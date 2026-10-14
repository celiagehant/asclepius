"""Offline tests for the rules intake enforces in code (no model calls, no key needed).

    .venv/bin/python tests/test_intake_rules.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.intake import _components, _same_drug, decide_modes, find_conflicts, select_panel  # noqa: E402
from backend.schemas import (  # noqa: E402
    DocMedication, DocumentExtractionOutput, DocumentRecord, Questionnaire, RoutingOutput, SpecialistPick,
)

TODAY = date(2026, 10, 13)


def questionnaire(**patient) -> Questionnaire:
    base = {"name": "Dana Whitfield", "date_of_birth": "1984-03-12", "sex_at_birth": "female", "pregnant": False}
    return Questionnaire.model_validate({"patient": {**base, **patient}, "main_concern": "tired"})


def record(filename: str, specialties: list[str], meds: list[DocMedication] | None = None, name: str = "Dana Whitfield",
           dob: str | None = "1984-03-12") -> DocumentRecord:
    e = DocumentExtractionOutput(
        doc_type="lab_report", date="2026-08-01", source="x", specialties=specialties, summary="s",
        patient_name_on_document=name, patient_dob_on_document=dob, patient_sex_on_document="female", labs=[],
        medications=meds or [], mentions_possible_malignancy=False, mentions_self_harm=False, instructions_to_ai=[],
    )
    return DocumentRecord(filename=filename, sha256="0", kind="text", read_by="text", page_count=1, text="t",
                          hidden_text=[], notes=[], extraction=e)


def pick(specialty: str, relevance: int, docs: list[str] | None = None, symptoms: list[str] | None = None) -> SpecialistPick:
    return SpecialistPick(specialty=specialty, relevance=relevance, documents=docs or [], symptoms=symptoms or [], reason="r")


def med(name: str, generic: str, status: str = "taking") -> DocMedication:
    return DocMedication(name=name, generic_name=generic, dose=None, frequency=None, prescriber=None, status=status)


def test_modes_come_from_the_questionnaire():
    adult = decide_modes(questionnaire(), has_meds=True, today=TODAY)
    assert (adult.age_years, adult.coordinator, adult.pediatric, adult.pharmacist_active) == (42, "internal_medicine", False, True)
    child = decide_modes(questionnaire(date_of_birth="2019-04-02"), has_meds=False, today=TODAY)
    assert (child.age_years, child.coordinator, child.pediatric, child.pharmacist_active) == (7, "pediatrics", True, False)
    assert decide_modes(questionnaire(date_of_birth="2008-10-14"), True, TODAY).coordinator == "pediatrics"  # 17 the day before
    assert decide_modes(questionnaire(date_of_birth="2008-10-13"), True, TODAY).coordinator == "internal_medicine"  # 18 today
    assert decide_modes(questionnaire(pregnant=True), True, TODAY).pregnancy


def test_cap_of_five_and_consider_seeing():
    recs = [record("a.pdf", ["cardiology"])]
    routing = RoutingOutput(questionnaire_medications=[], specialists=[
        pick("cardiology", 5, ["a.pdf"]), pick("hematology", 4, symptoms=["pale"]), pick("nephrology", 4, symptoms=["x"]),
        pick("neurology", 3, symptoms=["headache"]), pick("endocrinology", 3, symptoms=["thirst"]),
        pick("dermatology", 2, symptoms=["rash"]), pick("urology", 1, symptoms=["nocturia"]),
    ])
    active, consider, unassigned = select_panel(routing, recs, decide_modes(questionnaire(), True, TODAY))
    assert [a.specialty for a in active] == ["cardiology", "hematology", "nephrology", "endocrinology", "neurology"]
    assert [c.specialty for c in consider] == ["dermatology", "urology"]
    assert unassigned == []


def test_no_document_and_no_symptom_means_not_activated():
    routing = RoutingOutput(questionnaire_medications=[], specialists=[pick("psychiatry", 5), pick("cardiology", 3, ["nope.pdf"])])
    active, consider, _ = select_panel(routing, [record("a.pdf", ["hematology"])], decide_modes(questionnaire(), True, TODAY))
    assert active == [] and consider == []  # unknown file names don't count as documents


def test_pregnancy_mode_always_includes_obgyn_within_the_cap():
    routing = RoutingOutput(questionnaire_medications=[], specialists=[
        pick(s, 5, symptoms=["x"]) for s in ("cardiology", "hematology", "nephrology", "neurology", "endocrinology")])
    active, consider, _ = select_panel(routing, [], decide_modes(questionnaire(pregnant=True), True, TODAY))
    assert active[0].specialty == "obstetrics_gynecology" and active[0].why_active == "pregnancy mode"
    assert len(active) == 5 and len(consider) == 1


def test_documents_follow_their_specialty_tags_and_untagged_go_to_coordinator():
    recs = [record("ecg.txt", ["cardiology"]), record("labs.pdf", ["cardiology", "hematology"]), record("meds.txt", ["clinical_pharmacist"])]
    routing = RoutingOutput(questionnaire_medications=[], specialists=[pick("cardiology", 5, ["ecg.txt"])])
    active, _, unassigned = select_panel(routing, recs, decide_modes(questionnaire(), True, TODAY))
    assert active[0].documents == ["ecg.txt", "labs.pdf"]
    assert unassigned == ["meds.txt"]


def test_drug_matching():
    assert _same_drug(_components("metoprolol succinate"), _components("metoprolol"))
    assert _same_drug(_components("birth control pill (norgestimate/ethinyl estradiol)"), _components("norgestimate/ethinyl estradiol"))
    assert not _same_drug(_components("levonorgestrel/ethinyl estradiol"), _components("norgestimate/ethinyl estradiol"))
    assert not _same_drug(_components("simvastatin"), _components("atorvastatin"))
    assert not _same_drug(_components(""), _components("aspirin"))


def test_conflicts_are_flagged_not_guessed():
    q = Questionnaire.model_validate({
        "patient": {"name": "Dana Whitfield", "date_of_birth": "1984-03-12", "sex_at_birth": "female"},
        "medications": [{"name": "Ibuprofen"}, {"name": "Vitamin D"}],
    })
    recs = [
        record("neph.pdf", ["nephrology"], [med("Lisinopril 5 mg", "lisinopril", "started")]),
        record("egd.pdf", ["gastroenterology"], [med("ibuprofen", "ibuprofen", "advised_to_avoid")]),
        record("other.pdf", ["hematology"], name="Sam Whitfield", dob="1990-01-01"),
    ]
    kinds = sorted(c.kind for c in find_conflicts(q, recs, None))
    assert kinds == sorted([
        "medication_not_on_your_list",      # lisinopril
        "advised_to_avoid_but_listed",      # ibuprofen
        "medication_not_in_records",        # vitamin D
        "different_patient_name", "different_birth_date",  # other.pdf
    ]), kinds


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
