"""Chat with the panel: questions about a finished case.

For each question:
  1. emergency check in code (no model): an emergency gets crisis or 911 guidance at once
  2. the coordinator routes it to the one or two most relevant panel members (pharmacist
     for medication questions); code enforces "only this case's panel, at most two".
     A connection question ("why are my acne and my weight related?") goes to the
     specialists who posted those findings on the case board, and the coordinator (who
     challenged every explanation in the debate) adds what else could explain it; code checks
     whether the board really links the two things, and says so if it does not
  3. those specialists give the coordinator short notes, in parallel, with their own memory of
     this chat. For speed they answer from what the panel already reviewed (no new live
     searches) and cite only sources the panel already gathered
  4. the coordinator writes the ONE short answer the patient sees, from those notes
  5. the safety reviewer checks that answer (model), then code checks block anything left
  6. the exchange is saved for this user and case

Memory: each panel member keeps its own message history for this case (including its tool
calls). Before each run the history is trimmed to MEMORY_CHAR_BUDGET by dropping whole
turns from the oldest end; a turn starts at a user question, so a tool call and its result
are always kept or dropped together. The case context is not stored in memory: it is
rebuilt fresh as the first message of every run (and, being identical each time, cached).
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import asdict
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, NativeOutput
from pydantic_ai.usage import UsageLimits
from pydantic_ai.messages import (
    ModelMessage, ModelMessagesTypeAdapter, ModelRequest, ToolCallPart, ToolReturnPart, UserPromptPart,
)

from . import board, db, defenses, llm, safety
from .budget import Budget, DailyBudgetExceeded
from .events import RunEvents
from .intake import decide_modes
from .panel import (
    AgentDeps, SAFETY_PROMPT, compact_pharmacist, compact_report, member_of, mode_text, profile, questionnaire_text,
)
from .profiles import to_questionnaire
from .registry import BY_ID, PHARMACIST_ID
from .schemas import ChatAnswerOutput, ChatRouteOutput, ChatWrapUpOutput, ProfileData, SafetyReviewOutput

PROMPTS = Path(__file__).resolve().parent / "prompts"
ROUTER_PROMPT = defenses.prompt_text((PROMPTS / "chat_router.md").read_text())
CHAT_PROMPT = defenses.prompt_text((PROMPTS / "specialist_chat.md").read_text())
WRAPUP_PROMPT = defenses.prompt_text((PROMPTS / "chat_wrapup.md").read_text())
ANSWER_PROMPT = defenses.prompt_text((PROMPTS / "chat_answer.md").read_text())
# "fast": the coordinator reads the chosen specialists' panel reviews and answers in one step
# (3 model calls in a row: route, answer, safety). "notes": the specialists first write fresh
# notes for the coordinator (4 calls in a row; slower, a little richer).
CHAT_MODE = os.environ.get("CC_CHAT_MODE", "fast")

MAX_QUESTION_CHARS = 1500
MAX_ANSWERERS = 2
LIFESTYLE = "lifestyle"
MEMORY_CHAR_BUDGET = 14_000      # per panel member, about 3,500 tokens of earlier turns
DIGEST_TURNS = 4                 # recent turns the coordinator sees
QUESTION_BUDGET_USD = 0.03
TOOL_CAP = {"specialist": 0, PHARMACIST_ID: 0}   # no live searches in chat (speed); the panel already gathered sources
MED_WORDS = re.compile(r"\b(medic\w*|pill\w*|dose|dosage|drug\w*|tablet\w*|interact\w*|side effects?|prescri\w*|supplement\w*|"
                       r"vitamin\w*|statin\w*|warfarin|naproxen|ibuprofen|aspirin|metformin|taking|refill)\b", re.I)


REF_IN_TEXT = re.compile(r"\s*\((?:\s*[a-z_]+\.[A-Z]\d+\s*,?)+\)")


class ChatError(RuntimeError):
    """Shown to the user."""


# ---- memory: trim whole turns so tool calls stay paired ---------------------------------

def split_turns(messages: list[ModelMessage]) -> list[list[ModelMessage]]:
    """A turn starts at a request carrying the user's question; everything after it (tool
    calls, tool results, the answer) belongs to that turn."""
    turns: list[list[ModelMessage]] = []
    for m in messages:
        if isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts):
            turns.append([m])
        elif turns:
            turns[-1].append(m)
        # a leading orphan (no question before it) is dropped
    return turns


def trim_memory(messages: list[ModelMessage], max_chars: int = MEMORY_CHAR_BUDGET) -> list[ModelMessage]:
    """Keep the newest whole turns that fit in max_chars (always at least the last turn)."""
    turns = split_turns(messages)
    kept: list[list[ModelMessage]] = []
    total = 0
    for turn in reversed(turns):
        size = len(ModelMessagesTypeAdapter.dump_json(turn))
        if kept and total + size > max_chars:
            break
        kept.append(turn)
        total += size
    return [m for turn in reversed(kept) for m in turn]


def tool_pairs_intact(messages: list[ModelMessage]) -> bool:
    """Every tool result answers an earlier call in the list, and every call gets a result."""
    calls, returns = set(), set()
    for m in messages:
        for p in m.parts:
            if isinstance(p, ToolCallPart):
                calls.add(p.tool_call_id)
            elif isinstance(p, ToolReturnPart):
                if p.tool_call_id not in calls:
                    return False
                returns.add(p.tool_call_id)
    return calls == returns


def load_memory(user_id: int, case_id: int, agent_key: str) -> list[ModelMessage]:
    raw = db.get_memory(user_id, case_id, agent_key)
    if not raw:
        return []
    try:
        return list(ModelMessagesTypeAdapter.validate_json(raw))
    except Exception:
        return []  # unreadable memory is dropped rather than breaking the chat


def save_memory(user_id: int, case_id: int, agent_key: str, messages: list[ModelMessage]) -> None:
    db.set_memory(user_id, case_id, agent_key, ModelMessagesTypeAdapter.dump_json(trim_memory(messages)).decode())


# ---- routing ------------------------------------------------------------------------------

def panel_members(result: dict[str, Any]) -> list[str]:
    members = list((result.get("specialists") or {}).keys())
    if result.get("consult"):
        members.append(result["consult"]["specialty"])
    if result.get("pharmacist"):
        members.append(PHARMACIST_ID)
    life = result.get("lifestyle") or {}
    if life.get("posts") or life.get("steps"):
        members.append(LIFESTYLE)
    return members


def name_of(member: str) -> str:
    return board.member_name(member)


def connection_plan(route: ChatRouteOutput | None, result: dict[str, Any], members: list[str]) -> dict[str, Any] | None:
    """For a connection question: who answers (the members who posted the findings, at most
    two) and whether the board really links the two things. The coordinator adds the
    challenge in its wrap-up. Decided in
    code from the board and the explanation cards, never by the model alone."""
    if not route or not route.connection_question:
        return None
    posts = board.index(result.get("board") or [])
    a = [r for r in dict.fromkeys(route.posts_a) if r in posts]
    b = [r for r in dict.fromkeys(route.posts_b) if r in posts]

    def best(refs: list[str], exclude: set[str]) -> str | None:
        count: dict[str, int] = {}
        for r in refs:
            who = posts[r]["by"]
            if who in members and who not in exclude:
                count[who] = count.get(who, 0) + 1
        return max(count, key=lambda k: (count[k], -members.index(k))) if count else None

    first = best(a, set()) or best(b, set())
    second = best(b, {first} if first else set()) or best(a + b, {first} if first else set())
    answerers = [x for x in (first, second) if x][:MAX_ANSWERERS]
    if not answerers:
        answerers = [m for m in members if m != PHARMACIST_ID][:1]
    cards = [c for c in ((result.get("summary") or {}).get("explanations") or [])
             if set(c["refs"]) & set(a) and set(c["refs"]) & set(b)]
    if cards:
        status = "linked"
    elif a and b:
        status = "both_on_board_no_card"
    else:
        status = "not_on_board"
    return {"topic_a": route.topic_a or "the first thing", "topic_b": route.topic_b or "the second thing",
            "posts_a": a, "posts_b": b, "cards": [c["id"] for c in cards], "status": status,
            "answerers": answerers}


def debate_challenges(plan: dict[str, Any], result: dict[str, Any]) -> str:
    """The coordinator's own round-3 challenges of the cards that link the two things."""
    cands = {c["id"]: c for c in (result.get("debate") or {}).get("candidates", [])}
    cards = {c["id"]: c for c in ((result.get("summary") or {}).get("explanations") or [])}
    lines = []
    for cid in plan["cards"]:
        ch = (cands.get(cid) or {}).get("challenge") or {}
        lines += [f"- {cid} {cards[cid]['title']}: you said {ch.get('verdict', '?')}: {ch.get('reason', '')}"]
        lines += [f"  simpler explanation: {x}" for x in ch.get("simpler_explanations", [])]
    return "<your_challenges_in_the_debate>\n" + ("\n".join(lines) or "(no card links them)") + "\n</your_challenges_in_the_debate>"


def connection_block(plan: dict[str, Any], result: dict[str, Any]) -> str:
    posts = board.index(result.get("board") or [])
    cards = {c["id"]: c for c in ((result.get("summary") or {}).get("explanations") or [])}
    line = lambda r: f"- {r}: {posts[r]['line']} ({posts[r]['system']})"  # noqa: E731
    status = {
        "linked": "The panel's explanation cards DO link these two things: " + "; ".join(
            f"{cid} '{cards[cid]['title']}' (argues against: {' / '.join(cards[cid]['argues_against'][:2])})" for cid in plan["cards"]),
        "both_on_board_no_card": "Both things are on the case board, but NO explanation card links them. Say that the panel "
                                 "did not find a supported link, and what could help tell; do not invent one.",
        "not_on_board": "The case board has nothing about " + " and ".join(
            t for t, refs in ((plan["topic_a"], plan["posts_a"]), (plan["topic_b"], plan["posts_b"])) if not refs)
            + ". Say plainly that the panel did not find a link in these records; do not invent one.",
    }[plan["status"]]
    lines_a = "\n".join(line(r) for r in plan["posts_a"]) or "(none)"
    lines_b = "\n".join(line(r) for r in plan["posts_b"]) or "(none)"
    return (f"<connection_question>\nThe patient asks how '{plan['topic_a']}' and '{plan['topic_b']}' are related.\n"
            f"Posts about {plan['topic_a']}:\n{lines_a}\nPosts about {plan['topic_b']}:\n{lines_b}\n{status}\n</connection_question>")


def enforce_route(route: ChatRouteOutput | None, question: str, members: list[str]) -> tuple[list[str], str]:
    """Only this case's panel, at most two, pharmacist for medication questions."""
    picked = [s for s in dict.fromkeys(route.specialists if route else []) if s in members]
    reason = route.reason if route else "Routed by keywords (the coordinator was unavailable)."
    medication = (route.medication_question if route else False) or bool(MED_WORDS.search(question))
    if medication and PHARMACIST_ID in members and PHARMACIST_ID not in picked:
        picked = [PHARMACIST_ID] + picked
    if not picked:
        named = [m for m in members if name_of(m).lower().split()[0] in question.lower()]
        picked = named or [m for m in members if m != PHARMACIST_ID][:1] or members[:1]
    return picked[:MAX_ANSWERERS], reason


def digest(history: list[dict[str, Any]], turns: int = DIGEST_TURNS) -> str:
    lines = []
    for msg in history[-turns * 2:]:
        if msg["role"] == "user":
            lines.append(f"Patient asked: {msg['content'][:300]}")
        elif msg["role"] == "panel":
            who = ", ".join(a["name"] for a in msg["meta"].get("answers", []))
            lines.append(f"Panel ({who}) answered; wrap-up: {msg['meta'].get('wrap_up', '')[:300]}")
        elif msg["role"] == "safety":
            lines.append("App showed emergency guidance.")
    return "\n".join(lines) or "(this is the first question)"


# ---- context for an answering specialist ------------------------------------------------

def panel_sources(result: dict[str, Any], spec: str | None = None) -> dict[str, str]:
    """url -> title for every source the panel already retrieved (optionally one member's)."""
    out: dict[str, str] = {}
    reports = dict(result.get("specialists") or {})
    if result.get("consult"):
        reports[result["consult"]["specialty"]] = result["consult"]
    for k, r in reports.items():
        if spec in (None, k):
            out.update({src["url"]: src.get("title") or src["url"] for src in r.get("sources", [])})
    if spec in (None, PHARMACIST_ID):
        out.update({u: "FDA drug label" for i in (result.get("pharmacist") or {}).get("issues", []) for u in i.get("source_urls", [])})
    if spec in (None, LIFESTYLE):
        out.update({st["source_url"]: st.get("source_title") or "MedlinePlus" for st in (result.get("lifestyle") or {}).get("steps", [])})
    for c in ((result.get("summary") or {}).get("explanations") or []):
        if c.get("pattern") and spec is None:
            out[c["pattern"]["source"]] = f"{c['pattern']['name']} (MedlinePlus)"
    return out


def case_context(spec: str, result: dict[str, Any], q_text: str, m_text: str) -> str:
    summary = result.get("summary") or {}
    parts = [f"<profile>\n{profile(spec)}\n</profile>", f"<mode>\n{m_text}\n</mode>",
             defenses.wrap("questionnaire", q_text)]
    if result.get("board"):
        parts.append(board.render(result["board"]))
    if summary:
        cards = summary.get("explanations")
        links = ("\nPossible explanations the panel discussed (patterns, not diagnoses):\n" + "\n".join(
            f"- {c['id']} [{c['strength']} match] {c['title']} (posts: {', '.join(c['refs'])}; argues against: "
            f"{' / '.join(c['argues_against'][:2])})" for c in cards)) if cards is not None else ("\nConnections:\n" + "\n".join(
            f"- {k['text']} [{', '.join(k['finding_refs'])}]" for k in summary.get("connections", [])))
        parts.append("<case_summary>\n" + summary.get("plain_language_summary", "") + "\nKey findings:\n" + "\n".join(
            f"- {k['text']} [{', '.join(k['finding_refs'])}]" for k in summary.get("key_findings", [])) + links + "\n</case_summary>")
    report = (result.get("specialists") or {}).get(spec) or (result.get("consult") if (result.get("consult") or {}).get("specialty") == spec else None)
    if spec == PHARMACIST_ID and result.get("pharmacist"):
        parts.append(f"<your_report>\n{compact_pharmacist(result['pharmacist'])}\n</your_report>")
    elif report:
        quotes = "\n".join(f"- {f['id']}: \"{f['quote']}\" ({f['document']})" for f in report["findings"])
        parts.append(f"<your_report>\n{compact_report(report)}\nQuotes:\n{quotes}\n</your_report>")
    r2 = (result.get("round2") or {}).get(spec)
    if r2:
        parts.append("<your_conference_comments>\n" + "\n".join(
            [f"- proposed: {c['title']}" if "title" in c else f"- connection: {c['connection']}" for c in r2.get("connections", [])]
            + [f"- disagreed with {d['with_specialty']}: {d['point']}" for d in r2.get("disagreements", [])]) + "\n</your_conference_comments>")
    mine = panel_sources(result, spec)
    if mine:
        parts.append("<sources_you_already_found>\n" + "\n".join(f"- {t}: {u}" for u, t in mine.items()) + "\n</sources_you_already_found>")
    life = result.get("lifestyle") or {}
    if spec == LIFESTYLE and (life.get("steps") or life.get("posts")):
        parts.append("<your_self_care_steps>\n" + "\n".join(f"- [{st['category']}] {st['action']} (source: {st['source_url']})"
                                                          for st in life.get("steps", [])) + "\n</your_self_care_steps>")
    return "<case_context>\n" + "\n\n".join(parts) + "\n</case_context>"


# ---- the exchange -------------------------------------------------------------------------

async def answer_question(*, user_id: int, case_id: int, question: str, events: RunEvents) -> dict[str, Any]:
    question = question.strip()
    if not question:
        raise ChatError("Please type a question.")
    if len(question) > MAX_QUESTION_CHARS:
        raise ChatError(f"Please keep questions under {MAX_QUESTION_CHARS} characters.")
    case = db.get_case(user_id, case_id, with_result=True)
    if not case:
        raise ChatError("No such case.")
    result = case["result"]
    if not result or not result.get("specialists"):
        raise ChatError("The panel needs to finish reviewing this case before it can answer questions.")
    history = db.list_chat(user_id, case_id)
    db.add_chat_message(user_id, case_id, "user", question)
    events.emit("chat_started", question=question)

    # 1. emergency check in code: no model, no delay
    emergency = safety.emergency_check(question)
    if emergency["emergency"]:
        text = emergency["message"]
        meta = {"emergency": emergency, "answers": [], "wrap_up": text}
        mid = db.add_chat_message(user_id, case_id, "safety", text, meta)
        msg = {"id": mid, "role": "safety", "content": text, "meta": meta}
        events.emit("final", message=msg, status="emergency")
        return msg

    meter = llm.UsageMeter(member_of=member_of)

    def on_spend(r: llm.CallRecord) -> None:
        events.emit("spend", agent=r.agent, member=r.member, call_usd=round(r.cost_usd, 6), total_usd=meter.totals()["cost_usd"])
        try:
            db.add_usage(user_id, case_id, events.run_id, "chat", asdict(r))
        except Exception:  # logging must never break the chat
            pass

    meter.listeners.append(on_spend)
    try:
        budget = Budget(meter, str(user_id), run_limit=QUESTION_BUDGET_USD)
    except DailyBudgetExceeded as exc:
        raise ChatError(str(exc)) from exc

    snapshot = ProfileData.model_validate(case["profile_snapshot"]) if case["profile_snapshot"] else None
    q = to_questionnaire(snapshot, case["main_concern"]) if snapshot else None
    modes = decide_modes(q, True) if q else None
    q_text = questionnaire_text(q, modes) if q else ""
    m_text = mode_text(modes, q) if modes else ""
    members = panel_members(result)
    coordinator = (result.get("modes") or {}).get("coordinator", "internal_medicine")
    m = llm.model()
    trace = f"{events.run_id}"

    try:
        # 2. route
        events.emit("coordinator_thinking", stage="routing")
        member_lines = []
        for s in members:
            if s == PHARMACIST_ID:
                issues = (result.get("pharmacist") or {}).get("issues", [])
                member_lines.append(f"- {s}: Clinical pharmacist. Items: " + "; ".join(i["explanation"][:120] for i in issues[:3]))
            elif s == LIFESTYLE:
                member_lines.append(f"- {s}: Lifestyle & prevention. Self-care steps and lifestyle facts.")
            else:
                rep = (result.get("specialists") or {}).get(s) or result.get("consult") or {}
                member_lines.append(f"- {s}: {BY_ID[s].name}. Findings: " + "; ".join(f["statement"][:100] for f in rep.get("findings", [])[:6])
                                    + (". Concerns: " + "; ".join(c["concern"][:80] for c in rep.get("concerns", [])[:3]) if rep.get("concerns") else ""))
        router = Agent(m, instructions=ROUTER_PROMPT, output_type=NativeOutput(ChatRouteOutput), retries=1)
        route = None
        try:
            route = await llm.run_agent(router, "\n\n".join([
                "<panel_members>\n" + "\n".join(member_lines) + "\n</panel_members>",
                board.render(result.get("board") or []),
                f"<recent_conversation>\n{digest(history)}\n</recent_conversation>",
                f"<question>\n{question}\n</question>"]), meter=meter, agent_name="chat_router", label="route",
                model_settings=llm.settings(600, "none", trace))
        except Exception:
            pass  # enforce_route falls back to keywords
        answerers, reason = enforce_route(route, question, members)
        plan = connection_plan(route, result, members)
        if plan:
            answerers = plan["answerers"]
            reason = (f"Connection question ({plan['topic_a']} and {plan['topic_b']}): the specialists who posted those findings, "
                      f"with the coordinator's challenge in the wrap-up. Board link: {plan['status'].replace('_', ' ')}.")
        events.emit("chat_routed", specialists=answerers, names=[name_of(s) for s in answerers], reason=reason,
                    connection=plan)

        if CHAT_MODE == "fast":
            return await _fast_answer(user_id=user_id, case_id=case_id, question=question, events=events, result=result,
                                      q_text=q_text, m_text=m_text, history=history, answerers=answerers, reason=reason,
                                      plan=plan, coordinator=coordinator, meter=meter, budget=budget, m=m, trace=trace)

        # 3. specialists' notes for the coordinator, in parallel, each with its own trimmed memory.
        # No live searches in chat (they cost 5-15 s each): the panel already gathered its sources.
        answers: list[dict[str, Any]] = []
        known_urls = panel_sources(result)
        valid_refs = {f["id"] for r in (result.get("specialists") or {}).values() for f in r["findings"]}
        valid_refs |= {f["id"] for f in (result.get("consult") or {}).get("findings", [])}
        valid_refs |= {i["id"] for i in (result.get("pharmacist") or {}).get("issues", [])}
        valid_refs |= {p_["id"] for p_ in result.get("board") or []}

        async def answer(spec: str) -> None:
            agent_id = f"chat.{spec}"
            events.agent_started(agent_id, "chat_specialist", spec, None, ["case context", "chat memory"])
            events.emit("specialist_started", agent=agent_id, specialty=spec, name=name_of(spec), round="chat")
            agent = Agent(m, deps_type=AgentDeps, instructions=CHAT_PROMPT, output_type=NativeOutput(ChatAnswerOutput), retries=1)
            deps = AgentDeps(events, agent_id, spec, str(user_id), str(case_id), TOOL_CAP.get(spec, TOOL_CAP["specialist"]))
            memory = trim_memory(load_memory(user_id, case_id, spec))
            context = ModelRequest(parts=[UserPromptPart(content=case_context(spec, result, q_text, m_text))])
            started = time.perf_counter()
            try:
                run = await asyncio.wait_for(agent.run(
                    (connection_block(plan, result) + "\n\n" if plan else "") + f"The patient asks: {question}",
                    message_history=[context, *memory], deps=deps,
                    model_settings=llm.settings(700, "none", f"{trace}-{spec}"),
                    usage_limits=UsageLimits(request_limit=2)), timeout=60)
            except Exception as exc:
                events.agent_finished(agent_id, "failed", f"error: {str(exc)[:160]}")
                events.emit("error", agent=agent_id, specialty=spec, message="This specialist could not answer right now.")
                return
            usage = llm._usage_from(run.new_messages())  # this run only, not the reloaded memory
            meter.add(llm.CallRecord("chat_specialist", agent_id, usage[0], usage[1], usage[2], usage[3], usage[4], usage[5],
                                     round(time.perf_counter() - started, 2), llm.cost_usd(usage[1], usage[2], usage[3], usage[4]), True))
            save_memory(user_id, case_id, spec, [*memory, *run.new_messages()])
            out: ChatAnswerOutput = run.output
            # Ids belong in finding_refs; strip any the model wrote into the text, e.g. "(gastroenterology.F1, hematology.F2)".
            out.answer = REF_IN_TEXT.sub("", out.answer)
            answers.append({
                "specialty": spec, "name": name_of(spec), "text": out.answer.strip(),
                "finding_refs": [r for r in out.finding_refs if r in valid_refs],
                "sources": [{"title": known_urls[s.url], "url": s.url, "used_for": s.used_for} for s in out.sources if s.url in known_urls],
                "ask_your_doctor": out.ask_your_doctor, "confidence": out.confidence, "source_note": None,
            })
            events.agent_finished(agent_id, "completed", "completed", out.answer[:120])
            events.emit("specialist_done", agent=agent_id, specialty=spec, name=name_of(spec), round="chat")

        await asyncio.gather(*[answer(s) for s in answerers])
        answers.sort(key=lambda a: answerers.index(a["specialty"]))
        if not answers:
            raise ChatError("The panel could not answer right now. Please try again in a moment.")

        # 4. the coordinator's single answer (what the patient sees), from the specialists' notes
        wrap_up = ""
        ask_doctor: str | None = None
        if budget.can_start("coordinator"):
            events.emit("coordinator_thinking", stage="wrap_up")
            wrapper = Agent(m, instructions=WRAPUP_PROMPT, output_type=NativeOutput(ChatWrapUpOutput), retries=1)
            try:
                wrap = await llm.run_agent(wrapper, (connection_block(plan, result) + "\n\n" + debate_challenges(plan, result) + "\n\n"
                                                     if plan else "")
                    + f"<question>\n{question}\n</question>\n\n<specialist_notes>\n" + "\n".join(
                    f"- {a['name']}: {a['text']}" + (f" (suggested question for the doctor: {a['ask_your_doctor']})" if a["ask_your_doctor"] else "")
                    for a in answers) + "\n</specialist_notes>", meter=meter, agent_name="chat_wrapup",
                    label="wrap_up", model_settings=llm.settings(600, "none", trace))
                wrap_up = REF_IN_TEXT.sub("", wrap.wrap_up).strip()
                ask_doctor = (wrap.ask_your_doctor or "").strip() or None
            except Exception:
                wrap_up = ""

        # 5. safety: model reviewer, then code checks
        events.emit("safety_check", stage="started")
        single = bool(wrap_up)   # the coordinator answered: only its answer is shown, so only it is reviewed
        if single:
            items = [("W", wrap_up)] + ([("WQ", ask_doctor)] if ask_doctor else [])
        else:                    # fallback: the coordinator failed, so the specialists' notes are shown instead
            items = [(f"A{i}", a["text"]) for i, a in enumerate(answers, 1)]
            items += [(f"Q{i}", a["ask_your_doctor"]) for i, a in enumerate(answers, 1) if a["ask_your_doctor"]]
        edits_applied: list[dict] = []
        emergency_flag = False
        if budget.can_start("safety"):
            reviewer = Agent(m, instructions=SAFETY_PROMPT, output_type=NativeOutput(SafetyReviewOutput), retries=1)
            try:
                review = await llm.run_agent(reviewer, "These items are chat answers to the patient's question.\n\n"
                                             f"<question>\n{question}\n</question>\n\n<summary_items>\n"
                                             + "\n".join(f"{i}: {t}" for i, t in items) + "\n</summary_items>",
                                             meter=meter, agent_name="chat_safety", label="safety",
                                             model_settings=llm.settings(1500, "low", trace))
                valid = {i for i, _ in items}
                for e in review.edits:
                    if e.item_id in valid:
                        edits_applied.append(e.model_dump())
                emergency_flag = review.emergency
            except Exception:
                pass
        edits = {e["item_id"]: (e["new_text"] if e["action"] == "rewrite" else None) for e in edits_applied}
        blocked: list[dict] = []
        for i, a in enumerate(answers, 1):
            a["text"] = edits.get(f"A{i}", a["text"]) if f"A{i}" in edits else a["text"]
            if f"Q{i}" in edits:
                a["ask_your_doctor"] = edits[f"Q{i}"]
        if "W" in edits:
            wrap_up = edits["W"] or ""
        if "WQ" in edits:
            ask_doctor = edits["WQ"]
        if ask_doctor and safety.violations(ask_doctor):
            blocked.append({"field": "ask_your_doctor", "problems": safety.violations(ask_doctor), "original": ask_doctor})
            ask_doctor = None
        for a in answers:  # code pass: last line of defense
            for key in ("text", "ask_your_doctor"):
                if a.get(key) and safety.violations(a[key]):
                    blocked.append({"specialty": a["specialty"], "field": key, "problems": safety.violations(a[key]), "original": a[key]})
                    a[key] = ("I can't answer that part here. Please bring this question to your own doctor, who can look at "
                              "your full situation.") if key == "text" else None
        if wrap_up and safety.violations(wrap_up):
            blocked.append({"field": "wrap_up", "problems": safety.violations(wrap_up), "original": wrap_up})
            wrap_up = ("I can't answer that part here. Please bring this question to your own doctors; they can look at "
                       "your whole situation.")
        answers = [a for a in answers if a["text"]]
        events.emit("safety_check", stage="done", edits=len(edits_applied), blocked=len(blocked))

        # 6. save
        sources = list({src["url"]: src for a in answers for src in a["sources"]}.values())[:3]
        meta = {"style": "coordinator" if single else "panel", "answers": answers, "wrap_up": wrap_up, "ask_your_doctor": ask_doctor,
                "sources": sources, "consulted": [{"id": a["specialty"], "name": a["name"]} for a in answers],
                "routed": answerers, "route_reason": reason, "connection": plan,
                "coordinator": coordinator, "safety": {"edits": edits_applied, "blocked": blocked},
                "emergency": {"emergency": True, "kind": "medical", "matches": [], "message": safety.EMERGENCY_GENERAL} if emergency_flag else None,
                "usage": meter.totals()}
        content = (wrap_up if single else "\n\n".join(f"{a['name']}: {a['text']}" for a in answers))
        mid = db.add_chat_message(user_id, case_id, "panel", content, meta)
        msg = {"id": mid, "role": "panel", "content": content, "meta": meta}
        events.emit("final", message=msg, status="answered", total_usd=meter.totals()["cost_usd"])
        return msg
    finally:
        budget.close()


def consulted_reviews(result: dict[str, Any], answerers: list[str]) -> str:
    """The panel reviews of the consulted members: what the coordinator reads to answer."""
    parts = []
    for spec in answerers:
        report = (result.get("specialists") or {}).get(spec) or (result.get("consult") if (result.get("consult") or {}).get("specialty") == spec else None)
        if spec == PHARMACIST_ID and result.get("pharmacist"):
            body = compact_pharmacist(result["pharmacist"])
        elif spec == LIFESTYLE:
            life = result.get("lifestyle") or {}
            body = "\n".join([f"- fact: {p_['line']}" for p_ in life.get("posts", [])]
                             + [f"- self-care step [{st['category']}]: {st['action']}" for st in life.get("steps", [])])
        elif report:
            body = compact_report(report) + "\nQuotes:\n" + "\n".join(f"- {f['id']}: \"{f['quote']}\" ({f['document']})" for f in report["findings"])
            if report.get("questions_for_doctor"):
                body += "\nQuestions this specialist suggested for the doctor: " + " | ".join(report["questions_for_doctor"])
        else:
            continue
        srcs = panel_sources(result, spec)
        if srcs:
            body += "\nSources this specialist found:\n" + "\n".join(f"- {t}: {u}" for u, t in srcs.items())
        parts.append(f'<review of="{name_of(spec)}">\n{body}\n</review>')
    return "<consulted_reviews>\n" + ("\n\n".join(parts) or "(none)") + "\n</consulted_reviews>"


async def _fast_answer(*, user_id: int, case_id: int, question: str, events: RunEvents, result: dict[str, Any], q_text: str,
                       m_text: str, history: list[dict[str, Any]], answerers: list[str], reason: str, plan: dict[str, Any] | None,
                       coordinator: str, meter: llm.UsageMeter, budget: Budget, m: Any, trace: str) -> dict[str, Any]:
    """The coordinator reads the consulted specialists' panel reviews and writes the one answer;
    then the safety reviewer and the code checks run, exactly as in the slower mode."""
    for spec in answerers:   # the consulted doctors light up while their reviews are read
        events.emit("specialist_started", agent=f"chat.{spec}", specialty=spec, name=name_of(spec), round="chat")
    events.emit("coordinator_thinking", stage="wrap_up")
    summary = result.get("summary") or {}
    cards = "\n".join(f"- {c['id']} [{c['strength']} match] {c['title']} (argues against: {' / '.join(c['argues_against'][:2])})"
                      for c in summary.get("explanations") or [])
    prompt = "\n\n".join(x for x in [
        board.render(result.get("board") or []),
        f"<mode>\n{m_text}\n</mode>", defenses.wrap("questionnaire", q_text),
        "<case_summary>\n" + summary.get("plain_language_summary", "") + ("\nPossible explanations the panel discussed:\n" + cards if cards else "")
        + "\n</case_summary>",
        consulted_reviews(result, answerers),
        (connection_block(plan, result) + "\n\n" + debate_challenges(plan, result)) if plan else "",
        f"<recent_conversation>\n{digest(history)}\n</recent_conversation>",
        f"<question>\n{question}\n</question>",
    ] if x)
    known_urls = panel_sources(result)
    valid_refs = {p_["id"] for p_ in result.get("board") or []}
    answerer = Agent(m, instructions=ANSWER_PROMPT, output_type=NativeOutput(ChatAnswerOutput), retries=1)
    try:
        out: ChatAnswerOutput = await llm.run_agent(answerer, prompt, meter=meter, agent_name="chat_wrapup", label="answer",
                                                    model_settings=llm.settings(700, "none", trace))
    except Exception as exc:
        for spec in answerers:
            events.emit("error", agent=f"chat.{spec}", specialty=spec, message="The panel could not answer right now.")
        raise ChatError("The panel could not answer right now. Please try again in a moment.") from exc
    for spec in answerers:
        events.emit("specialist_done", agent=f"chat.{spec}", specialty=spec, name=name_of(spec), round="chat")
    text = REF_IN_TEXT.sub("", out.answer).strip()
    ask_doctor = (out.ask_your_doctor or "").strip() or None
    sources = [{"title": known_urls[s_.url], "url": s_.url} for s_ in out.sources if s_.url in known_urls][:3]

    # safety: model reviewer, then code checks (same rules as everywhere)
    events.emit("safety_check", stage="started")
    items = [("W", text)] + ([("WQ", ask_doctor)] if ask_doctor else [])
    edits_applied: list[dict] = []
    emergency_flag = False
    if budget.can_start("safety"):
        reviewer = Agent(m, instructions=SAFETY_PROMPT, output_type=NativeOutput(SafetyReviewOutput), retries=1)
        try:
            review = await llm.run_agent(reviewer, "These items are the chat answer to the patient's question.\n\n"
                                         f"<question>\n{question}\n</question>\n\n<summary_items>\n"
                                         + "\n".join(f"{i}: {t}" for i, t in items) + "\n</summary_items>",
                                         meter=meter, agent_name="chat_safety", label="safety",
                                         model_settings=llm.settings(1200, "low", trace))
            edits_applied = [e.model_dump() for e in review.edits if e.item_id in {"W", "WQ"}]
            emergency_flag = review.emergency
        except Exception:
            pass
    edits = {e["item_id"]: (e["new_text"] if e["action"] == "rewrite" else None) for e in edits_applied}
    text = edits.get("W", text) if "W" in edits else text
    ask_doctor = edits.get("WQ", ask_doctor) if "WQ" in edits else ask_doctor
    blocked: list[dict] = []
    if text and safety.violations(text):
        blocked.append({"field": "answer", "problems": safety.violations(text), "original": text})
        text = None
    if not text:
        text = "I can't answer that part here. Please bring this question to your own doctors; they can look at your whole situation."
    if ask_doctor and safety.violations(ask_doctor):
        blocked.append({"field": "ask_your_doctor", "problems": safety.violations(ask_doctor), "original": ask_doctor})
        ask_doctor = None
    events.emit("safety_check", stage="done", edits=len(edits_applied), blocked=len(blocked))

    meta = {"style": "coordinator", "mode": "fast", "answers": [], "wrap_up": text, "ask_your_doctor": ask_doctor, "sources": sources,
            "finding_refs": [r for r in out.finding_refs if r in valid_refs],
            "consulted": [{"id": s_, "name": name_of(s_)} for s_ in answerers], "routed": answerers, "route_reason": reason,
            "connection": plan, "coordinator": coordinator, "safety": {"edits": edits_applied, "blocked": blocked},
            "emergency": {"emergency": True, "kind": "medical", "matches": [], "message": safety.EMERGENCY_GENERAL} if emergency_flag else None,
            "usage": meter.totals()}
    mid = db.add_chat_message(user_id, case_id, "panel", text, meta)
    msg = {"id": mid, "role": "panel", "content": text, "meta": meta}
    events.emit("final", message=msg, status="answered", total_usd=meter.totals()["cost_usd"])
    return msg


def new_chat_events(user_id: int, case_id: int) -> RunEvents:
    return RunEvents(run_id=f"chat-{uuid.uuid4().hex[:10]}", user_id=str(user_id), case_id=f"case-{case_id}")
