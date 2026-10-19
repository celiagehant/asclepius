"""The case conference: specialists, pharmacist, lifestyle agent, a shared case board,
four rounds (independent review, connections, a debate led by the coordinator, recommendations), an
optional consult, the coordinator and the safety reviewer.

Flow for one case run:
  intake -> round 1: independent review (every active specialist + the pharmacist + the
            lifestyle agent, in parallel, with tools)
         -> the shared case board (built in code from validated findings)
         -> optional consult (one extra specialist, only if the cap allows; joins the board)
         -> round 2: connection round (members with abnormal posts read the whole board and
            propose up to 2 connections each; code merges them into candidates)
         -> round 3: debate (the coordinator challenges every candidate, the involved members
            defend, concede, support or challenge; code scores them) -> HARD STOP
            (the lifestyle agent writes self-care steps in parallel with round 3)
         -> round 4: recommendations (coordinator) -> safety review (model + code) -> final

What the server controls, never the model:
  - which patient, which specialty and which documents an agent sees (documents_for)
  - which tools it may call (filtered MCP toolset) and how many (tool cap per agent)
  - budgets, round count, timeouts
Every agent output is checked in code before anyone else sees it: quotes must appear in
the cited document, sources must be URLs a tool really returned, summary points must cite
existing findings, and forbidden language is removed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, NativeOutput, RunContext
from pydantic_ai.mcp import MCPToolset, StdioTransport

from . import board, conference, config, defenses, lifestyle, llm, patterns, safety, traps
from .budget import Budget, DailyBudgetExceeded
from .events import RunEvents
from .intake import run_intake
from .registry import BY_ID, MAX_ACTIVE_SPECIALISTS, PANEL_IDS, PHARMACIST_ID
from .schemas import (
    REGION_LABELS, CaseSummaryOutput, ConsultDecisionOutput, DocumentRecord, IntakeResult, Modes,
    ConnectionRoundOutput, LifestyleBoardOutput, LifestyleStepsOutput, PanelResponseOutput, PharmacistReportOutput,
    ChallengeOutput, Questionnaire, SafetyReviewOutput, SpecialistReportOutput,
)

HERE = Path(__file__).resolve().parent
PROFILES = HERE / "profiles"
PROMPTS = HERE / "prompts"
# Raw prompt files; defenses.prompt_text() applies the prompt layer when each agent is created.
SPECIALIST_PROMPT_RAW = (PROMPTS / "specialist_base.md").read_text()
PHARMACIST_PROMPT_RAW = (PROMPTS / "pharmacist.md").read_text()
COORDINATOR_PROMPT_RAW = (PROMPTS / "coordinator.md").read_text()
SAFETY_PROMPT_RAW = (PROMPTS / "safety.md").read_text()
LIFESTYLE_PROMPT_RAW = (PROMPTS / "lifestyle.md").read_text()
LIFESTYLE_ID = "lifestyle"
LIFESTYLE_NAME = "Lifestyle & prevention"
SAFETY_PROMPT = defenses.prompt_text(SAFETY_PROMPT_RAW)  # production version, used by chat
MCP_SERVER = config.REPO_ROOT / "mcp_server" / "server.py"

SPECIALIST_TOOLS = {"search_pubmed", "search_medlineplus"}
PHARMACIST_TOOLS = {"fda_label_search", "search_medlineplus"}
LIFESTYLE_TOOLS = {"search_medlineplus"}
TOOL_CAP = {"specialist": 2, "consult": 2, "pharmacist": 6, "lifestyle": 3}
MAX_PANEL_QUESTIONS = 2   # questions one specialist may put to other panel specialists
AGENT_TIMEOUT_S = 180
MAX_TOKENS = {"specialist": 3500, "pharmacist": 4000, "round2": 2000, "challenge": 3000, "round3": 1500,
              "lifestyle_board": 800, "lifestyle": 3000,
              "consult_decision": 600, "coordinator": 7000, "safety": 3000}
KEY_LAB_WORDS = ("creatinine", "egfr", "gfr", "potassium", "inr", "alt", "ast", "hemoglobin", "platelet",
                 "glucose", "a1c", "sodium", "ck", "creatine kinase", "tsh", "bun", "ferritin")


def member_of(agent: str, label: str) -> str:
    """Which panel member a model call belongs to, for the per-doctor meter and the usage log."""
    if agent.startswith("intake"):
        return "intake"
    if agent in ("chat_router", "chat_wrapup") or label.startswith("coordinator"):
        return "coordinator"
    if agent in ("safety_reviewer", "chat_safety"):
        return "safety_reviewer"
    head = label.split(" (retry")[0]
    if "." in head and head.split(".")[0] in ("r1", "r2", "r3", "r4", "consult", "chat"):
        return head.split(".", 1)[1]
    return agent


def profile(specialty: str) -> str:
    return (PROFILES / f"{specialty}.md").read_text().strip()


# ---- tools: MCP sources with a server-side recorder --------------------------------------

@dataclass
class AgentDeps:
    """Set by the server for each agent run. The model never chooses these values."""
    events: RunEvents
    agent_id: str
    specialty: str
    user_id: str
    case_id: str
    tool_cap: int
    tool_calls: int = 0
    tool_urls: set[str] = field(default_factory=set)
    tool_titles: dict[str, str] = field(default_factory=dict)  # url -> page title, as the tool returned it
    tool_statuses: list[tuple[str, str]] = field(default_factory=list)  # (source, status)


def _as_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("result"), str):
        return raw["result"]
    return json.dumps(raw, default=str)


async def _record_tool_call(ctx: RunContext[AgentDeps], call_tool, name: str, args: dict[str, Any]):
    d = ctx.deps
    audit = d.events.agents[d.agent_id]
    if d.tool_calls >= d.tool_cap:
        msg = f"Tool limit for this agent ({d.tool_cap} calls) reached. Answer with what you have."
        audit.tool_calls.append({"tool": name, "args": args, "status": "refused", "summary": msg})
        d.events.emit("tool_call", agent=d.agent_id, specialty=d.specialty, tool=name, args=args, status="refused", summary=msg)
        return json.dumps({"status": "refused", "message": msg})
    d.tool_calls += 1
    started = time.perf_counter()
    try:
        raw = await call_tool(name, args)
    except Exception as exc:  # the MCP server itself failed: tell the model plainly
        raw = json.dumps({"status": "unreachable", "source": name, "message": f"Tool failed ({type(exc).__name__}). Say so."})
    text = _as_text(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"status": "unknown"}
    status, source = data.get("status", "unknown"), data.get("source", name)
    urls = [r.get("url") for r in data.get("results", []) if r.get("url")] + ([data["url"]] if data.get("url") else [])
    d.tool_urls.update(urls)
    d.tool_titles.update({r["url"]: r.get("title", "") for r in data.get("results", []) if r.get("url")})
    d.tool_statuses.append((source, status))
    titles = [r.get("title", "") for r in data.get("results", [])][:3]
    if data.get("sections"):
        titles = [f"label sections: {', '.join(data['sections'])}"]
    summary = f"{status}: " + ("; ".join(t for t in titles if t) or data.get("message") or data.get("note") or "no results")
    entry = {"tool": name, "args": args, "status": status, "source": source, "summary": summary[:300],
             "urls": urls[:5], "seconds": round(time.perf_counter() - started, 2)}
    audit.tool_calls.append(entry)
    d.events.emit("tool_call", agent=d.agent_id, specialty=d.specialty, tool=name, args=args, status=status,
                  summary=summary[:200])
    return raw


async def open_sources(stack: contextlib.AsyncExitStack, events: RunEvents) -> MCPToolset | None:
    """Start the trusted-sources MCP server inside `stack`. If it cannot start (busy machine,
    missing dependency), the run carries on without it: agents rely on the records and say
    that sources were unavailable, instead of the whole run failing."""
    toolset = sources_toolset()
    try:
        await stack.enter_async_context(toolset)
        return toolset
    except Exception as exc:
        events.emit("error", agent="sources", message="Trusted medical sources (PubMed, MedlinePlus, FDA labels) could not be "
                    f"started ({type(exc).__name__}); continuing without them.")
        return None


def sources_toolset() -> MCPToolset:
    # Least privilege: the MCP server gets no API keys, only what it needs to run.
    keep = ("PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CC_SIMULATE_OUTAGE")
    env = {k: v for k, v in os.environ.items() if k in keep}
    transport = StdioTransport(sys.executable, [str(MCP_SERVER)], env=env, cwd=str(config.REPO_ROOT))
    return MCPToolset(transport, process_tool_call=_record_tool_call, id="sources", tool_error_behavior="failed", init_timeout=30)


# ---- text builders (all built by the server from the case it owns) -----------------------

def questionnaire_text(q: Questionnaire, modes: Modes) -> str:
    p = q.patient
    lines = [
        f"Patient: {p.name}; age {modes.age_years:g}; sex at birth: {p.sex_at_birth or 'not given'}; "
        f"pregnant: {'yes' if modes.pregnancy else 'no'}"
        + (f"; height {p.height_cm:g} cm" if p.height_cm else "") + (f"; weight {p.weight_kg:g} kg" if p.weight_kg else ""),
        f"Completed by: {q.completed_by or 'patient'}",
        f"Main concern: {q.main_concern}",
        "Symptoms:", *[f"- {s.symptom}" + (f" (since {s.since})" if s.since else "") + (f": {s.details}" if s.details else "")
                       for s in q.symptoms],
        "Known conditions: " + (", ".join(q.known_conditions) or "none listed"),
        "Medications (as written by the patient):",
        *[f"- {m.name}" + "".join(f"; {x}" for x in (m.dose, m.how_often) if x)
          + (f"; prescribed by {m.prescribed_by}" if m.prescribed_by else "") + (f"; for {m.reason}" if m.reason else "")
          for m in q.medications],
        "Allergies: " + (", ".join(q.allergies) or "none listed"),
        "Doctors: " + ("; ".join(f"{d.specialty}" + (f" ({d.name})" if d.name else "") for d in q.doctors) or "none listed"),
        "Past history: " + ("; ".join(q.past_history) or "none listed"),
        "Family history: " + ("; ".join(q.family_history) or "none listed"),
        "Lifestyle: " + ("; ".join(f"{k}: {v}" for k, v in q.lifestyle.items()) or "not given"),
        "Patient's questions: " + (" | ".join(q.questions_for_panel) or "none"),
    ]
    if q.gender_identity:
        lines.insert(1, f"Gender identity: {q.gender_identity}")
    if q.pregnancy_status and q.pregnancy_status not in ("neither",):
        lines.insert(1, f"Pregnancy / breastfeeding: {q.pregnancy_status.replace('_', ' ')}")
    if q.withheld:
        lines.append("The patient chose not to share: " + ", ".join(q.withheld)
                     + ". Do not guess these; note where they would matter.")
    return "\n".join(lines)


def mode_text(modes: Modes, q: Questionnaire | None = None) -> str:
    lines = [f"Age group: {modes.age_group} (age {modes.age_years:g}). Coordinator: {modes.coordinator_name}."]
    if q is not None:
        if q.breastfeeding:
            lines.append("BREASTFEEDING: the patient is breastfeeding; medicines and some tests need a lactation check.")
        if q.pregnancy_status == "not_sure":
            lines.append("PREGNANCY STATUS UNKNOWN: the patient is not sure whether she is pregnant. Do not assume either "
                         "way; mention where pregnancy would change the interpretation or a medicine question.")
        if q.patient.sex_at_birth in (None, "prefer not to say"):
            lines.append("SEX AT BIRTH NOT SHARED: where reference ranges differ by sex, say so and give both ranges.")
    if modes.pediatric:
        lines.append(f"PEDIATRIC MODE: the patient is {modes.age_years:g} years old. Use pediatric reference ranges and "
                     "pediatric considerations for every value, not the adult ranges printed on reports.")
    if modes.pregnancy:
        lines.append("PREGNANCY MODE: the patient is pregnant. Account for pregnancy in every interpretation.")
    return "\n".join(lines)


def documents_for(intake: IntakeResult, specialty: str, *, consult: bool = False) -> list[DocumentRecord]:
    """Server-side access control: only the documents routed to this specialty in this case.

    Active specialists get the documents intake assigned to them. A consult gets the
    documents intake tagged with its specialty. Nobody else's documents are ever included.
    """
    if not defenses.current().code:  # code layer off (safety tests only): no scoping, everyone reads everything
        names = {d.filename for d in intake.documents}
    elif consult:
        names = {d.filename for d in intake.documents if d.extraction and specialty in d.extraction.specialties}
    else:
        active = {a.specialty: a for a in intake.active_specialists}
        names = set(active[specialty].documents) if specialty in active else set()
    return [d for d in intake.documents if d.filename in names and d.extraction and not d.error]


def _documents_block(docs: list[DocumentRecord]) -> str:
    if not docs:
        return ("<documents>\n(No documents were routed to you. You were activated by the patient's symptoms: base "
                "findings on the questionnaire only, citing document 'questionnaire'.)\n</documents>")
    parts = []
    for d in docs:
        e = d.extraction
        kind = "RAW IMAGE" if d.raw_image else "written"
        parts.append(defenses.wrap("document", d.text, name=d.filename, kind=kind, type=e.doc_type, date=e.date or "unknown"))
    return ("<documents>\n" + "\n".join(parts) + "\n</documents>") if defenses.current().prompt else "Documents:\n" + "\n\n".join(parts)


def compact_report(r: dict[str, Any], *, with_questions: bool = False) -> str:
    lines = [f"Specialist: {r['name']} (confidence {r['confidence']}"
             + ("; information insufficient" if r.get("insufficient_information") else "") + ")"]
    lines += [f"- {f['id']} [{f['significance']}{', ' + f['region'] if f.get('region') else ''}] {f['statement']} "
              f"(source: {f['document']})" for f in r["findings"]]
    if r["abnormal_values"]:
        lines.append("Abnormal values: " + "; ".join(
            f"{a['test']} {a['value']}{' ' + a['unit'] if a.get('unit') else ''} = {a['interpretation']} ({a['reference_used']})"
            for a in r["abnormal_values"]))
    if r["concerns"]:
        lines.append("Concerns: " + "; ".join(f"[{c['urgency']}] {c['concern']}" for c in r["concerns"]))
    if with_questions and r["questions_for_specialists"]:
        lines.append("Asked: " + "; ".join(f"{q['to_specialty']}: {q['question']}" for q in r["questions_for_specialists"]))
    return "\n".join(lines)


def compact_pharmacist(p: dict[str, Any]) -> str:
    lines = ["Combined medication list: " + "; ".join(
        f"{m['medication']}" + (f" {m['dose_and_schedule']}" if m.get("dose_and_schedule") else "")
        + (f" ({m['prescriber']})" if m.get("prescriber") else "") for m in p["combined_list"])]
    lines += [f"- {i['id']} [{i['kind']}, {i['urgency']}] {', '.join(i['medications'])}: {i['explanation']} "
              f"(discuss with: {', '.join(i['discuss_with'])})" for i in p["issues"]]
    return "\n".join(lines)


# ---- validation of agent outputs ---------------------------------------------------------

def _clean_items(items: list[dict], key: str, dropped: list[dict], who: str) -> list[dict]:
    kept = []
    for it in items:
        bad = safety.violations(it[key])
        if bad:
            dropped.append({"item": it[key][:160], "reason": f"forbidden language: {', '.join(bad)}", "agent": who})
        else:
            kept.append(it)
    return kept


def _limit_questions(specialty: str, questions) -> list[dict]:
    """Keep every question for the coordinator or pharmacist, but at most
    MAX_PANEL_QUESTIONS for other panel specialists (each one costs a round-2 read)."""
    kept, panel = [], 0
    for q in questions:
        if q.to_specialty == specialty:
            continue
        if q.to_specialty in PANEL_IDS:
            if panel >= MAX_PANEL_QUESTIONS:
                continue
            panel += 1
        kept.append(q.model_dump())
    return kept


def validate_specialist(specialty: str, out: SpecialistReportOutput, docs: list[DocumentRecord], q_text: str,
                        deps: AgentDeps) -> tuple[dict[str, Any], dict[str, Any]]:
    texts = {d.filename: d.text for d in docs}
    texts["questionnaire"] = q_text
    raw_images = {d.filename for d in docs if d.raw_image}
    dropped: list[dict] = []
    findings = []
    for f in out.findings:
        item = f.model_dump()
        if f.document not in texts:
            dropped.append({"item": f.statement[:160], "reason": f"cites '{f.document}', which was not routed to this specialist"})
            continue
        if not safety.quote_supported(f.quote, texts[f.document]):
            dropped.append({"item": f.statement[:160], "reason": "quote not found in the cited document", "quote": f.quote[:120]})
            continue
        if f.document in raw_images:
            item["statement"] = "Unverified visual impression, needs a professional read: " + f.statement
            item["significance"] = "unclear"
            item["unverified_visual"] = True
        findings.append(item)
    findings = _clean_items(findings, "statement", dropped, specialty)
    for i, item in enumerate(findings, start=1):
        item["id"] = f"{specialty}.F{i}"
    concerns = _clean_items([c.model_dump() for c in out.concerns], "concern", dropped, specialty)
    abnormal = [a.model_dump() for a in out.abnormal_values if a.document in texts]
    sources = [s.model_dump() for s in out.sources if s.url in deps.tool_urls]
    dropped_sources = [s.url for s in out.sources if s.url not in deps.tool_urls]
    note = out.source_note or ""
    unreachable = sorted({src for src, st in deps.tool_statuses if st == "unreachable"})
    if unreachable:
        auto = f"{' and '.join(unreachable)} could not be reached during this review, so no source from it is cited."
        note = note if re.search(r"unreachable|could not be reached|not reachable", note, re.I) else f"{note} {auto}".strip()
    confidence = out.confidence
    if docs and all(d.filename in raw_images for d in docs):
        confidence = "low"
    report = {
        "specialty": specialty, "name": BY_ID[specialty].name, "documents": [d.filename for d in docs],
        "findings": findings, "abnormal_values": abnormal, "concerns": concerns,
        "questions_for_specialists": _limit_questions(specialty, out.questions_for_specialists),
        "questions_for_doctor": [q for q in out.questions_for_doctor if not safety.violations(q)],
        "sources": sources, "source_note": note or None, "confidence": confidence,
        "insufficient_information": out.insufficient_information, "missing_information": out.missing_information,
    }
    validation = {"findings_kept": len(findings), "dropped": dropped, "sources_dropped": dropped_sources,
                  "tool_calls": deps.tool_calls}
    return report, validation


def validate_pharmacist(out: PharmacistReportOutput, deps: AgentDeps) -> tuple[dict[str, Any], dict[str, Any]]:
    dropped: list[dict] = []
    issues = []
    for issue in out.issues:
        item = issue.model_dump()
        if safety.violations(item["explanation"]):
            dropped.append({"item": item["explanation"][:160], "reason": "forbidden language"})
            continue
        item["source_urls"] = [u for u in issue.source_urls if u in deps.tool_urls]
        issues.append(item)
    for i, item in enumerate(issues, start=1):
        item["id"] = f"pharmacist.I{i}"
    note = out.source_note or ""
    unreachable = sorted({src for src, st in deps.tool_statuses if st == "unreachable"})
    if unreachable:
        auto = f"{' and '.join(unreachable)} could not be reached; label checks rely on general knowledge."
        note = note if re.search(r"unreachable|could not be reached|not reachable", note, re.I) else f"{note} {auto}".strip()
    report = {"specialty": PHARMACIST_ID, "name": "Clinical pharmacist",
              "combined_list": [m.model_dump() for m in out.combined_list], "issues": issues,
              "questions_for_doctor": [q for q in out.questions_for_doctor if not safety.violations(q)],
              "source_note": note or None, "confidence": out.confidence}
    return report, {"issues_kept": len(issues), "dropped": dropped, "tool_calls": deps.tool_calls}


# ---- coordinator output validation and safety -------------------------------------------

def validate_summary(out: CaseSummaryOutput, valid_refs: set[str], *, top: list[dict] | None = None,
                     posts: dict[str, dict] | None = None, names: dict[str, str] | None = None) -> tuple[dict[str, Any], list[dict]]:
    """Never add findings that are not on the board: every point must cite existing post ids.
    Explanation cards are finished in code from the debate (conference.build_cards)."""
    s = out.model_dump()
    dropped: list[dict] = []
    for key, text_key in (("key_findings", "text"), ("medication_discussion", "text"),
                          ("red_flags", "flag"), ("body_regions", "reason")):
        kept = []
        for item in s[key]:
            item["finding_refs"] = [r for r in item["finding_refs"] if r in valid_refs]
            if item["finding_refs"]:
                kept.append(item)
            else:
                dropped.append({"section": key, "item": item[text_key][:160], "reason": "cites no existing finding"})
        s[key] = kept
    cards, card_dropped = conference.build_cards(s.pop("explanations"), top or [], posts or {}, names or {})
    s["explanations"] = cards
    dropped += card_dropped
    card_ids = {c["id"] for c in cards}
    urgency_order = {"urgent": 0, "soon": 1, "routine": 2}
    s["see_first"] = sorted(s["see_first"][:3], key=lambda x: urgency_order.get(x["urgency"], 9))  # urgent first, stable
    for x in s["see_first"]:
        x["related_to"] = [r for r in x["related_to"] if r in card_ids]
    for d in s["questions_for_doctors"]:
        d["related_to"] = [r for r in d.get("related_to", []) if r in card_ids]
    # Consistency: our definition of urgent is "needs care today". A present problem whose
    # instruction says today / same day / immediately is urgent, whatever label the model chose.
    for flag in s["red_flags"]:
        if flag.get("present_now") and flag["urgency"] == "soon" and re.search(
                r"\btoday\b|same[- ]day|right away|immediately|tonight", flag["what_to_do"], re.I):
            flag["urgency"] = "urgent"
            flag["urgency_adjusted"] = "instruction says to act today"
    order = {"watch": 0, "discuss": 1, "urgent": 2}
    merged: dict[str, dict] = {}
    for b in s["body_regions"]:
        cur = merged.get(b["region"])
        if not cur or order[b["severity"]] > order[cur["severity"]]:
            merged[b["region"]] = b
    s["body_regions"] = list(merged.values())
    s.setdefault("self_care", {"steps": [], "care_first": False, "message": None})
    return s, dropped


def flatten_summary(s: dict[str, Any]) -> list[tuple[str, str]]:
    """Every patient-facing sentence as (item id, text), for the safety reviewer and the code pass."""
    items = [("SUMMARY", s["plain_language_summary"])]
    for i, c in enumerate(s.get("explanations", []), 1):
        items.append((f"E{i}.title", c["title"]))
        items += [(f"E{i}.fit{j}", x["text"]) for j, x in enumerate(c["why_it_fits"], 1)]
        items += [(f"E{i}.against{j}", x) for j, x in enumerate(c["argues_against"], 1)]
        items += [(f"E{i}.tell{j}", x) for j, x in enumerate(c["would_help_tell"], 1)]
    items += [(f"SF{i}", x["why"]) for i, x in enumerate(s.get("see_first", []), 1)]
    for i, st in enumerate((s.get("self_care") or {}).get("steps", []), 1):
        items += [(f"SC{i}", st["action"]), (f"SC{i}.why", st["why_it_may_help"]), (f"SC{i}.track", st["how_to_track"])]
    items += [(f"K{i}", x["text"]) for i, x in enumerate(s["key_findings"], 1)]
    items += [(f"M{i}", x["text"]) for i, x in enumerate(s["medication_discussion"], 1)]
    for i, d in enumerate(s["questions_for_doctors"], 1):
        items += [(f"Q{i}.{j}", q) for j, q in enumerate(d["questions"], 1)]
    for i, r in enumerate(s["red_flags"], 1):
        items += [(f"R{i}", r["flag"]), (f"R{i}.do", r["what_to_do"])]
    items += [(f"B{i}", x["reason"]) for i, x in enumerate(s["body_regions"], 1)]
    items += [(f"L{i}", x) for i, x in enumerate(s["limitations"], 1)]
    return items


def apply_edits(s: dict[str, Any], edits: dict[str, str | None]) -> dict[str, Any]:
    """edits: item_id -> new text, or None to remove. Returns a new summary dict.

    Removing a card's title removes the card. A card left with no 'argues against' point is
    not shown (every card must be two-sided). Removing any part of a self-care step removes
    the step."""
    s = json.loads(json.dumps(s))

    def pick(item_id: str, current: str) -> str | None:
        return edits.get(item_id, current) if item_id in edits else current

    s["plain_language_summary"] = pick("SUMMARY", s["plain_language_summary"]) or ""
    cards = []
    for i, c in enumerate(s.get("explanations", []), 1):
        title = pick(f"E{i}.title", c["title"])
        if not title:
            continue
        fits = [{**x, "text": t} for j, x in enumerate(c["why_it_fits"], 1) if (t := pick(f"E{i}.fit{j}", x["text"]))]
        against = [t for j, x in enumerate(c["argues_against"], 1) if (t := pick(f"E{i}.against{j}", x))]
        tell = [t for j, x in enumerate(c["would_help_tell"], 1) if (t := pick(f"E{i}.tell{j}", x))]
        if not fits or not against:
            continue
        cards.append({**c, "title": title, "why_it_fits": fits, "argues_against": against, "would_help_tell": tell})
    if "explanations" in s:
        s["explanations"] = cards
    if "see_first" in s:
        s["see_first"] = [{**x, "why": t} for i, x in enumerate(s["see_first"], 1) if (t := pick(f"SF{i}", x["why"]))]
    if s.get("self_care"):
        steps = []
        for i, st in enumerate(s["self_care"].get("steps", []), 1):
            a, w, t = pick(f"SC{i}", st["action"]), pick(f"SC{i}.why", st["why_it_may_help"]), pick(f"SC{i}.track", st["how_to_track"])
            if a and w and t:
                steps.append({**st, "action": a, "why_it_may_help": w, "how_to_track": t})
        s["self_care"] = {**s["self_care"], "steps": steps}
    for prefix, key, field_ in (("K", "key_findings", "text"), ("M", "medication_discussion", "text"),
                                ("B", "body_regions", "reason")):
        kept = []
        for i, x in enumerate(s[key], 1):
            new = pick(f"{prefix}{i}", x[field_])
            if new:
                x[field_] = new
                kept.append(x)
        s[key] = kept
    docs = []
    for i, d in enumerate(s["questions_for_doctors"], 1):
        qs = [q2 for j, q in enumerate(d["questions"], 1) if (q2 := pick(f"Q{i}.{j}", q))]
        if qs:
            docs.append({**d, "questions": qs})
    s["questions_for_doctors"] = docs
    flags = []
    for i, r in enumerate(s["red_flags"], 1):
        flag, do = pick(f"R{i}", r["flag"]), pick(f"R{i}.do", r["what_to_do"])
        if flag:
            flags.append({**r, "flag": flag, "what_to_do": do or r["what_to_do"]})
    s["red_flags"] = flags
    s["limitations"] = [y for i, x in enumerate(s["limitations"], 1) if (y := pick(f"L{i}", x))]
    return s


def code_safety_pass(s: dict[str, Any], *, medications: list[str] | None = None,
                     self_care_ctx: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict]]:
    """Last line of defense: anything still breaking a rule after the reviewer is blocked.

    Beyond forbidden language everywhere, explanation cards always carry the fixed
    "not a diagnosis" label (restored if missing) and must stay two-sided, and self-care
    steps are re-checked against the lifestyle rules after any rewrite."""
    blocked: list[dict] = []
    edits: dict[str, str | None] = {}
    s = json.loads(json.dumps(s))
    for c in s.get("explanations", []):
        if c.get("label") != conference.NOT_A_DIAGNOSIS:
            blocked.append({"item_id": f"card {c['id']}", "problems": ["missing_label"], "action": "label restored",
                            "original": c.get("label")})
            c["label"] = conference.NOT_A_DIAGNOSIS
    for item_id, text in flatten_summary(s):
        bad = safety.violations(text)
        if re.fullmatch(r"SC\d+", item_id) and self_care_ctx is not None:  # once per step, on all of its text
            st = s["self_care"]["steps"][int(item_id[2:]) - 1]
            bad += lifestyle.text_problems(f"{st['action']} {st['why_it_may_help']} {st['how_to_track']}",
                                           category=st["category"], action=st["action"], ctx=self_care_ctx,
                                           medications=medications or [])
        if not bad:
            continue
        if item_id == "SUMMARY":
            sentences = re.split(r"(?<=[.!?])\s+", text)
            keep = [x for x in sentences if not safety.violations(x)]
            edits[item_id] = " ".join(keep)
            blocked.append({"item_id": item_id, "problems": bad, "action": "removed sentences",
                            "removed": [x for x in sentences if safety.violations(x)]})
        elif item_id.startswith("R") and bad == ["cancer_speculation"]:
            edits[item_id] = "One of your results needs follow-up. Please ask your doctor about it soon."
            blocked.append({"item_id": item_id, "problems": bad, "action": "rewritten calmly", "original": text})
        else:
            edits[item_id] = None
            action = ("removed the card" if re.fullmatch(r"E\d+\.title", item_id)
                      else "removed the step" if item_id.startswith("SC") else "removed")
            blocked.append({"item_id": item_id, "problems": bad, "action": action, "original": text})
    before = {c["id"] for c in s.get("explanations", [])}
    out = apply_edits(s, edits)  # always: it also hides cards left one-sided
    for c in s.get("explanations", []):
        if c["id"] in before - {x["id"] for x in out.get("explanations", [])} and not any(
                b["item_id"].startswith(f"E{s['explanations'].index(c) + 1}.title") for b in blocked):
            blocked.append({"item_id": f"card {c['id']}", "problems": ["one_sided_or_empty"], "action": "card hidden",
                            "original": c["title"]})
    return out, blocked


def _similar(a: str, b: str) -> bool:
    """Rough duplicate check for red flags: share most of their content words."""
    wa, wb = ({w for w in re.findall(r"[a-z]{4,}", x.lower())} for x in (a, b))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.5


# ---- one agent run with audit, timeout and stop reason -----------------------------------

async def _run_logged(events: RunEvents, agent: Agent, prompt: str, *, meter: llm.UsageMeter, agent_id: str,
                      agent_kind: str, specialty: str | None, round_: int | None, inputs: list[str],
                      max_tokens: int, request_limit: int, deps: AgentDeps | None = None, effort: str = "low",
                      attempts: int = 1):
    """Run one agent with a timeout. Transient provider errors (5xx, 429, timeouts) are
    retried up to `attempts` times; a request-limit stop (possible loop) is never retried."""
    events.agent_started(agent_id, agent_kind, specialty, round_, inputs)
    reason = "not started"
    for attempt in range(1, attempts + 1):
        try:
            out = await asyncio.wait_for(llm.run_agent(
                agent, prompt, meter=meter, agent_name=agent_kind if agent_kind != "specialist" else f"specialist_r{round_}",
                label=agent_id if attempt == 1 else f"{agent_id} (retry {attempt - 1})",
                model_settings=llm.settings(max_tokens, effort, f"{events.run_id}-{agent_id}"),
                request_limit=request_limit, deps=deps,
            ), timeout=AGENT_TIMEOUT_S)
            return out, None
        except asyncio.TimeoutError:
            reason, transient = f"timeout after {AGENT_TIMEOUT_S}s", True
        except Exception as exc:
            msg = str(exc)
            if "request_limit" in msg or "UsageLimitExceeded" in msg:
                reason, transient = "request limit reached (possible loop)", False
            else:
                reason = f"error: {msg[:200]}"
                transient = bool(re.search(r"status_code: (5\d\d|429)|timed? ?out|Connection", msg))
        if not transient or attempt == attempts:
            break
        events.emit("error", agent=agent_id, specialty=specialty, message=f"{reason[:120]} - retrying", retrying=True)
        await asyncio.sleep(2 * attempt)
    events.agent_finished(agent_id, "failed", reason)
    events.emit("error", agent=agent_id, specialty=specialty, message=reason)
    return None, reason


# ---- the run -----------------------------------------------------------------------------

async def run_case(
    *, user_id: str, case_id: str, questionnaire: Questionnaire, files: list[tuple[str, bytes]], events: RunEvents,
    use_cache: bool = True, run_budget: float | None = None, on_call: Any = None,
    pass_full_documents: bool = False, round2_mode: str = "targeted", defense_settings: defenses.Defenses | None = None,
) -> dict[str, Any]:
    """Run the whole panel. `on_call(record)` receives every model call (the usage log).

    Experiment switches (defaults are the production design):
      pass_full_documents  hand-offs carry the full documents instead of only summaries
      round2_mode          "targeted" (default) or "all" (everyone reads everyone)
    """
    d_token = defenses.use(defense_settings) if defense_settings else None
    t_token = traps.current_events.set(events)
    try:
        return await _run_case(user_id=user_id, case_id=case_id, questionnaire=questionnaire, files=files, events=events,
                               use_cache=use_cache, run_budget=run_budget, on_call=on_call,
                               pass_full_documents=pass_full_documents, round2_mode=round2_mode)
    finally:
        traps.current_events.reset(t_token)
        if d_token is not None:
            defenses.reset(d_token)


async def _run_case(
    *, user_id: str, case_id: str, questionnaire: Questionnaire, files: list[tuple[str, bytes]], events: RunEvents,
    use_cache: bool, run_budget: float | None, on_call: Any, pass_full_documents: bool, round2_mode: str,
) -> dict[str, Any]:
    meter = llm.UsageMeter(member_of=member_of)
    started = time.perf_counter()
    result: dict[str, Any] = {"run_id": events.run_id, "case_id": case_id, "status": "failed", "stop_reason": None}

    def on_spend(rec: llm.CallRecord) -> None:
        t = meter.totals()
        events.emit("spend", agent=rec.agent, label=rec.label, member=rec.member, from_cache=rec.from_cache,
                    call_usd=round(rec.cost_usd, 6), call={"input": rec.input_tokens, "cached": rec.cached_input_tokens,
                    "cache_write": rec.cache_write_tokens, "output": rec.output_tokens, "seconds": rec.seconds},
                    total_usd=t["cost_usd"], input_tokens=t["input_tokens"], cached_input_tokens=t["cached_input_tokens"],
                    cache_write_tokens=t["cache_write_tokens"], output_tokens=t["output_tokens"],
                    limit_usd=round(budget.limit, 4) if budget else None,
                    remaining_usd=round(max(budget.limit - t["cost_usd"], 0), 6) if budget else None)
        if on_call:
            try:
                on_call(rec)
            except Exception:  # logging must never break a run
                pass

    budget: Budget | None = None
    meter.listeners.append(on_spend)
    try:
        budget = Budget(meter, user_id, **({"run_limit": run_budget} if run_budget else {}))
    except DailyBudgetExceeded as exc:
        events.emit("error", agent="budget", message=str(exc))
        result.update(stop_reason=str(exc))
        events.emit("final", status="failed", stop_reason=str(exc), emergency=None)
        return result

    events.emit("run_started", case_id=case_id, documents=[n for n, _ in files], budget=budget.status(),
                settings={"prompt_cache": llm._prompt_cache_enabled, "pass_full_documents": pass_full_documents, "round2_mode": round2_mode})
    stop_reason = "completed: conference ended after the debate (round 3, hard stop), recommendations reviewed"
    intake: IntakeResult | None = None
    r1: dict[str, dict] = {}
    pharm: dict | None = None
    r2: dict[str, dict] = {}
    board_posts: list[dict] = []
    candidates: list[dict] = []
    debate: dict | None = None
    life: dict[str, Any] = {"posts": [], "steps": [], "dropped": [], "context": None, "source_note": None}
    consult: dict | None = None
    summary: dict | None = None
    safety_info: dict[str, Any] = {}
    emergency: dict[str, Any] = {"active": False, "reasons": [], "actions": [], "crisis": False, "message": None}
    try:
        # ---- intake ----
        events.agent_started("intake", "intake", None, 0, [n for n, _ in files])
        intake = await run_intake(
            case_id, questionnaire, files, use_cache=use_cache, meter=meter,
            on_document=lambda d: events.emit(
                "document_routed", document=d.filename, read_by=d.read_by,
                doc_type=d.extraction.doc_type if d.extraction else None,
                specialties=d.extraction.specialties if d.extraction else [],
                summary=d.extraction.summary if d.extraction else None,
                hidden_text=[f"{h.label} ({h.char_count} chars)" for h in d.hidden_text], error=d.error),
        )
        events.agent_finished("intake", "completed", "completed",
                              f"{len(intake.documents)} documents, {len(intake.active_specialists)} specialists")
        modes = intake.modes
        events.emit("panel_selected", coordinator=modes.coordinator_name, coordinator_id=modes.coordinator,
                    mode=modes.age_group, pregnancy=modes.pregnancy, pharmacist=modes.pharmacist_active,
                    medications=len(intake.medications),
                    active=[{"specialty": a.specialty, "name": a.name, "documents": a.documents, "reason": a.reason}
                            for a in intake.active_specialists],
                    consider=[c.name for c in intake.consider_seeing], conflicts=[c.message for c in intake.conflicts])
        q_text = questionnaire_text(questionnaire, modes)
        m_text = mode_text(modes, questionnaire)

        sources_stack = contextlib.AsyncExitStack()
        toolset = await open_sources(sources_stack, events)
        specialist_tools = [toolset.filtered(lambda ctx, td: td.name in SPECIALIST_TOOLS)] if toolset else []
        pharmacist_tools = [toolset.filtered(lambda ctx, td: td.name in PHARMACIST_TOOLS)] if toolset else []
        lifestyle_tools = [toolset.filtered(lambda ctx, td: td.name in LIFESTYLE_TOOLS)] if toolset else []
        m = llm.model()
        d_set = defenses.current()
        # Design layer: agents that read raw patient text (documents or questionnaire) get no action
        # tools. The trap tools stand in for "real" actions; with the design layer on they exist only
        # for round 2, which reads agent reports only. With it off (tests only), every agent has them.
        raw_reader_traps = [] if d_set.design else [traps.trap_toolset()]
        # Every panel agent's instructions open with the same pattern library, so they share one
        # cached prompt prefix (written once per run, then read at the cached-token price).
        library = patterns.library_block()
        specialist_prompt = library + defenses.prompt_text(SPECIALIST_PROMPT_RAW)
        specialist_agent = Agent(m, deps_type=AgentDeps, instructions=specialist_prompt,
                                 output_type=NativeOutput(SpecialistReportOutput), toolsets=[*specialist_tools, *raw_reader_traps], retries=1)
        # Rounds 2 and 3 read the case board and agent outputs only (no patient text), so with the
        # design layer on they are the only agents that hold the (harmless) trap tools.
        round2_agent = Agent(m, instructions=specialist_prompt, output_type=NativeOutput(ConnectionRoundOutput),
                             toolsets=[traps.trap_toolset()], retries=1)
        round3_agent = Agent(m, instructions=specialist_prompt, output_type=NativeOutput(PanelResponseOutput),
                             toolsets=[traps.trap_toolset()], retries=1)
        pharmacist_agent = Agent(m, deps_type=AgentDeps, instructions=library + defenses.prompt_text(PHARMACIST_PROMPT_RAW),
                                 output_type=NativeOutput(PharmacistReportOutput), toolsets=[*pharmacist_tools, *raw_reader_traps], retries=1)
        # The lifestyle agent reads the questionnaire (patient text), so like every raw reader it
        # holds no action tools; in round 4 it gets MedlinePlus only.
        lifestyle_prompt = library + defenses.prompt_text(LIFESTYLE_PROMPT_RAW)
        lifestyle_board_agent = Agent(m, instructions=lifestyle_prompt, output_type=NativeOutput(LifestyleBoardOutput),
                                      toolsets=[*raw_reader_traps], retries=1)
        lifestyle_steps_agent = Agent(m, deps_type=AgentDeps, instructions=lifestyle_prompt,
                                      output_type=NativeOutput(LifestyleStepsOutput), toolsets=[*lifestyle_tools, *raw_reader_traps],
                                      retries=1)
        doc_text = {a.specialty: "\n".join(d.text for d in documents_for(intake, a.specialty)) for a in intake.active_specialists}
        all_docs_block = "\n\n".join(defenses.wrap("document", d.text, name=d.filename) for d in intake.documents if d.extraction)

        async def run_specialist(spec: str, *, consult_mode: bool = False, extra: str = "") -> None:
            docs = documents_for(intake, spec, consult=consult_mode)
            agent_id = f"{'consult' if consult_mode else 'r1'}.{spec}"
            deps = AgentDeps(events, agent_id, spec, user_id, case_id, TOOL_CAP["consult" if consult_mode else "specialist"])
            events.emit("specialist_started", agent=agent_id, specialty=spec, name=BY_ID[spec].name, round=1,
                        consult=consult_mode, documents=[d.filename for d in docs])
            prompt = "\n\n".join([
                f"<profile>\n{profile(spec)}\n</profile>", f"<mode>\n{m_text}\n</mode>",
                defenses.wrap("questionnaire", q_text), _documents_block(docs), extra,
                "Task: Round 1, your independent review" + (" (you were called in as a consult)" if consult_mode else "")
                + ". Return your report.",
            ])
            out, err = await _run_logged(events, specialist_agent, prompt, meter=meter, agent_id=agent_id,
                                         agent_kind="specialist", specialty=spec, round_=1,
                                         inputs=[d.filename for d in docs] + ["questionnaire"],
                                         max_tokens=MAX_TOKENS["specialist"], request_limit=5, deps=deps,
                                         attempts=2)
            if out is None:
                return
            report, validation = validate_specialist(spec, out, docs, q_text, deps)
            report["consult"] = consult_mode
            events.agent_finished(agent_id, "completed", "completed", f"{len(report['findings'])} findings", validation)
            events.emit("specialist_done", agent=agent_id, specialty=spec, name=BY_ID[spec].name, round=1,
                        findings=len(report["findings"]), concerns=len(report["concerns"]), confidence=report["confidence"],
                        sources=len(report["sources"]), dropped=len(validation["dropped"]),
                        insufficient=report["insufficient_information"],
                        headline=report["findings"][0]["statement"] if report["findings"] else None)
            for post in board.posts_from_report(report):
                events.emit("board_post", **post)
            if consult_mode:
                nonlocal consult
                consult = report
            else:
                r1[spec] = report

        async def run_pharmacist() -> None:
            nonlocal pharm
            agent_id = "r1.clinical_pharmacist"
            deps = AgentDeps(events, agent_id, PHARMACIST_ID, user_id, case_id, TOOL_CAP["pharmacist"])
            events.emit("specialist_started", agent=agent_id, specialty=PHARMACIST_ID, name="Clinical pharmacist", round=1,
                        documents=["medication summary from intake"])
            meds = "\n".join(
                f"- {mm.generic_name}: names {', '.join(mm.names_seen)}; doses {'; '.join(mm.doses) or 'n/a'}; prescribers "
                f"{'; '.join(mm.prescribers) or 'n/a'}; status {'; '.join(mm.statuses)}; seen in {', '.join(mm.sources)}"
                for mm in intake.medications)
            labs = "\n".join(f"- {lab.test} {lab.value} {lab.unit or ''} (range {lab.reference_range or 'n/a'}, flag "
                             f"{lab.flag}, {lab.date or 'date ?'}, {lab.document})" for lab in intake.labs
                             if lab.flag != "none" or any(w in lab.test.lower() for w in KEY_LAB_WORDS))
            conflicts = "\n".join(f"- {c.message}" for c in intake.conflicts if "medication" in c.kind or "avoid" in c.kind)
            prompt = "\n\n".join([
                f"<profile>\n{profile(PHARMACIST_ID)}\n</profile>", f"<mode>\n{m_text}\n</mode>",
                defenses.wrap("questionnaire", q_text),
                all_docs_block if pass_full_documents else defenses.wrap("medications_from_records", meds),
                f"<relevant_labs>\n{labs or '(none)'}\n</relevant_labs>",
                f"<intake_conflicts>\n{conflicts or '(none)'}\n</intake_conflicts>",
                "Task: build the combined list and the issues to discuss.",
            ])
            out, err = await _run_logged(events, pharmacist_agent, prompt, meter=meter, agent_id=agent_id,
                                         agent_kind="pharmacist", specialty=PHARMACIST_ID, round_=1,
                                         inputs=["intake medication summary", "relevant labs", "questionnaire"],
                                         max_tokens=MAX_TOKENS["pharmacist"], request_limit=9, deps=deps,
                                         attempts=2)
            if out is None:
                return
            pharm, validation = validate_pharmacist(out, deps)
            for post in board.posts_from_pharmacist(pharm):
                events.emit("board_post", **post)
            events.agent_finished(agent_id, "completed", "completed", f"{len(pharm['issues'])} issues", validation)
            events.emit("specialist_done", agent=agent_id, specialty=PHARMACIST_ID, name="Clinical pharmacist", round=1,
                        findings=len(pharm["issues"]), confidence=pharm["confidence"], dropped=len(validation["dropped"]),
                        headline=pharm["issues"][0]["explanation"] if pharm["issues"] else None)

        async def run_lifestyle_board() -> None:
            agent_id = "r1.lifestyle"
            events.emit("specialist_started", agent=agent_id, specialty=LIFESTYLE_ID, name=LIFESTYLE_NAME, round=1,
                        documents=["questionnaire"])
            prompt = "\n\n".join([f"<mode>\n{m_text}\n</mode>", defenses.wrap("questionnaire", q_text),
                                   "Task A: lifestyle facts for the case board."])
            out, err = await _run_logged(events, lifestyle_board_agent, prompt, meter=meter, agent_id=agent_id,
                                         agent_kind="lifestyle", specialty=LIFESTYLE_ID, round_=1, inputs=["questionnaire"],
                                         max_tokens=MAX_TOKENS["lifestyle_board"], request_limit=2, effort="none", attempts=2)
            if out is None:
                return
            kept, dropped = lifestyle.validate_posts(out, q_text)
            life["posts"] = lifestyle.as_board_posts(kept)
            events.agent_finished(agent_id, "completed", "completed", f"{len(kept)} lifestyle facts", {"dropped": dropped})
            for post in life["posts"]:
                events.emit("board_post", **post)
            events.emit("specialist_done", agent=agent_id, specialty=LIFESTYLE_ID, name=LIFESTYLE_NAME, round=1,
                        findings=len(kept), headline=kept[0]["line"] if kept else None)

        async def run_lifestyle_steps() -> None:
            agent_id = "r4.lifestyle"
            deps = AgentDeps(events, agent_id, LIFESTYLE_ID, user_id, case_id, TOOL_CAP["lifestyle"])
            events.emit("specialist_started", agent=agent_id, specialty=LIFESTYLE_ID, name=LIFESTYLE_NAME, round=4,
                        documents=["case board", "questionnaire"])
            urgent = [f"- {r['name']} [{c['urgency']}]: {c['concern']}" for r in reports.values() for c in r["concerns"]
                      if c["urgency"] != "routine"]
            ctx = lifestyle.context(board_posts, pediatric=modes.pediatric, pregnancy=modes.pregnancy, urgent_concerns=urgent)
            life["context"] = ctx
            prompt = "\n\n".join([
                board_block, f"<mode>\n{m_text}\n</mode>", lifestyle.context_text(ctx),
                "<concerns_raised>\n" + ("\n".join(urgent) or "(none)") + "\n</concerns_raised>",
                defenses.wrap("questionnaire", q_text),
                "Task B: self-care steps.",
            ])
            out, err = await _run_logged(events, lifestyle_steps_agent, prompt, meter=meter, agent_id=agent_id,
                                         agent_kind="lifestyle", specialty=LIFESTYLE_ID, round_=4,
                                         inputs=["case board", "questionnaire", "context notes"],
                                         max_tokens=MAX_TOKENS["lifestyle"], request_limit=5, deps=deps, attempts=2)
            if out is None:
                return
            meds = ([n for mm in intake.medications for n in [mm.generic_name, *mm.names_seen]]
                    + [qm.name for qm in questionnaire.medications]
                    + [ml["medication"] for ml in (pharm or {}).get("combined_list", [])])
            steps, dropped = lifestyle.validate_steps(out, tool_urls=deps.tool_urls, posts=posts, ctx=ctx, medications=meds,
                                                     tool_titles=deps.tool_titles)
            life.update(steps=steps, dropped=dropped, source_note=out.source_note)
            events.agent_finished(agent_id, "completed", "completed", f"{len(steps)} self-care steps",
                                  {"dropped": dropped, "tool_calls": deps.tool_calls})
            events.emit("specialist_done", agent=agent_id, specialty=LIFESTYLE_ID, name=LIFESTYLE_NAME, round=4,
                        findings=len(steps), dropped=len(dropped))

        async with sources_stack:  # closes the MCP server (if it started) after the conference
            # ---- round 1: independent, in parallel ----
            active = [a.specialty for a in intake.active_specialists]
            if not budget.can_start("round1", len(active) + 1 + (1 if modes.pharmacist_active else 0)):
                stop_reason = "stopped: run budget reached before the panel could start"
            else:
                events.emit("conference_round", round=1, status="started",
                            participants=active + ([PHARMACIST_ID] if modes.pharmacist_active else []))
                await asyncio.gather(*[run_specialist(s) for s in active], run_lifestyle_board(),
                                     *([run_pharmacist()] if modes.pharmacist_active else []))
                events.emit("conference_round", round=1, status="done", reports=len(r1) + (1 if pharm else 0))
            # ---- the shared case board: built in code from validated round-1 outputs ----
            covered = " ".join(f"{a['test']} {f['quote']}" for r in r1.values() for a in r["abnormal_values"]
                               for f in r["findings"]) + " " + " ".join(f["quote"] for r in r1.values() for f in r["findings"])
            intake_posts = board.posts_from_intake_labs(intake.labs, covered, modes.pediatric)
            for post in intake_posts:
                events.emit("board_post", **post)
            board_posts = ([p_ for s_ in active if s_ in r1 for p_ in board.posts_from_report(r1[s_])]
                           + (board.posts_from_pharmacist(pharm) if pharm else []) + life.get("posts", []) + intake_posts)
            events.emit("board_ready", posts=len(board_posts),
                        systems=sorted({p_["system"] for p_ in board_posts}))

            # ---- optional consult: one extra specialist, only within the cap; its findings join the board ----
            candidates_c = sorted(
                ({q["to_specialty"] for r in r1.values() for q in r["questions_for_specialists"]}
                 | {c.specialty for c in intake.consider_seeing}) & set(PANEL_IDS) - set(r1))
            if r1 and candidates_c and len(intake.active_specialists) < MAX_ACTIVE_SPECIALISTS and budget.can_start("consult"):
                events.emit("coordinator_thinking", stage="consult", candidates=candidates_c)
                coordinator_agent_a = Agent(m, instructions=library + defenses.prompt_text(COORDINATOR_PROMPT_RAW), output_type=NativeOutput(ConsultDecisionOutput))
                asked = "\n".join(f"- {r['name']} asked {q['to_specialty']}: {q['question']}" for r in r1.values()
                                  for q in r["questions_for_specialists"] if q["to_specialty"] in candidates_c)
                prompt = "\n\n".join([
                    f"<profile>\n{profile(modes.coordinator)}\n</profile>",
                    board.render(board_posts),
                    f"<questions_to_specialties_not_on_panel>\n{asked or '(none)'}\n</questions_to_specialties_not_on_panel>",
                    "<consider_seeing>\n" + ("\n".join(f"- {c.specialty}: {c.reason}" for c in intake.consider_seeing) or "(none)")
                    + "\n</consider_seeing>",
                    f"Candidates you may choose from: {', '.join(candidates_c)}.",
                    "Task A: consult decision.",
                ])
                decision, err = await _run_logged(events, coordinator_agent_a, prompt, meter=meter, agent_id="coordinator.consult",
                                                  agent_kind="coordinator", specialty=modes.coordinator, round_=None,
                                                  inputs=["case board"], max_tokens=MAX_TOKENS["consult_decision"],
                                                  request_limit=2)
                if decision is not None:
                    chosen = decision.consult if decision.consult in candidates_c else None
                    events.agent_finished("coordinator.consult", "completed", "completed",
                                          f"consult: {chosen or 'none'} ({decision.reason[:120]})")
                    events.emit("coordinator_thinking", stage="consult_decision", consult=chosen, reason=decision.reason)
                    if chosen:
                        qs = "\n".join(f"- from {r['name']}: {q['question']}" for r in r1.values()
                                       for q in r["questions_for_specialists"] if q["to_specialty"] == chosen)
                        extra = (board.render(board_posts) + "\n\n" + f"<questions_for_you>\n{qs or '(none)'}\n</questions_for_you>")
                        await run_specialist(chosen, consult_mode=True, extra=extra)
                        if consult:
                            board_posts = board_posts + board.posts_from_report(consult)

            posts = board.index(board_posts)
            reports = dict(r1, **({consult["specialty"]: consult} if consult else {}))
            own_text = {s_: compact_report(r, with_questions=True) for s_, r in reports.items()}
            if pharm:
                own_text[PHARMACIST_ID] = compact_pharmacist(pharm)
            board_block = board.render(board_posts)

            # ---- round 2: connection round (everyone reads the whole board; no tools) ----
            # Only members with something abnormal or borderline on the board take part.
            talking = [s_ for s_ in own_text if any(p_["by"] == s_ and p_["significance"] in ("abnormal", "borderline")
                                                   for p_ in board_posts)]
            if talking and budget.can_start("round2", len(talking)):
                events.emit("conference_round", round=2, status="started", name="connection round", participants=talking,
                            skipped=[s_ for s_ in own_text if s_ not in talking])

                async def run_connections(spec: str) -> None:
                    agent_id = f"r2.{spec}"
                    name = board.member_name(spec)
                    events.emit("specialist_started", agent=agent_id, specialty=spec, name=name, round=2)
                    qs = "\n".join(f"- from {r['name']}: {q['question']}" for b_, r in reports.items() if b_ != spec
                                   for q in r["questions_for_specialists"] if q["to_specialty"] == spec)
                    peers = ""
                    if round2_mode == "all":  # comparison mode: full peer reports instead of the board alone
                        peers = "\n\n".join(f'<peer specialty="{b_}">\n{t_}' + (f"\n<peer_documents>\n{doc_text.get(b_, '')}\n</peer_documents>"
                                            if pass_full_documents else "") + "\n</peer>" for b_, t_ in own_text.items() if b_ != spec)
                    prompt = "\n\n".join(x for x in [
                        board_block,  # first, identical for every reader: part of the cached prefix
                        f"<profile>\n{profile(spec)}\n</profile>", f"<mode>\n{m_text}\n</mode>",
                        f"<your_round1>\n{own_text[spec]}\n</your_round1>", peers,
                        f"<questions_for_you>\n{qs or '(none)'}\n</questions_for_you>",
                        "Task: Round 2, the connection round. Return your connections.",
                    ] if x)
                    out, err = await _run_logged(events, round2_agent, prompt, meter=meter, agent_id=agent_id,
                                                 agent_kind="specialist", specialty=spec, round_=2, inputs=["case board"],
                                                 max_tokens=MAX_TOKENS["round2"], request_limit=2, attempts=2)
                    if out is None:
                        return
                    cards, dropped = conference.validate_connections(spec, out.connections, posts)
                    answers = [a.model_dump() for a in out.answers if not safety.violations(a.answer)]
                    r2[spec] = {"specialty": spec, "connections": cards, "answers": answers}
                    events.agent_finished(agent_id, "completed", "completed", f"{len(cards)} connections",
                                          {"connections_kept": len(cards), "dropped": dropped})
                    for c_ in cards:
                        events.emit("connection", round=2, from_=spec, title=c_["title"], refs=c_["refs"],
                                    members=sorted({posts[r_]["by"] for r_ in c_["refs"]} - {spec}),
                                    pattern_id=c_["pattern_id"])
                    for a_ in answers:
                        events.emit("comment", round=2, from_=spec, to=a_["from_specialty"], kind="answer", text=a_["answer"])
                    events.emit("specialist_done", agent=agent_id, specialty=spec, name=name, round=2,
                                connections=len(cards), disagreements=0)

                await asyncio.gather(*[run_connections(s_) for s_ in talking])
                candidates = conference.merge_candidates([c_ for s_ in talking for c_ in (r2.get(s_) or {}).get("connections", [])], posts)
                events.emit("conference_round", round=2, status="done", connections=sum(len(d["connections"]) for d in r2.values()),
                            candidates=[{"id": c_["id"], "title": c_["title"], "refs": c_["refs"], "proposers": c_["proposers"]}
                                        for c_ in candidates])
            elif talking:
                stop_reason = "stopped: run budget reached before the connection round; summary built from the board"

            async def run_debate() -> None:
                nonlocal debate, stop_reason
                # round 3: debate (the coordinator challenges, the involved members answer) ----
                # The coordinator leads the conference, so it is also the challenger. It reads agent
                # outputs only (no patient text), so like rounds 2-3 it holds the harmless trap tools.
                chair = modes.coordinator
                if candidates and budget.can_start("challenge"):
                    events.emit("conference_round", round=3, status="started", name="debate", candidates=len(candidates),
                                challenger=chair)
                    challenge_agent = Agent(m, instructions=library + defenses.prompt_text(COORDINATOR_PROMPT_RAW),
                                            output_type=NativeOutput(ChallengeOutput), toolsets=[traps.trap_toolset()], retries=1)
                    prompt = "\n\n".join([
                        board_block, f"<profile>\n{profile(chair)}\n</profile>", f"<mode>\n{m_text}\n</mode>",
                        conference.render_candidates(candidates),
                        f"<pharmacist>\n{compact_pharmacist(pharm) if pharm else '(no medication review)'}\n</pharmacist>",
                        "Task C: challenge every candidate.",
                    ])
                    sk, err = await _run_logged(events, challenge_agent, prompt, meter=meter, agent_id="coordinator.challenge",
                                                agent_kind="coordinator", specialty=chair, round_=3, inputs=["case board", "candidates"],
                                                max_tokens=MAX_TOKENS["challenge"], request_limit=2, attempts=2)
                    challenges: dict[str, dict] = {}
                    if sk is not None:
                        challenges, alternative, sk_dropped = conference.validate_challenge(sk, candidates, posts, chair)
                        if alternative and len(candidates) < conference.MAX_CANDIDATES + 1:
                            alt = conference.merge_candidates([alternative], posts)[0]
                            alt["id"] = f"C{len(candidates) + 1}"
                            candidates.append(alt)
                            challenges[alt["id"]] = {"verdict": "keep", "reason": "Proposed by the coordinator as a simpler or overlooked link.",
                                                     "simpler_explanations": [], "unsupported_refs": [], "missing": []}
                        events.agent_finished("coordinator.challenge", "completed", "completed",
                                              ", ".join(f"{k}: {v['verdict']}" for k, v in challenges.items()) or "no challenges",
                                              {"dropped": sk_dropped})
                        for c_ in candidates:
                            ch = challenges.get(c_["id"])
                            if ch and c_["proposers"] != [chair]:
                                events.emit("challenge", round=3, from_=chair, candidate=c_["id"], verdict=ch["verdict"],
                                            to=sorted(set(c_["proposers"]) | set(c_["posters"])), text=ch["reason"])
                        if alternative:
                            events.emit("connection", round=3, from_=chair, title=candidates[-1]["title"], refs=candidates[-1]["refs"],
                                        members=candidates[-1]["posters"], pattern_id=candidates[-1]["pattern_id"])
                    involved = [s_ for s_ in own_text if any(s_ in c_["proposers"] or s_ in c_["posters"] for c_ in candidates)]
                    stances: list[dict] = []
                    if involved and budget.can_start("round3", len(involved)):
                        cand_block = conference.render_candidates(candidates, challenges)

                        async def run_response(spec: str) -> None:
                            agent_id = f"r3.{spec}"
                            name = board.member_name(spec)
                            events.emit("specialist_started", agent=agent_id, specialty=spec, name=name, round=3)
                            mine = [c_["id"] for c_ in candidates if spec in c_["proposers"]]
                            prompt = "\n\n".join([
                                board_block, cand_block,
                                f"<profile>\n{profile(spec)}\n</profile>", f"<mode>\n{m_text}\n</mode>",
                                f"<your_round1>\n{own_text[spec]}\n</your_round1>",
                                f"You proposed: {', '.join(mine) or 'none'}.",
                                "Task: Round 3, the debate. Return your stances.",
                            ])
                            out, err = await _run_logged(events, round3_agent, prompt, meter=meter, agent_id=agent_id,
                                                         agent_kind="specialist", specialty=spec, round_=3,
                                                         inputs=["case board", "candidates with the coordinator's challenges"],
                                                         max_tokens=MAX_TOKENS["round3"], request_limit=2, attempts=2)
                            if out is None:
                                return
                            mine_st = conference.validate_stances(spec, out.stances, candidates, posts)
                            stances.extend(mine_st)
                            events.agent_finished(agent_id, "completed", "completed",
                                                  ", ".join(f"{x['candidate']}: {x['stance']}" for x in mine_st) or "no stances")
                            cand_by = {c_["id"]: c_ for c_ in candidates}
                            for x in mine_st:
                                c_ = cand_by[x["candidate"]]
                                events.emit("stance", round=3, from_=spec, candidate=x["candidate"], stance=x["stance"],
                                            to=sorted((set(c_["proposers"]) | set(c_["posters"])) - {spec}), text=x["reason"])
                            events.emit("specialist_done", agent=agent_id, specialty=spec, name=name, round=3, stances=len(mine_st))

                        await asyncio.gather(*[run_response(s_) for s_ in involved])
                    scored = conference.score_candidates(candidates, challenges, stances)
                    debate = {"candidates": scored, "stances": stances}
                    events.emit("conference_round", round=3, status="done", note="hard stop: the conference ends after the debate",
                                scored=[{"id": c_["id"], "title": c_["title"], "score": c_["score"], "strength": c_["strength"],
                                         "removed": c_["removed"]} for c_ in scored])
                elif candidates:
                    stop_reason = "stopped: run budget reached before the debate; summary built from the connection round"

            # ---- round 3 (debate) and round 4's self-care steps run in parallel ----
            jobs = [run_debate()]
            if r1 and budget.can_start("lifestyle"):
                jobs.append(run_lifestyle_steps())
            await asyncio.gather(*jobs)

        # ---- round 4: recommendations (the coordinator writes the summary from the debate) ----
        if r1 and budget.can_start("coordinator"):
            events.emit("conference_round", round=4, status="started", name="recommendations")
            events.emit("coordinator_thinking", stage="synthesis", specialists=len(r1) + (1 if consult else 0))
            all_reports = dict(r1, **({consult["specialty"]: consult} if consult else {}))
            valid_refs = set(posts)
            scored = (debate or {}).get("candidates", [])
            top = conference.top_candidates(scored)
            removed = [c for c in scored if c["removed"]]
            answers = "\n".join(f"- {s_} answers {x['from_specialty']}: {x['answer']}" for s_, d in r2.items() for x in d["answers"])
            docs_text = "\n".join(f"- {d.filename}: {d.extraction.summary}" for d in intake.documents if d.extraction)
            failed_reviews = [f"- The {BY_ID[a.specialty].name} review failed and is missing from this summary; list it under limitations."
                              for a in events.agents.values() if a.status == "failed" and a.specialty in BY_ID]
            signals = "\n".join(intake.safety_signals + failed_reviews
                                 + [f"- To confirm with the patient: {c.message}" for c in intake.conflicts])
            prompt = "\n\n".join([
                board_block,
                f"<profile>\n{profile(modes.coordinator)}\n</profile>", f"<mode>\n{m_text}\n</mode>",
                defenses.wrap("questionnaire", q_text),
                all_docs_block if pass_full_documents else f"<document_summaries>\n{docs_text}\n</document_summaries>",
                conference.render_top(top, removed),
                "<specialist_concerns_and_questions>\n" + "\n\n".join(
                    f"{r['name']} (confidence {r['confidence']})"
                    + "".join(f"\n- concern [{c['urgency']}]: {c['concern']}" for c in r["concerns"])
                    + ("\n- questions for their doctor: " + " | ".join(r["questions_for_doctor"]) if r["questions_for_doctor"] else "")
                    + (f"\n- source note: {r['source_note']}" if r.get("source_note") else "") for r in all_reports.values())
                + "\n</specialist_concerns_and_questions>",
                f"<pharmacist>\n{compact_pharmacist(pharm) if pharm else '(no medication review)'}\n</pharmacist>",
                f"<answers_between_specialists>\n{answers or '(none)'}\n</answers_between_specialists>",
                "<consider_seeing>\n" + ("\n".join(f"- {c.name}: {c.reason}" for c in intake.consider_seeing) or "(none)")
                + "\n</consider_seeing>",
                f"<safety_signals>\n{signals or '(none)'}\n</safety_signals>",
                "Task B: recommendations and the case summary.",
            ])
            coordinator_agent = Agent(m, instructions=library + defenses.prompt_text(COORDINATOR_PROMPT_RAW), output_type=NativeOutput(CaseSummaryOutput),
                                      toolsets=[] if defenses.current().design else [traps.trap_toolset()], retries=1)
            out, err = await _run_logged(events, coordinator_agent, prompt, meter=meter, agent_id="coordinator.synthesis",
                                         agent_kind="coordinator", specialty=modes.coordinator, round_=4,
                                         inputs=["case board", "top candidates and the debate", "pharmacist", "document summaries"],
                                         max_tokens=MAX_TOKENS["coordinator"], request_limit=2, attempts=3)
            if out is not None:
                names = {m_: board.member_name(m_) for m_ in {p_["by"] for p_ in board_posts} | {x for c in top for x in c["proposers"]}}
                summary, dropped = validate_summary(out, valid_refs, top=top, posts=posts, names=names)
                summary["self_care"] = {"steps": life.get("steps", []), "source_note": life.get("source_note"),
                                        "limits": (life.get("context") or {}).get("reasons", []), "care_first": False, "message": None}
                # Calm red flag for any document intake marked as mentioning a possible malignancy.
                for d in intake.documents:
                    if d.extraction and d.extraction.mentions_possible_malignancy:
                        doc_refs = {f["id"] for r in all_reports.values() for f in r["findings"] if f["document"] == d.filename}
                        if not any(set(rf["finding_refs"]) & doc_refs for rf in summary["red_flags"]):
                            summary["red_flags"].append({"flag": safety.MALIGNANCY_FLAG.format(file=d.filename), "urgency": "soon", "present_now": True,
                                                         "what_to_do": "Ask your doctor about this result at your next contact, soon.",
                                                         "finding_refs": sorted(doc_refs), "added_by": "safety_rule"})
                events.agent_finished("coordinator.synthesis", "completed", "completed",
                                      f"{len(summary['explanations'])} explanation cards, {len(summary['see_first'])} to see first",
                                      {"dropped": dropped})
                events.emit("explanations", cards=[{"id": c["id"], "title": c["title"], "strength": c["strength"], "refs": c["refs"],
                                                     "regions": c["regions"], "specialists": [x["id"] for x in c["specialists"]]}
                                                    for c in summary["explanations"]])
                events.emit("conference_round", round=4, status="done")
            else:
                stop_reason = f"stopped: the coordinator failed ({err}); returning the specialist reports"
        elif r1:
            stop_reason = "stopped: run budget reached before the coordinator; returning specialist reports"

        # ---- safety review: model, then code ----
        summary_before_safety = json.loads(json.dumps(summary)) if summary is not None else None
        if summary is not None:
            events.emit("safety_check", stage="started", items=len(flatten_summary(summary)))
            all_reports = dict(r1, **({consult["specialty"]: consult} if consult else {}))
            concerns = [f"- {r['name']} [{c['urgency']}]: {c['concern']}" for r in all_reports.values() for c in r["concerns"]
                        if c["urgency"] != "routine"]
            concerns += [f"- pharmacist {i['id']} [{i['urgency']}]: {i['explanation']}" for i in (pharm or {}).get("issues", [])
                         if i["urgency"] != "routine"]
            crisis = safety.crisis_mentions(q_text + "\n" + "\n".join(d.text for d in intake.documents))
            crisis += [f"{d.filename}: intake marked a self-harm mention" for d in intake.documents
                       if d.extraction and d.extraction.mentions_self_harm]
            edits_applied: list[dict] = []
            missed: list[dict] = []
            reviewer_emergency: tuple[bool, str | None] = (False, None)
            if budget.can_start("safety"):
                items = "\n".join(f"{i}: {t}" for i, t in flatten_summary(summary))
                prompt = "\n\n".join([
                    f"<summary_items>\n{items}\n</summary_items>",
                    "<specialist_concerns>\n" + ("\n".join(concerns) or "(none)") + "\n</specialist_concerns>",
                    "<intake_signals>\n" + ("\n".join(intake.safety_signals + crisis) or "(none)") + "\n</intake_signals>",
                    "Review the summary items.",
                ])
                safety_agent = Agent(m, instructions=defenses.prompt_text(SAFETY_PROMPT_RAW), output_type=NativeOutput(SafetyReviewOutput), retries=1)
                review, err = await _run_logged(events, safety_agent, prompt, meter=meter, agent_id="safety_reviewer",
                                                agent_kind="safety_reviewer", specialty=None, round_=None,
                                                inputs=["summary items", "urgent concerns", "intake signals"],
                                                max_tokens=MAX_TOKENS["safety"], request_limit=2, attempts=3)
                if review is not None:
                    valid_ids = {i for i, _ in flatten_summary(summary)}
                    edits = {e.item_id: (e.new_text if e.action == "rewrite" else None) for e in review.edits if e.item_id in valid_ids}
                    edits_applied = [e.model_dump() for e in review.edits if e.item_id in valid_ids]
                    summary = apply_edits(summary, edits)
                    for mf in review.missed_red_flags:
                        if any(_similar(mf.flag, r["flag"]) for r in summary["red_flags"]):
                            continue  # repeats an existing red flag
                        summary["red_flags"].append({"flag": mf.flag, "urgency": mf.urgency, "present_now": mf.present_now, "what_to_do": mf.what_to_do,
                                                     "finding_refs": [], "added_by": "safety_reviewer", "basis": mf.basis})
                        missed.append(mf.model_dump())
                    reviewer_emergency = (review.emergency, review.emergency_reason)
                    events.agent_finished("safety_reviewer", "completed", "completed",
                                          f"{len(edits_applied)} edits, {len(missed)} missed red flags added")
                    events.emit("safety_check", stage="model", edits=len(edits_applied), missed_red_flags=len(missed),
                                emergency=review.emergency, details=[f"{e['item_id']}: {e['problem']} -> {e['action']}" for e in edits_applied])
                else:
                    stop_reason = f"completed with code-only safety check (the safety reviewer failed: {err})"
            else:
                stop_reason = "completed with code-only safety check (run budget reached before the safety reviewer)"
            meds_all = ([n for mm in intake.medications for n in [mm.generic_name, *mm.names_seen]]
                        + [qm.name for qm in questionnaire.medications]
                        + [ml["medication"] for ml in (pharm or {}).get("combined_list", [])])
            summary, blocked = code_safety_pass(summary, medications=meds_all, self_care_ctx=life.get("context") or {})
            events.emit("safety_check", stage="code", blocked=len(blocked),
                        details=[f"{b['item_id']}: {', '.join(b['problems'])} -> {b['action']}" for b in blocked])
            # Only problems present now raise the banner; "if X happens" advice is shown as a safety net.
            urgent = [r for r in summary["red_flags"] if r["urgency"] == "urgent" and r.get("present_now", True)]
            urgent_flags = [r["flag"] for r in urgent]
            emergency = {
                "active": bool(crisis or reviewer_emergency[0] or urgent_flags),
                "crisis": bool(crisis),
                "reasons": ([reviewer_emergency[1]] if reviewer_emergency[0] and reviewer_emergency[1] else []) + urgent_flags
                           + (["Possible mention of self-harm or suicidal thoughts."] if crisis else []),
                "actions": [r["what_to_do"] for r in urgent],
                "message": safety.CRISIS_RESOURCES if crisis else (safety.EMERGENCY_GENERAL if (reviewer_emergency[0] or urgent_flags) else None),
            }
            # Care first: an urgent problem present now hides every self-care step.
            summary["self_care"] = lifestyle.apply_care_first(summary.get("self_care") or {"steps": []},
                                                              bool(urgent_flags or crisis or reviewer_emergency[0]))
            safety_info = {"model_edits": edits_applied, "missed_red_flags_added": missed, "code_blocked": blocked,
                           "crisis_mentions": crisis}
            events.emit("safety_check", stage="done", emergency=emergency["active"], crisis=emergency["crisis"])
        failed = [a.agent_id for a in events.agents.values() if a.status == "failed"]
        if failed and stop_reason.startswith("completed"):
            stop_reason += f"; {len(failed)} agent(s) failed after retries: {', '.join(failed)}"
        status = ("complete" if summary is not None and stop_reason.startswith("completed") and not failed
                  else ("partial" if r1 or summary else "failed"))
    except Exception as exc:
        events.emit("error", agent="run", message=f"{type(exc).__name__}: {str(exc)[:300]}")
        stop_reason = f"error: {type(exc).__name__}: {str(exc)[:200]}"
        status = "partial" if r1 else "failed"
    finally:
        if budget:
            budget.close()

    result.update({
        "status": status, "stop_reason": stop_reason,
        "seconds": round(time.perf_counter() - started, 1),
        "modes": intake.modes.model_dump() if intake else None,
        "emergency": emergency,
        "summary": summary,
        "summary_before_safety": locals().get("summary_before_safety"),
        "trap_calls": traps.calls_for_run(events.run_id),
        "defenses": {"tag": defenses.current().tag, "label": defenses.current().label},
        "specialists": r1, "pharmacist": pharm, "round2": r2, "consult": consult, "board": board_posts,
        "candidates": candidates, "debate": debate, "lifestyle": life,
        "safety": safety_info,
        "intake": intake.model_dump(exclude={"usage"}) if intake else None,
        "usage": meter.as_dict(), "budget": budget.status() if budget else None,
    })
    events.emit("final", status=status, stop_reason=stop_reason, emergency=emergency["active"],
                total_usd=meter.totals()["cost_usd"], seconds=result["seconds"])
    return result


def new_run(user_id: str, case_id: str) -> RunEvents:
    return RunEvents(run_id=f"run-{uuid.uuid4().hex[:10]}", user_id=user_id, case_id=case_id)
