"""Offline tests for the lifestyle and prevention agent's code-level rules (no model calls).

Run: .venv/bin/python tests/test_lifestyle.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import lifestyle  # noqa: E402

SRC = "https://medlineplus.gov/healthysleep.html"
URLS = {SRC, "https://medlineplus.gov/exerciseandphysicalfitness.html"}
MEDS = ["warfarin", "Coumadin", "naproxen sodium", "Children's multivitamin", "water pill (hydrochlorothiazide)"]


def step(action: str, category: str = "sleep", source: str = SRC, check: str = "if symptoms get worse", why: str = "may help",
         track: str = "note it in a diary") -> NS:
    return NS(category=category, action=action, why_it_may_help=why, board_refs=["a.F1", "zz.F9"], how_to_track=track,
              check_first_if=check, source_url=source)


def post(system: str, significance: str = "abnormal", symptoms: list[str] | None = None, line: str = "x") -> dict:
    return {"id": f"{system}.F1", "by": system, "system": system, "symptoms": symptoms or [], "line": line,
            "significance": significance, "region": None}


def ctx(**over) -> dict:
    base = lifestyle.context([], pediatric=False, pregnancy=False, urgent_concerns=[])
    return {**base, **over}


def run(steps: list[NS], c: dict | None = None) -> tuple[list[dict], list[dict]]:
    return lifestyle.validate_steps(NS(steps=steps), tool_urls=URLS, posts={"a.F1": {}}, ctx=c or ctx(), medications=MEDS)


def test_lifestyle_posts_need_a_questionnaire_quote():
    q = "Lifestyle: daily habits: sleep about 5 hours; 4 coffees a day"
    out = NS(posts=[NS(board_line="Sleeps about 5 hours", symptoms=["fatigue"], quote="sleep about 5 hours"),
                    NS(board_line="Runs marathons", symptoms=[], quote="runs three marathons a year")])
    kept, dropped = lifestyle.validate_posts(out, q)
    assert [k["line"] for k in kept] == ["Sleeps about 5 hours"] and dropped[0]["reason"].startswith("quote not found")
    bp = lifestyle.as_board_posts(kept)
    assert bp[0]["id"] == "lifestyle.L1" and bp[0]["system"] == "lifestyle" and bp[0]["symptoms"] == ["fatigue"]


def test_context_comes_from_the_board():
    c = lifestyle.context([post("kidney_urinary"), post("musculoskeletal", "normal_but_relevant", ["fall", "dizziness"])],
                          pediatric=True, pregnancy=False, urgent_concerns=[])
    assert c["activity_needs_doctor"] and c["no_extra_fluids"] and c["no_salt_potassium"] and c["pediatric"]
    c = lifestyle.context([post("skin"), post("kidney_urinary", "normal_but_relevant")], pediatric=False, pregnancy=False,
                          urgent_concerns=[])
    assert not (c["activity_needs_doctor"] or c["no_extra_fluids"] or c["no_salt_potassium"])   # normal kidney post only
    assert lifestyle.context([], pediatric=False, pregnancy=True, urgent_concerns=[])["activity_needs_doctor"]


def test_good_steps_pass_with_refs_checked():
    kept, dropped = run([step("You could keep a regular bedtime and wake time."),
                         step("You could bring every medicine bottle and supplement you take to the visit.", "visit_preparation")])
    assert len(kept) == 2 and not dropped
    assert kept[0]["refs"] == ["a.F1"]                          # invented ref removed


def test_each_rule_drops_the_step_with_a_reason():
    cases = {
        "rule 2": step("You could keep a regular bedtime.", source="https://example.com/sleep"),
        "rule 3": step("You could take your warfarin at the same time each day."),
        "rule 3 ": step("You could try a magnesium supplement at night."),
        "rule 3  ": step("You could have 200 mg of caffeine less per day."),
        "rule 4": step("You could try intermittent fasting on weekdays.", "eating_pattern"),
        "rule 4 ": step("You could aim to lose 5 kg over the next months.", "eating_pattern"),
        "rule 6": step("You could keep a regular bedtime.", check="  "),
    }
    for label, st in cases.items():
        kept, dropped = run([st])
        assert not kept and any(p.startswith(label.strip()) for p in dropped[0]["problems"]), (label, dropped)


def test_rule_5_uses_the_patients_context():
    walk = step("You could take a short walk most days.", "activity")
    ask = step("You could ask your doctor what activity is safe for you before starting short walks.", "activity")
    falls = ctx(activity_needs_doctor=True, reasons=["falls"])
    assert run([walk])[0] and not run([walk], falls)[0] and run([ask], falls)[0]
    fluids = step("You could drink more water through the day.", "hydration")
    assert run([fluids])[0] and not run([fluids], ctx(no_extra_fluids=True))[0]
    salt = step("You could choose lower-salt foods.", "eating_pattern")
    assert run([salt])[0] and not run([salt], ctx(no_salt_potassium=True))[0]
    weight = step("You could watch portion sizes at dinner.", "eating_pattern")
    assert run([weight])[0] and not run([weight], ctx(pediatric=True))[0]   # no weight or diet advice for a child


def test_care_first_hides_every_step():
    sc = {"steps": [{"action": "a"}, {"action": "b"}]}
    hidden = lifestyle.apply_care_first(sc, urgent_present=True)
    assert hidden["steps"] == [] and hidden["care_first"] and hidden["hidden_steps"] == 2
    assert hidden["message"] == lifestyle.CARE_FIRST
    shown = lifestyle.apply_care_first(sc, urgent_present=False)
    assert len(shown["steps"]) == 2 and not shown["care_first"]


def test_at_most_five_steps():
    kept, _ = run([step(f"You could try sleep habit number {i}.") for i in range(8)])
    assert len(kept) == lifestyle.MAX_STEPS


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
