"""Offline tests for the panel's code-level guarantees (no model calls, no key needed).

    .venv/bin/python tests/test_panel_rules.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import budget as budget_mod, safety  # noqa: E402
from backend.events import RunEvents  # noqa: E402
from backend.llm import CallRecord, UsageMeter  # noqa: E402
from backend.panel import (  # noqa: E402
    AgentDeps, code_safety_pass, documents_for, validate_specialist, validate_summary,
)
from backend.schemas import (  # noqa: E402
    ActiveSpecialist, CaseSummaryOutput, DocumentExtractionOutput, DocumentRecord, IntakeResult, Modes,
    SpecialistReportOutput,
)


def doc(name: str, text: str, specialties: list[str], raw_image: bool = False) -> DocumentRecord:
    e = DocumentExtractionOutput(doc_type="lab_report", date=None, source="x", specialties=specialties, summary="s",
                                 patient_name_on_document=None, patient_dob_on_document=None, patient_sex_on_document=None,
                                 labs=[], medications=[], mentions_possible_malignancy=False, mentions_self_harm=False,
                                 instructions_to_ai=[])
    return DocumentRecord(filename=name, sha256="0", kind="text", read_by="text", page_count=1, text=text,
                          hidden_text=[], notes=[], extraction=e, raw_image=raw_image)


def intake_with(docs: list[DocumentRecord], active: dict[str, list[str]]) -> IntakeResult:
    modes = Modes(age_years=42, age_group="adult", pediatric=False, pregnancy=False, coordinator="internal_medicine",
                  coordinator_name="Internal medicine", pharmacist_active=False)
    return IntakeResult(case_label="t", modes=modes, documents=docs, consider_seeing=[], unassigned_documents=[],
                        conflicts=[], medications=[], labs=[], safety_signals=[], usage={},
                        active_specialists=[ActiveSpecialist(specialty=s, name=s, relevance=3, documents=d, symptoms=[],
                                                             reason="r", why_active="documents") for s, d in active.items()])


def deps(urls: set[str] | None = None, statuses: list | None = None) -> AgentDeps:
    d = AgentDeps(RunEvents("r", "u", "c"), "r1.x", "cardiology", "u", "c", 2)
    d.tool_urls = urls or set()
    d.tool_statuses = statuses or []
    return d


def report(findings: list[dict], sources: list[dict] | None = None) -> SpecialistReportOutput:
    return SpecialistReportOutput.model_validate({
        "findings": findings, "abnormal_values": [], "concerns": [], "questions_for_specialists": [],
        "questions_for_doctor": [], "sources": sources or [], "source_note": None, "confidence": "high",
        "insufficient_information": False, "missing_information": []})


def finding(document: str, quote: str, statement: str = "The heart rate was fast.", region: str | None = "heart") -> dict:
    return {"statement": statement, "document": document, "quote": quote, "significance": "abnormal", "region": region,
            "board_line": statement, "system": "cardiovascular", "symptoms": ["palpitations"]}


def test_specialists_only_get_documents_routed_to_them():
    docs = [doc("ecg.txt", "Sinus tachycardia 104 bpm", ["cardiology"]), doc("iron.pdf", "Ferritin 6 L", ["hematology"]),
            doc("egd.pdf", "gastric ulcer", ["gastroenterology", "hematology"])]
    intake = intake_with(docs, {"cardiology": ["ecg.txt"], "hematology": ["iron.pdf", "egd.pdf"]})
    assert [d.filename for d in documents_for(intake, "cardiology")] == ["ecg.txt"]
    assert [d.filename for d in documents_for(intake, "hematology")] == ["iron.pdf", "egd.pdf"]
    assert documents_for(intake, "neurology") == []  # not active: nothing
    assert [d.filename for d in documents_for(intake, "gastroenterology", consult=True)] == ["egd.pdf"]


def test_findings_need_a_real_quote_from_an_allowed_document():
    docs = [doc("ecg.txt", "Ventricular rate     104 bpm\nInterpretation: Sinus tachycardia.", ["cardiology"])]
    out = report([
        finding("ecg.txt", "Ventricular rate 104 bpm"),              # spacing differs: kept
        finding("ecg.txt", "Ventricular rate 140 bpm"),              # wrong number: dropped
        finding("iron.pdf", "Ferritin 6"),                           # not routed to this specialist: dropped
        finding("questionnaire", "heart races when I climb stairs"),  # from the questionnaire: kept
        finding("ecg.txt", "Sinus tachycardia", statement="You have heart disease."),  # forbidden language: dropped
    ])
    rep, val = validate_specialist("cardiology", out, docs, "Main concern: my heart races when I climb stairs.", deps())
    assert [f["id"] for f in rep["findings"]] == ["cardiology.F1", "cardiology.F2"]
    assert [f["document"] for f in rep["findings"]] == ["ecg.txt", "questionnaire"]
    assert len(val["dropped"]) == 3


def test_sources_must_come_from_tool_results_and_outages_are_reported():
    docs = [doc("ecg.txt", "Sinus tachycardia", ["cardiology"])]
    out = report([finding("ecg.txt", "Sinus tachycardia")], sources=[
        {"title": "real", "url": "https://medlineplus.gov/anemia.html", "used_for": "x"},
        {"title": "invented", "url": "https://pubmed.ncbi.nlm.nih.gov/99999999/", "used_for": "x"}])
    rep, val = validate_specialist("cardiology", out, docs, "", deps({"https://medlineplus.gov/anemia.html"},
                                                                       [("PubMed", "unreachable")]))
    assert [s["title"] for s in rep["sources"]] == ["real"]
    assert val["sources_dropped"] == ["https://pubmed.ncbi.nlm.nih.gov/99999999/"]
    assert "PubMed could not be reached" in rep["source_note"]


def test_raw_images_only_give_unverified_impressions():
    docs = [doc("strip.jpg", "[RAW IMAGE, no written report. Neutral description: ECG strip]", ["cardiology"], raw_image=True)]
    out = report([finding("strip.jpg", "ECG strip", statement="The rhythm looks regular.")])
    rep, _ = validate_specialist("cardiology", out, docs, "", deps())
    f = rep["findings"][0]
    assert f["statement"].startswith("Unverified visual impression, needs a professional read")
    assert f["significance"] == "unclear" and rep["confidence"] == "low"


def test_panel_questions_are_limited():
    from backend.panel import _limit_questions
    from backend.schemas import QuestionForSpecialist
    qs = [QuestionForSpecialist(to_specialty=t, question="q") for t in
          ("cardiology", "nephrology", "urology", "internal_medicine", "clinical_pharmacist", "hematology")]
    kept = [q["to_specialty"] for q in _limit_questions("hematology", qs)]
    assert kept == ["cardiology", "nephrology", "internal_medicine", "clinical_pharmacist"]


def test_summary_points_must_cite_existing_findings():
    out = CaseSummaryOutput.model_validate({
        "plain_language_summary": "s", "questions_for_doctors": [], "explanations": [], "see_first": [], "limitations": [],
        "key_findings": [{"text": "real", "finding_refs": ["hematology.F1"]}, {"text": "invented", "finding_refs": ["neurology.F9"]}],
        "medication_discussion": [{"text": "no refs", "finding_refs": []}],
        "red_flags": [], "body_regions": [{"region": "blood", "severity": "watch", "reason": "a", "finding_refs": ["hematology.F1"]},
                                          {"region": "blood", "severity": "discuss", "reason": "b", "finding_refs": ["hematology.F1"]}]})
    s, dropped = validate_summary(out, {"hematology.F1"})
    assert [k["text"] for k in s["key_findings"]] == ["real"] and s["medication_discussion"] == []
    assert len(dropped) == 2
    assert s["body_regions"] == [{"region": "blood", "severity": "discuss", "reason": "b", "finding_refs": ["hematology.F1"]}]


def test_present_flags_that_say_today_are_urgent():
    out = CaseSummaryOutput.model_validate({
        "plain_language_summary": "s", "key_findings": [], "explanations": [], "see_first": [], "medication_discussion": [],
        "questions_for_doctors": [], "body_regions": [], "limitations": [],
        "red_flags": [{"flag": "INR above goal with bruising", "urgency": "soon", "present_now": True, "what_to_do": "Call the clinic today.", "finding_refs": ["x.F1"]},
                      {"flag": "If bleeding starts", "urgency": "soon", "present_now": False, "what_to_do": "Seek care today if it happens.", "finding_refs": ["x.F1"]},
                      {"flag": "Kidney results", "urgency": "soon", "present_now": True, "what_to_do": "Ask at your next visit.", "finding_refs": ["x.F1"]}]})
    s, _ = validate_summary(out, {"x.F1"})
    assert [f["urgency"] for f in s["red_flags"]] == ["urgent", "soon", "soon"]


def test_code_safety_pass_blocks_what_slips_through():
    s = {"plain_language_summary": "Your iron is low. You have iron deficiency anemia. Ask about the colonoscopy.",
         "key_findings": [{"text": "You should stop taking ibuprofen.", "finding_refs": ["x"]},
                          {"text": "Low ferritin.", "finding_refs": ["x"]}],
         "medication_discussion": [], "questions_for_doctors": [{"doctor": "GI", "questions": ["Is it cancer?"], "related_to": []}],
         "explanations": [], "see_first": [], "body_regions": [], "limitations": [],
         "red_flags": [{"flag": "The ulcer biopsy may show a malignancy.", "urgency": "soon", "what_to_do": "Ask.", "finding_refs": ["x"]}]}
    out, blocked = code_safety_pass(s)
    assert out["plain_language_summary"] == "Your iron is low. Ask about the colonoscopy."
    assert [k["text"] for k in out["key_findings"]] == ["Low ferritin."]
    assert out["questions_for_doctors"] == []
    assert "malignan" not in out["red_flags"][0]["flag"].lower() and out["red_flags"][0]["urgency"] == "soon"
    assert len(blocked) == 4


def test_forbidden_language_respects_negation():
    safe = ["They don\u2019t establish a diagnosis of kidney failure.", "Don't change the medication based on this chat.",
            "I can't tell you to stop taking a medicine.", "The records do not confirm that he has heart failure."]
    unsafe = ["You should stop taking naproxen.", "Do not take aspirin with warfarin.", "This confirms lupus.",
              "You have kidney disease.", "Increase your dose to 20 mg."]
    assert [safety.violations(x) for x in safe] == [[], [], [], []]
    assert all(safety.violations(x) for x in unsafe)


def test_runs_continue_if_the_sources_server_cannot_start():
    import asyncio
    import contextlib
    from backend import panel
    original = panel.MCP_SERVER
    panel.MCP_SERVER = ROOT / "mcp_server" / "does_not_exist.py"
    events = RunEvents("r", "u", "c")

    async def go():
        stack = contextlib.AsyncExitStack()
        toolset = await panel.open_sources(stack, events)
        async with stack:
            return toolset
    try:
        assert asyncio.run(go()) is None
    finally:
        panel.MCP_SERVER = original
    assert events.events[-1]["type"] == "error" and "continuing without them" in events.events[-1]["message"]


def test_global_daily_budget_protects_a_public_deployment():
    with tempfile.TemporaryDirectory() as tmp:
        budget_mod.LEDGER_DIR = Path(tmp)
        budget_mod.add_spend(budget_mod.GLOBAL, 2.99)
        b = budget_mod.Budget(UsageMeter(), "new-user", run_limit=0.05, daily_limit=0.50, global_limit=3.00)
        assert abs(b.limit - 0.01) < 1e-9          # only what is left for everyone today
        budget_mod.add_spend(budget_mod.GLOBAL, 0.02)
        try:
            budget_mod.Budget(UsageMeter(), "another-new-user", global_limit=3.00)
        except budget_mod.DailyBudgetExceeded as exc:
            assert "overall" in str(exc)
        else:
            raise AssertionError("the global cap should block new runs")


def test_crisis_detection_respects_negation():
    assert safety.crisis_mentions("Lately I have had thoughts of suicide.")
    assert safety.crisis_mentions("I want to die some days")
    assert not safety.crisis_mentions("Denies suicidal ideation. Mood stable.")
    assert not safety.crisis_mentions("No thoughts of self-harm.")


def test_budget_stops_runs_and_tracks_daily_spend():
    with tempfile.TemporaryDirectory() as tmp:
        budget_mod.LEDGER_DIR = Path(tmp)
        meter = UsageMeter()
        b = budget_mod.Budget(meter, "tester", run_limit=0.01, daily_limit=0.02)
        assert b.can_start("round1")
        meter.add(CallRecord("x", "y", 1, 1000, 0, 0, 1000, 0, 1.0, 0.009, True))
        assert not b.can_start("round2")      # 0.009 + 0.0012 > 0.01
        assert not b.can_start("round1", 4)   # rounds reserve per agent: 4 x 0.0025
        b.close()
        b2 = budget_mod.Budget(UsageMeter(), "tester", run_limit=0.05, daily_limit=0.02)
        assert abs(b2.limit - 0.011) < 1e-9  # what is left of today
        budget_mod.add_spend("tester", 0.02)
        try:
            budget_mod.Budget(UsageMeter(), "tester", daily_limit=0.02)
        except budget_mod.DailyBudgetExceeded:
            pass
        else:
            raise AssertionError("daily budget should block a new run")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
