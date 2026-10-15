"""Offline tests for step 6: the safety rules for explanation cards and self-care steps
(planted bad items, no model calls).

Run: .venv/bin/python tests/test_explanation_safety.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import conference, safety  # noqa: E402
from backend.panel import code_safety_pass, flatten_summary  # noqa: E402


def card(cid: str, title: str, against: list[str] | None = None, label: str = conference.NOT_A_DIAGNOSIS) -> dict:
    return {"id": cid, "title": title, "label": label, "strength": "possible", "score": 2,
            "why_it_fits": [{"text": "Low ferritin and a positive stool test.", "finding_refs": ["hematology.F1"]}],
            "argues_against": ["Heavy periods could explain the low iron too."] if against is None else against,
            "would_help_tell": ["Ask about a colonoscopy."], "refs": ["hematology.F1"], "regions": ["blood"], "specialists": []}


def step(action: str, category: str = "sleep") -> dict:
    return {"category": category, "action": action, "why_it_may_help": "It may help you feel rested.",
            "how_to_track": "Note it in a diary.", "check_first_if": "if symptoms get worse", "refs": [], "source_url": "u"}


def summary(cards: list[dict], steps: list[dict] | None = None) -> dict:
    return {"plain_language_summary": "Your results show a pattern worth discussing.", "explanations": cards,
            "see_first": [{"who": "GI", "why": "Ask about the colonoscopy.", "urgency": "soon", "related_to": ["C1"]}],
            "key_findings": [], "medication_discussion": [], "questions_for_doctors": [], "red_flags": [], "body_regions": [],
            "limitations": [], "self_care": {"steps": steps or [], "care_first": False, "message": None}}


def test_patterns_to_discuss_are_allowed():
    ok = ["Slow blood loss in the gut is a pattern that could connect your tiredness and low iron.",
          "Celiac disease is worth asking about because it can cause low iron that does not improve.",
          "Ask whether you have celiac disease testing planned.",
          "If you have kidney disease, ask how it affects these results.",
          "Transferrin saturation was 6%, which is low."]
    for text in ok:
        assert safety.violations(text) == [], (text, safety.violations(text))


def test_you_have_language_and_odds_are_blocked():
    bad = {"You have celiac disease.": "diagnosis_language", "You've got an iron deficiency.": "diagnosis_language",
           "This is a classic case of lupus.": "diagnosis_language", "Your PCOS explains the acne.": "diagnosis_language",
           "Your child has kidney disease.": "diagnosis_language",
           "There is a 70% chance this is thyroid related.": "probability_language",
           "The probability of an autoimmune cause is high.": "probability_language"}
    for text, problem in bad.items():
        assert problem in safety.violations(text), (text, safety.violations(text))


def test_card_with_diagnosis_title_is_removed_and_good_card_stays():
    s = summary([card("C1", "You have iron deficiency anemia from your stomach ulcer."),
                 card("C2", "Stomach irritation from ibuprofen could connect your stomach pain and low iron.")])
    out, blocked = code_safety_pass(s)
    assert [c["id"] for c in out["explanations"]] == ["C2"]
    assert any(b["item_id"] == "E1.title" and b["action"] == "removed the card" for b in blocked)


def test_missing_label_is_restored_and_logged():
    out, blocked = code_safety_pass(summary([card("C1", "A thyroid pattern could connect tiredness and weight gain.", label="")]))
    assert out["explanations"][0]["label"] == conference.NOT_A_DIAGNOSIS
    assert blocked[0]["problems"] == ["missing_label"]


def test_one_sided_cards_are_not_shown():
    out, blocked = code_safety_pass(summary([card("C1", "A thyroid pattern could connect tiredness and weight gain.", against=[])]))
    assert out["explanations"] == [] and blocked[0]["problems"] == ["one_sided_or_empty"]
    # The reviewer removing the only 'argues against' point hides the card too.
    s = summary([card("C1", "A pattern could connect these.", against=["You have lupus."])])
    out, _ = code_safety_pass(s)
    assert out["explanations"] == []


def test_self_care_steps_are_rechecked_after_rewrites():
    ctx = {"activity_needs_doctor": True, "no_extra_fluids": True, "no_salt_potassium": True, "pediatric": False,
           "reasons": ["falls"]}
    s = summary([], [step("You could keep a regular bedtime."),
                     step("You could take a vitamin D supplement each morning."),
                     step("You could walk 30 minutes a day.", "activity"),
                     step("You could drink more water through the day.", "hydration"),
                     step("You could take your warfarin at the same time each night.")])
    out, blocked = code_safety_pass(s, medications=["warfarin"], self_care_ctx=ctx)
    assert [x["action"] for x in out["self_care"]["steps"]] == ["You could keep a regular bedtime."]
    assert sum(1 for b in blocked if b["action"] == "removed the step") == 4


def test_every_card_part_is_reviewed():
    ids = [i for i, _ in flatten_summary(summary([card("C1", "A pattern could connect these.")], [step("Sleep more.")]))]
    for expected in ("E1.title", "E1.fit1", "E1.against1", "E1.tell1", "SF1", "SC1", "SC1.why", "SC1.track"):
        assert expected in ids


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
