"""The panel roster: every specialty the app knows, in one place.

Adding a specialty means adding one entry here (and, from Phase 3, one short profile
file). No other code changes. Oncology is deliberately absent: a document suggesting a
possible malignancy raises a calm red flag instead of going to a specialist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Tier = Literal["coordinator", "always", "frequent", "on_demand"]


@dataclass(frozen=True)
class Specialty:
    id: str
    name: str
    tier: Tier
    scope: str  # one line used by the intake agent for routing


ROSTER: tuple[Specialty, ...] = (
    # Coordinators: exactly one leads each case.
    Specialty("internal_medicine", "Internal medicine", "coordinator",
              "Adult primary care: general visit notes, problem lists, routine adult labs; leads adult cases."),
    Specialty("pediatrics", "Pediatrics", "coordinator",
              "Patients under 18: well-child visits, growth records, pediatric labs; leads pediatric cases."),
    # Always on when the patient takes any medication.
    Specialty("clinical_pharmacist", "Clinical pharmacist", "always",
              "Medication lists, prescriptions, pharmacy printouts, discharge medication lists."),
    # Frequent specialists.
    Specialty("cardiology", "Cardiology", "frequent",
              "ECGs, Holter monitors, echocardiograms, blood pressure, cholesterol, palpitations, chest symptoms, atrial fibrillation, anticoagulation for the heart."),
    Specialty("endocrinology", "Endocrinology", "frequent",
              "Thyroid tests, glucose and HbA1c, diabetes, hormones, growth problems, bone metabolism."),
    Specialty("gastroenterology", "Gastroenterology", "frequent",
              "Endoscopy and colonoscopy, liver tests, stool tests, digestive symptoms, GI bleeding."),
    Specialty("neurology", "Neurology", "frequent",
              "Brain imaging reports, headaches, numbness, weakness, memory, concentration or balance problems, seizures."),
    Specialty("hematology", "Hematology", "frequent",
              "Abnormal blood counts, anemia, iron studies, B12, clotting tests and INR, bleeding or bruising."),
    Specialty("nephrology", "Nephrology", "frequent",
              "Creatinine, eGFR, BUN, electrolytes, urinalysis, protein or blood in urine, kidney disease, kidney-related blood pressure."),
    Specialty("rheumatology", "Rheumatology", "frequent",
              "Autoantibodies (ANA etc.), ESR/CRP, joint pain or stiffness, multi-system symptoms (skin + kidney + blood), Raynaud's."),
    # On-demand specialists.
    Specialty("pulmonology", "Pulmonology", "on_demand",
              "Chest X-ray and CT reports, spirometry, oxygen levels, cough, breathing symptoms."),
    Specialty("orthopedics", "Orthopedics and traumatology", "on_demand",
              "Bone and joint X-rays, fractures, joint injuries, osteoarthritis, falls with injury."),
    Specialty("ophthalmology", "Ophthalmology", "on_demand",
              "Eye exams, vision tests, eye symptoms."),
    Specialty("obstetrics_gynecology", "Obstetrics and gynecology", "on_demand",
              "Gynecologic studies, pregnancy, menstrual problems, contraception."),
    Specialty("urology", "Urology", "on_demand",
              "Prostate, PSA, urinary tract structure, urinary symptoms in men, kidney stones, bladder."),
    Specialty("dermatology", "Dermatology", "on_demand",
              "Skin findings, rashes, skin biopsies, hair and nail problems."),
    Specialty("otolaryngology", "Otolaryngology (ENT)", "on_demand",
              "Ear, nose, throat, hearing, sinus, voice."),
    Specialty("infectious_disease", "Infectious disease", "on_demand",
              "Cultures, serologies, infections, H. pylori, recurrent or unusual infections."),
    Specialty("psychiatry", "Psychiatry", "on_demand",
              "Anxiety, depression, sleep, mood, mental health medications. Crisis rules apply."),
)

BY_ID: dict[str, Specialty] = {s.id: s for s in ROSTER}
COORDINATOR_IDS = tuple(s.id for s in ROSTER if s.tier == "coordinator")
PHARMACIST_ID = "clinical_pharmacist"
PREGNANCY_SPECIALTY_ID = "obstetrics_gynecology"
# Specialists the intake agent may activate (not coordinators, not the pharmacist).
PANEL_IDS = tuple(s.id for s in ROSTER if s.tier in ("frequent", "on_demand"))
ALL_IDS = tuple(s.id for s in ROSTER)

MAX_ACTIVE_SPECIALISTS = 5  # not counting the coordinator and the pharmacist

# Literal types for structured outputs, so the model can only name real specialties.
SpecialtyId = Literal[ALL_IDS]  # type: ignore[valid-type]
PanelSpecialtyId = Literal[PANEL_IDS]  # type: ignore[valid-type]


def roster_text(ids: tuple[str, ...] = ALL_IDS) -> str:
    """The roster as prompt text: one line per specialty."""
    return "\n".join(f"- {BY_ID[i].id}: {BY_ID[i].name}. {BY_ID[i].scope}" for i in ids)
