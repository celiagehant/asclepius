"""Patient profiles: validation of questionnaire answers and conversion for the panel.

A profile is what the user answered in the health questionnaire. The panel never sees
the raw form; it gets a Questionnaire built here, with "prefer not to say" answers listed
explicitly so agents know what was withheld rather than guessing.
"""

from __future__ import annotations

from datetime import date

from .schemas import (
    Doctor, Patient, ProfileData, Questionnaire, QuestionnaireMedication,
)

TOBACCO = {"never": "never smoked", "former": "former smoker", "current": "current smoker"}
ALCOHOL = {"none": "no alcohol", "occasionally": "occasionally", "weekly": "weekly", "most_days": "most days"}


class ProfileError(ValueError):
    """Shown to the user as-is."""


def validate_profile(p: ProfileData, today: date | None = None) -> ProfileData:
    today = today or date.today()
    if p.date_of_birth:
        try:
            born = date.fromisoformat(p.date_of_birth)
        except ValueError as exc:
            raise ProfileError("Date of birth must be a real date (YYYY-MM-DD).") from exc
        if born > today or born.year < today.year - 120:
            raise ProfileError("Date of birth must be in the past 120 years.")
    age = p.age_on(today)
    if age is None:
        raise ProfileError("Age or date of birth is required: lab reference ranges depend on it.")
    if p.for_whom == "self" and age < 18:
        raise ProfileError("People under 18 can't create their own profile. A parent or guardian can add one "
                           "for them from their own account (choose \"someone in my care\").")
    data = p.model_dump()
    if not ProfileData.pregnancy_applies(p.sex_at_birth, age):
        data["pregnancy"] = None
    if p.medications_status != "listed":
        data["medications"] = []
    if p.allergies_status != "listed":
        data["allergies"] = []
    if p.conditions_status != "listed":
        data["conditions"], data["conditions_other"] = [], ""
    if p.family_status != "listed":
        data["family_history"], data["family_other"] = [], ""
    if p.main_concern_withheld:
        data["main_concern"] = ""
    data["name"] = p.name.strip()
    return ProfileData.model_validate(data)


def withheld_topics(p: ProfileData) -> list[str]:
    topics = []
    for label, value in (("sex assigned at birth", p.sex_at_birth), ("pregnancy or breastfeeding", p.pregnancy),
                         ("medications", p.medications_status), ("allergies", p.allergies_status),
                         ("conditions and surgeries", p.conditions_status), ("family history", p.family_status),
                         ("tobacco use", p.tobacco), ("alcohol use", p.alcohol)):
        if value == "prefer_not_to_say":
            topics.append(label)
    if p.main_concern_withheld:
        topics.append("main concern")
    return topics


def to_questionnaire(p: ProfileData, main_concern: str | None = None) -> Questionnaire:
    """The panel's view of a profile. `main_concern` overrides the profile's (per case)."""
    conditions = list(p.conditions) + ([p.conditions_other.strip()] if p.conditions_other.strip() else [])
    family = list(p.family_history) + ([p.family_other.strip()] if p.family_other.strip() else [])
    lifestyle = {}
    if p.tobacco in TOBACCO:
        lifestyle["tobacco"] = TOBACCO[p.tobacco]
    if p.alcohol in ALCOHOL:
        lifestyle["alcohol"] = ALCOHOL[p.alcohol]
    doctors = []
    for d in p.doctors:
        specialty, _, name = d.partition("-")
        doctors.append(Doctor(specialty=specialty.strip() or d.strip(), name=name.strip() or None))
    return Questionnaire(
        patient=Patient(
            name=p.name, date_of_birth=p.date_of_birth, age_years=p.age_years,
            sex_at_birth="prefer not to say" if p.sex_at_birth == "prefer_not_to_say" else p.sex_at_birth,
            pregnant=True if p.pregnancy == "pregnant" else (False if p.pregnancy in ("neither", "breastfeeding") else None),
        ),
        completed_by="patient" if p.for_whom == "self" else f"parent/guardian or carer ({p.relationship or 'in their care'})",
        pregnancy_status=p.pregnancy, breastfeeding=p.pregnancy == "breastfeeding",
        gender_identity=p.gender_identity or None, withheld=withheld_topics(p),
        main_concern=(main_concern if main_concern is not None else p.main_concern).strip(),
        known_conditions=conditions if p.conditions_status == "listed" else (["none"] if p.conditions_status == "none" else []),
        medications=[QuestionnaireMedication(name=m.name, dose=m.dose, how_often=m.how_often) for m in p.medications],
        allergies=p.allergies if p.allergies_status == "listed" else (["no known allergies"] if p.allergies_status == "none" else []),
        doctors=doctors, past_history=[f"Surgeries: {p.surgeries.strip()}"] if p.surgeries.strip() else [],
        family_history=family if p.family_status == "listed" else (["none known"] if p.family_status == "none_known" else []),
        lifestyle=lifestyle,
    )


def from_demo(profile_json: dict) -> tuple[ProfileData, str]:
    """Build a profile (and the case's main concern) from a demo patient's profile.json."""
    pt = profile_json["patient"]
    family_map = {"heart": "Heart disease", "diabet": "Diabetes", "arthritis": "Autoimmune conditions",
                  "lupus": "Autoimmune conditions"}
    family, family_other = [], []
    for item in profile_json.get("family_history", []):
        hit = next((v for k, v in family_map.items() if k in item.lower()), None)
        (family.append(hit) if hit and hit not in family else family_other.append(item))
    smoking = profile_json.get("lifestyle", {}).get("smoking", "").lower()
    tobacco = "former" if "quit" in smoking or "former" in smoking else ("never" if "never" in smoking or "no smokers" in smoking
                                                                        else "prefer_not_to_say")
    alcohol_text = profile_json.get("lifestyle", {}).get("alcohol", "").lower()
    alcohol = ("most_days" if "most" in alcohol_text or "evening" in alcohol_text else "weekly" if "week" in alcohol_text
               else "occasionally" if "occasion" in alcohol_text else "none" if "n/a" in alcohol_text else "prefer_not_to_say")
    conditions = [c for c in profile_json.get("known_conditions", []) if c.lower() != "none diagnosed"]
    symptoms = "; ".join(f"{s['symptom']}" + (f" ({s['since']})" if s.get("since") else "")
                         + (f": {s['details']}" if s.get("details") else "") for s in profile_json.get("symptoms", []))
    questions = " ".join(profile_json.get("questions_for_panel", []))
    concern = profile_json.get("main_concern", "") + (f"\n\nSymptoms: {symptoms}" if symptoms else "") + \
        (f"\n\nMy questions: {questions}" if questions else "")
    age = pt.get("age_years")
    sex = pt.get("sex_at_birth") or "prefer_not_to_say"
    data = ProfileData(
        for_whom="self" if (age or 0) >= 18 else "care", name=pt["name"],
        relationship=None if (age or 0) >= 18 else "child", date_of_birth=pt.get("date_of_birth"),
        sex_at_birth=sex, pregnancy=("pregnant" if pt.get("pregnant") else "neither") if ProfileData.pregnancy_applies(sex, age) else None,
        medications_status="listed" if profile_json.get("medications") else "none",
        medications=[{"name": m["name"], "dose": m.get("dose"), "how_often": m.get("how_often")} for m in profile_json.get("medications", [])],
        allergies_status="none" if not profile_json.get("allergies") or "no known" in profile_json["allergies"][0].lower() else "listed",
        allergies=[a for a in profile_json.get("allergies", []) if "no known" not in a.lower()],
        conditions_status="listed" if conditions or profile_json.get("past_history") else "none",
        conditions=[], conditions_other="; ".join(conditions), surgeries="; ".join(profile_json.get("past_history", [])),
        family_status="listed" if family or family_other else "none_known", family_history=family,
        family_other="; ".join(family_other), tobacco=tobacco, alcohol=alcohol, main_concern=concern[:3000],
        doctors=[f"{d['specialty']} - {d['name']}" if d.get("name") else d["specialty"] for d in profile_json.get("doctors", [])],
    )
    return validate_profile(data), concern[:3000]
