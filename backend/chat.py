"""Chat with the panel: questions about a finished case.

For each question:
  1. emergency check in code (no model): an emergency gets crisis or 911 guidance at once
  2. the coordinator routes it to the one or two most relevant panel members (pharmacist
     for medication questions); code enforces "only this case's panel, at most two".
     A connection question ("why are my acne and my weight related?") goes to the
     specialists who posted those findings on the case board plus the skeptic; code checks
     whether the board really links the two things, and says so if it does not
  3. those specialists answer in their own voice, in parallel, with their own memory of
     this chat and the trusted-source tools
  4. the coordinator adds a short wrap-up
  5. the safety reviewer checks every answer (model), then code checks block anything left
  6. the exchange is saved for this user and case

Memory: each panel member keeps its own message history for this case (including its tool
calls). Before each run the history is trimmed to MEMORY_CHAR_BUDGET by dropping whole
turns from the oldest end; a turn starts at a user question, so a tool call and its result
are always kept or dropped together. The case context is not stored in memory: it is
rebuilt fresh as the first message of every run (and, being identical each time, cached).
"""

from __future__ import annotations

import asyncio
import contextlib
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
    LIFESTYLE_TOOLS, AgentDeps, PHARMACIST_TOOLS, SAFETY_PROMPT, SPECIALIST_TOOLS, compact_pharmacist, compact_report, member_of,
    mode_text, open_sources, profile, questionnaire_text,
)
from .profiles import to_questionnaire
from .registry import BY_ID, PHARMACIST_ID
from .schemas import ChatAnswerOutput, ChatRouteOutput, ChatWrapUpOutput, ProfileData, SafetyReviewOutput

PROMPTS = Path(__file__).resolve().parent / "prompts"
ROUTER_PROMPT = defenses.prompt_text((PROMPTS / "chat_router.md").read_text())
CHAT_PROMPT = defenses.prompt_text((PROMPTS / "specialist_chat.md").read_text())
WRAPUP_PROMPT = defenses.prompt_text((PROMPTS / "chat_wrapup.md").read_text())

MAX_QUESTION_CHARS = 1500
MAX_ANSWERERS = 2
SKEPTIC = "skeptic"
LIFESTYLE = "lifestyle"
MEMORY_CHAR_BUDGET = 14_000      # per panel member, about 3,500 tokens of earlier turns
DIGEST_TURNS = 4                 # recent turns the coordinator sees
QUESTION_BUDGET_USD = 0.03
TOOL_CAP = {"specialist": 2, PHARMACIST_ID: 3}
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
    two, plus the skeptic) and whether the board really links the two things. Decided in
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
            "answerers": answerers + [SKEPTIC]}


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
    picked = [s for s in dict.fromkeys(route.specialists if route else []) if s in members and s != SKEPTIC]
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
    debate = result.get("debate") or {}
    if spec == SKEPTIC and debate.get("candidates"):
        parts.append("<your_debate_challenges>\n" + "\n".join(
            f"- {c['id']} {c['title']}: {(c.get('skeptic') or {}).get('verdict', '?')}, {(c.get('skeptic') or {}).get('reason', '')}"
            for c in debate["candidates"]) + "\n</your_debate_challenges>")
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
                      f"plus the skeptic. Board link: {plan['status'].replace('_', ' ')}.")
        events.emit("chat_routed", specialists=answerers, names=[name_of(s) for s in answerers], reason=reason,
                    connection=plan)

        # 3. answers, in parallel, each with its own trimmed memory
        sources_stack = contextlib.AsyncExitStack()
        toolset = await open_sources(sources_stack, events)
        answers: list[dict[str, Any]] = []
        valid_refs = {f["id"] for r in (result.get("specialists") or {}).values() for f in r["findings"]}
        valid_refs |= {f["id"] for f in (result.get("consult") or {}).get("findings", [])}
        valid_refs |= {i["id"] for i in (result.get("pharmacist") or {}).get("issues", [])}
        valid_refs |= {p_["id"] for p_ in result.get("board") or []}

        async def answer(spec: str) -> None:
            agent_id = f"chat.{spec}"
            events.agent_started(agent_id, "chat_specialist", spec, None, ["case context", "chat memory"])
            events.emit("specialist_started", agent=agent_id, specialty=spec, name=name_of(spec), round="chat")
            allowed = (PHARMACIST_TOOLS if spec == PHARMACIST_ID else LIFESTYLE_TOOLS if spec == LIFESTYLE
                       else set() if spec == SKEPTIC else SPECIALIST_TOOLS)
            tools = [toolset.filtered(lambda ctx, td: td.name in allowed)] if toolset and allowed else []
            agent = Agent(m, deps_type=AgentDeps, instructions=CHAT_PROMPT, output_type=NativeOutput(ChatAnswerOutput),
                          toolsets=tools, retries=1)
            deps = AgentDeps(events, agent_id, spec, str(user_id), str(case_id), TOOL_CAP.get(spec, TOOL_CAP["specialist"]))
            memory = trim_memory(load_memory(user_id, case_id, spec))
            context = ModelRequest(parts=[UserPromptPart(content=case_context(spec, result, q_text, m_text))])
            started = time.perf_counter()
            try:
                run = await asyncio.wait_for(agent.run(
                    (connection_block(plan, result) + "\n\n" if plan else "") + f"The patient asks: {question}",
                    message_history=[context, *memory], deps=deps,
                    model_settings=llm.settings(1500, "low", f"{trace}-{spec}"),
                    usage_limits=UsageLimits(request_limit=4)), timeout=120)
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
            unreachable = sorted({src for src, st in deps.tool_statuses if st == "unreachable"})
            answers.append({
                "specialty": spec, "name": name_of(spec), "text": out.answer.strip(),
                "finding_refs": [r for r in out.finding_refs if r in valid_refs],
                "sources": [s.model_dump() for s in out.sources if s.url in deps.tool_urls],
                "ask_your_doctor": out.ask_your_doctor, "confidence": out.confidence,
                "source_note": f"{' and '.join(unreachable)} could not be reached." if unreachable else None,
            })
            events.agent_finished(agent_id, "completed", "completed", out.answer[:120])
            events.emit("specialist_done", agent=agent_id, specialty=spec, name=name_of(spec), round="chat")

        async with sources_stack:
            await asyncio.gather(*[answer(s) for s in answerers])
        answers.sort(key=lambda a: answerers.index(a["specialty"]))
        if not answers:
            raise ChatError("The panel could not answer right now. Please try again in a moment.")

        # 4. wrap-up
        wrap_up = ""
        if budget.can_start("coordinator"):
            events.emit("coordinator_thinking", stage="wrap_up")
            wrapper = Agent(m, instructions=WRAPUP_PROMPT, output_type=NativeOutput(ChatWrapUpOutput), retries=1)
            try:
                wrap = await llm.run_agent(wrapper, f"<question>\n{question}\n</question>\n\n<answers>\n" + "\n".join(
                    f"- {a['name']}: {a['text']}" for a in answers) + "\n</answers>", meter=meter, agent_name="chat_wrapup",
                    label="wrap_up", model_settings=llm.settings(400, "none", trace))
                wrap_up = wrap.wrap_up.strip()
            except Exception:
                wrap_up = ""

        # 5. safety: model reviewer, then code checks
        events.emit("safety_check", stage="started")
        items = [(f"A{i}", a["text"]) for i, a in enumerate(answers, 1)]
        items += [(f"Q{i}", a["ask_your_doctor"]) for i, a in enumerate(answers, 1) if a["ask_your_doctor"]]
        if wrap_up:
            items.append(("W", wrap_up))
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
        for a in answers:  # code pass: last line of defense
            for key in ("text", "ask_your_doctor"):
                if a.get(key) and safety.violations(a[key]):
                    blocked.append({"specialty": a["specialty"], "field": key, "problems": safety.violations(a[key]), "original": a[key]})
                    a[key] = ("I can't answer that part here. Please bring this question to your own doctor, who can look at "
                              "your full situation.") if key == "text" else None
        if wrap_up and safety.violations(wrap_up):
            blocked.append({"field": "wrap_up", "problems": safety.violations(wrap_up), "original": wrap_up})
            wrap_up = "Please bring these points to your own doctors; they can look at your whole situation."
        answers = [a for a in answers if a["text"]]
        events.emit("safety_check", stage="done", edits=len(edits_applied), blocked=len(blocked))

        # 6. save
        meta = {"answers": answers, "wrap_up": wrap_up, "routed": answerers, "route_reason": reason, "connection": plan,
                "coordinator": coordinator, "safety": {"edits": edits_applied, "blocked": blocked},
                "emergency": {"emergency": True, "kind": "medical", "matches": [], "message": safety.EMERGENCY_GENERAL} if emergency_flag else None,
                "usage": meter.totals()}
        content = "\n\n".join(f"{a['name']}: {a['text']}" for a in answers) + (f"\n\nCoordinator: {wrap_up}" if wrap_up else "")
        mid = db.add_chat_message(user_id, case_id, "panel", content, meta)
        msg = {"id": mid, "role": "panel", "content": content, "meta": meta}
        events.emit("final", message=msg, status="answered", total_usd=meter.totals()["cost_usd"])
        return msg
    finally:
        budget.close()


def new_chat_events(user_id: int, case_id: int) -> RunEvents:
    return RunEvents(run_id=f"chat-{uuid.uuid4().hex[:10]}", user_id=str(user_id), case_id=f"case-{case_id}")
