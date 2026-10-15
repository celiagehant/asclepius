"""Offline tests for the shared case board and the four-round conference rules (no model calls).

Run: .venv/bin/python tests/test_conference.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import board, conference, patterns  # noqa: E402


def finding(fid: str, system: str, significance: str = "abnormal", region: str | None = None, line: str = "x",
            symptoms: list[str] | None = None) -> dict:
    return {"id": fid, "statement": f"statement {fid}", "document": "d.pdf", "quote": "q", "significance": significance,
            "region": region, "board_line": line, "system": system, "symptoms": symptoms or []}


def posts_for(*specs: tuple[str, str, str]) -> dict[str, dict]:
    """(id, system, significance) -> board index."""
    out = []
    for fid, system, sig in specs:
        out.append({"id": fid, "by": fid.split(".")[0], "system": system, "symptoms": [], "line": fid,
                    "significance": sig, "region": None})
    return board.index(out)


def card(title: str, refs: list[str], pattern_id: str = "panel-proposed") -> NS:
    return NS(title=title, board_refs=refs, pattern_id=pattern_id, why_it_fits=["fits"], would_help_tell=["ask about x"])


# ---- the board ---------------------------------------------------------------------------

def test_board_posts_come_only_from_validated_findings_abnormal_first():
    report = {"specialty": "hematology", "name": "Hematology", "findings": [
        finding("hematology.F1", "blood", "normal_but_relevant"), finding("hematology.F2", "blood", "abnormal", "blood"),
        *[finding(f"hematology.F{i}", "blood", "borderline") for i in range(3, 9)]]}
    posts = board.posts_from_report(report)
    assert len(posts) == board.MAX_POSTS_PER_MEMBER
    assert posts[0]["id"] == "hematology.F2"                      # abnormal first
    assert "hematology.F1" not in {p["id"] for p in posts}        # the normal one is cut by the cap
    assert all(p["by"] == "hematology" for p in posts)


def test_board_lines_fall_back_when_unsafe_and_tags_are_normalized():
    report = {"specialty": "cardiology", "name": "Cardiology", "findings": [
        finding("cardiology.F1", "cardiovascular", line="You have heart failure", symptoms=["Palpitations", "muscle aches", "Palpitations "]),
        finding("cardiology.F2", "not-a-system", line="one two three four five six seven eight nine ten eleven twelve "
                "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo")]}
    p1, p2 = board.posts_from_report(report)
    assert p1["line"] == "statement cardiology.F1"                 # forbidden wording never reaches the board
    assert p1["symptoms"] == ["palpitation", "muscle ache"]
    assert p2["system"] == "general" and p2["line"].endswith("…")
    assert [board.norm_symptom(x) for x in ("rashes", "headaches", "dizziness", "bruises", "diabetes")] == \
        ["rash", "headache", "dizziness", "bruise", "diabetes"]


def test_intake_labs_post_only_what_no_specialist_covered():
    labs = [NS(test="Phosphorus", value="5.4", unit="mg/dL", reference_range="2.5 - 4.5", flag="high", document="labs.pdf"),
            NS(test="Hemoglobin", value="11.0", unit="g/dL", reference_range="11.5-15.5", flag="low", document="labs.pdf"),
            NS(test="Alkaline phosphatase", value="245", unit="U/L", reference_range="40 - 130", flag="high", document="labs.pdf"),
            NS(test="Sodium", value="140", unit="mmol/L", reference_range="135-145", flag="none", document="labs.pdf")]
    posts = board.posts_from_intake_labs(labs, covered_text="Hemoglobin 11.0 below pediatric range", pediatric=True)
    assert [p["id"] for p in posts] == ["intake.L1", "intake.L2"]
    assert posts[0]["system"] == "endocrine_metabolic"
    assert posts[1]["system"] == "musculoskeletal"                 # alkaline phosphatase in a child: bone
    assert all(p["significance"] == "unclear" and "check for age" in p["line"] for p in posts)  # adult ranges on a child's report
    assert board.lab_system("Alkaline phosphatase") == "liver"     # in an adult: liver


def test_pattern_library_is_data_with_checked_shape_and_no_cancer_patterns():
    lib = patterns.load()
    assert len(lib) >= 20 and len({p["id"] for p in lib}) == len(lib)
    for p in lib:
        assert p["source"].startswith("https://medlineplus.gov/")
        assert set(p["systems"]) <= set(board.SYSTEMS)
        assert p["often_confused_with"] and p["what_doctors_may_check"]
    text = patterns.library_block().lower()
    assert "starting point, not a limit" in text
    for word in ("cancer", "malignan", "tumor", "oncolog", "lymphoma", "leukemia"):
        assert word not in text


# ---- round 2: connections ------------------------------------------------------------------

def test_connections_need_two_real_posts_from_two_systems():
    posts = posts_for(("hematology.F1", "blood", "abnormal"), ("hematology.F2", "blood", "abnormal"),
                      ("gastroenterology.F1", "digestive", "abnormal"))
    kept, dropped = conference.validate_connections("hematology", [
        card("Iron loss could connect these", ["hematology.F1", "gastroenterology.F1", "made-up.F9"], "P01"),
        card("Same system only", ["hematology.F1", "hematology.F2"]),
    ], posts)
    assert [k["refs"] for k in kept] == [["hematology.F1", "gastroenterology.F1"]]  # invented ref removed
    assert [d["reason"] for d in dropped] == ["all posts are in one body system"]
    kept, dropped = conference.validate_connections("hematology", [card("Only one post", ["hematology.F1", "made-up.F2"])], posts)
    assert not kept and dropped[0]["reason"] == "needs at least 2 existing board posts"


def test_connections_with_diagnosis_wording_or_unknown_patterns():
    posts = posts_for(("a.F1", "blood", "abnormal"), ("b.F1", "digestive", "abnormal"))
    kept, dropped = conference.validate_connections("a", [card("You have celiac disease", ["a.F1", "b.F1"], "P03")], posts)
    assert not kept and "forbidden language" in dropped[0]["reason"]
    kept, _ = conference.validate_connections("a", [card("Could connect", ["a.F1", "b.F1"], "P99")], posts)
    assert kept[0]["pattern_id"] == conference.PANEL_PROPOSED
    many = [card(f"c{i}", ["a.F1", "b.F1"]) for i in range(4)]
    kept, _ = conference.validate_connections("a", many, posts)
    assert len(kept) == conference.MAX_CARDS_PER_MEMBER


def test_merge_keeps_different_library_patterns_apart():
    posts = posts_for(("hematology.F1", "blood", "abnormal"), ("hematology.F2", "blood", "abnormal"),
                      ("nephrology.F1", "kidney_urinary", "abnormal"), ("nephrology.F2", "kidney_urinary", "abnormal"),
                      ("pharmacist.I1", "medication", "abnormal"), ("rheumatology.F1", "skin", "abnormal"))
    cards = [
        {"by": "hematology", "title": "Bleeding risk", "refs": ["hematology.F1", "pharmacist.I1"], "pattern_id": "P19", "why_it_fits": [], "would_help_tell": []},
        {"by": "cardiology", "title": "Bleeding risk 2", "refs": ["hematology.F1", "hematology.F2", "pharmacist.I1"], "pattern_id": "P19", "why_it_fits": [], "would_help_tell": []},
        {"by": "nephrology", "title": "Kidney strain", "refs": ["nephrology.F1", "pharmacist.I1", "hematology.F1"], "pattern_id": "P14", "why_it_fits": [], "would_help_tell": []},
        {"by": "rheumatology", "title": "New idea", "refs": ["nephrology.F1", "nephrology.F2", "rheumatology.F1"], "pattern_id": "panel-proposed", "why_it_fits": [], "would_help_tell": []},
        {"by": "dermatology", "title": "New idea again", "refs": ["nephrology.F2", "rheumatology.F1"], "pattern_id": "panel-proposed", "why_it_fits": [], "would_help_tell": []},
    ]
    cands = conference.merge_candidates(cards, posts)
    by_pattern = {c["pattern_id"]: c for c in cands}
    assert len(cands) == 3
    assert by_pattern["P19"]["proposers"] == ["hematology", "cardiology"] and by_pattern["P19"]["id"] == "C1"
    assert by_pattern["P14"]["proposers"] == ["nephrology"]                # shares posts with P19 but stays separate
    assert by_pattern["panel-proposed"]["proposers"] == ["rheumatology", "dermatology"]
    assert by_pattern["P19"]["systems"] == ["blood", "medication"]


# ---- round 3: skeptic, stances, scoring ----------------------------------------------------

def _cands() -> tuple[list[dict], dict[str, dict]]:
    posts = posts_for(("a.F1", "blood", "abnormal"), ("b.F1", "digestive", "abnormal"), ("c.F1", "skin", "borderline"))
    cards = [{"by": "a", "title": "One", "refs": ["a.F1", "b.F1"], "pattern_id": "P01", "why_it_fits": [], "would_help_tell": []},
             {"by": "b", "title": "One again", "refs": ["a.F1", "b.F1"], "pattern_id": "P01", "why_it_fits": [], "would_help_tell": []},
             {"by": "c", "title": "Two", "refs": ["c.F1", "b.F1"], "pattern_id": "P03", "why_it_fits": [], "would_help_tell": []},
             {"by": "a", "title": "Three", "refs": ["a.F1", "c.F1"], "pattern_id": "P05", "why_it_fits": [], "would_help_tell": []}]
    return conference.merge_candidates(cards, posts), posts


def test_skeptic_output_is_checked_like_everyone_elses():
    cands, posts = _cands()
    out = NS(challenges=[NS(candidate="C1", verdict="keep", simpler_explanations=["x"], unsupported_refs=["made-up", "a.F1"],
                            missing=[], reason="ok"),
                         NS(candidate="C9", verdict="drop", simpler_explanations=[], unsupported_refs=[], missing=[], reason="?")],
             alternative=card("Simpler: one system", ["a.F1", "a.F1"]))
    challenges, alternative, dropped = conference.validate_skeptic(out, cands, posts)
    assert set(challenges) == {"C1"} and challenges["C1"]["unsupported_refs"] == ["a.F1"]
    assert alternative is None and dropped                         # the skeptic's own card must follow the rules too


def test_stances_defend_only_your_own_card():
    cands, posts = _cands()
    raw = [NS(candidate="C1", stance="defend", reason="r", board_refs=["a.F1"]),       # c did not propose C1 -> support
           NS(candidate="C2", stance="challenge", reason="r", board_refs=[]),          # c proposed C2 -> concede
           NS(candidate="C3", stance="concede", reason="r", board_refs=[]),            # not c's card -> ignored
           NS(candidate="C1", stance="challenge", reason="dup", board_refs=[]),        # second stance on C1 -> ignored
           NS(candidate="C7", stance="support", reason="r", board_refs=[])]            # unknown candidate -> ignored
    st = conference.validate_stances("c", raw, cands, posts)
    assert [(x["candidate"], x["stance"]) for x in st] == [("C1", "support"), ("C2", "concede")]


def test_scoring_is_arithmetic_and_drops_need_a_defense():
    cands, _ = _cands()  # C1: P01 by a,b  C2: P03 by c  C3: P05 by a
    challenges = {"C1": {"verdict": "keep"}, "C2": {"verdict": "drop"}, "C3": {"verdict": "weaken"}}
    stances = [{"by": "c", "candidate": "C1", "stance": "support"}, {"by": "a", "candidate": "C1", "stance": "defend"},
               {"by": "a", "candidate": "C3", "stance": "defend"}, {"by": "b", "candidate": "C3", "stance": "challenge"}]
    scored = {c["id"]: c for c in conference.score_candidates(cands, challenges, stances)}
    assert scored["C1"]["score"] == 3 and scored["C1"]["strength"] == "stronger"      # 2 proposers + 1 support
    assert scored["C2"]["removed"].startswith("skeptic: drop")                         # dropped and nobody defended
    assert scored["C3"]["score"] == -1 and scored["C3"]["strength"] == "weaker"       # 1 - 1 challenge - 1 weaken
    top = conference.top_candidates(conference.score_candidates(cands, challenges, stances))
    assert [c["id"] for c in top] == ["C1", "C3"]                                       # no padding with removed cards
    defended = conference.score_candidates(cands, challenges, stances + [{"by": "c", "candidate": "C2", "stance": "defend"}])
    c2 = next(c for c in defended if c["id"] == "C2")
    assert c2["removed"] is None and c2["score"] == -1                                 # defended drop: kept at -2


def test_card_regions_come_from_posts_not_the_model():
    posts = board.index([{"id": "a.F1", "region": "blood"}, {"id": "b.F1", "region": "stomach"},
                         {"id": "c.F1", "region": None}, {"id": "d.F1", "region": "blood"}])
    assert conference.regions_for(["a.F1", "b.F1", "c.F1", "d.F1", "zz"], posts) == ["blood", "stomach"]


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
