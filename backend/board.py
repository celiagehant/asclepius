"""The shared case board: one compact line per verified finding, readable by the whole panel.

The board is built in code from outputs that have already passed validation, so every
post traces back to a finding whose quote was found in the cited document (or a
pharmacist issue, or a lab value printed on a document). No model writes to the board
directly, and nothing that failed a check can reach it.

Post format (about 25 tokens):
  cardiology.F2 | cardiovascular | palpitations, fatigue | Resting heart rate 112 on ECG | abnormal | heart
"""

from __future__ import annotations

import re
from typing import Any

from . import safety
from .registry import BY_ID, PHARMACIST_ID

MAX_POSTS_PER_MEMBER = 6
MAX_INTAKE_POSTS = 6
MAX_LINE_WORDS = 20  # the prompt asks for 15; longer lines are cut, not rejected
SIGNIFICANCE_ORDER = {"abnormal": 0, "borderline": 1, "unclear": 2, "normal_but_relevant": 3}
SYSTEMS = (
    "cardiovascular", "respiratory", "digestive", "liver", "kidney_urinary", "endocrine_metabolic", "blood",
    "immune_joints", "nervous_system", "mental_health", "skin", "musculoskeletal", "reproductive", "eyes",
    "ear_nose_throat", "medication", "lifestyle", "general",
)
SYSTEM_LABELS = {
    "cardiovascular": "Heart & circulation", "respiratory": "Lungs & breathing", "digestive": "Digestive",
    "liver": "Liver", "kidney_urinary": "Kidneys & urinary", "endocrine_metabolic": "Hormones & metabolism",
    "blood": "Blood", "immune_joints": "Immune & joints", "nervous_system": "Nervous system",
    "mental_health": "Mental health", "skin": "Skin", "musculoskeletal": "Bones & muscles",
    "reproductive": "Reproductive", "eyes": "Eyes", "ear_nose_throat": "Ear, nose & throat",
    "medication": "Medicines", "lifestyle": "Lifestyle", "general": "General",
}
# Where an intake lab with no specialist post belongs (first matching key wins).
LAB_SYSTEMS = (
    (("ferritin", "iron", "hemoglobin", "hgb", "hematocrit", "mcv", "platelet", "wbc", "white", "rbc", "b12", "folate",
      "inr", "pt ", "ptt", "neutrophil", "lymph"), "blood"),
    (("creatinine", "egfr", "gfr", "bun", "urea", "urine", "protein", "albumin/creat", "potassium", "sodium", "chloride",
      "bicarbonate", "co2"), "kidney_urinary"),
    (("alkaline phos", "alk phos", "alp "), "bone_or_liver"),
    (("phosph", "calcium", "magnesium", "pth", "parathyroid"), "endocrine_metabolic"),
    (("glucose", "a1c", "hba1c", "tsh", "t4", "t3", "cortisol", "insulin", "testosterone", "estradiol", "vitamin d",
      "cholesterol", "ldl", "hdl", "triglyceride", "lipid"), "endocrine_metabolic"),
    (("alt", "ast", "bilirubin", "alkaline", "alp", "ggt", "albumin"), "liver"),
    (("troponin", "bnp", "ck"), "cardiovascular"),
    (("ana", "esr", "crp", "complement", "c3", "c4", "dsdna", "rheumatoid", "anti-"), "immune_joints"),
    (("stool", "calprotectin", "occult", "lipase", "amylase", "pylori"), "digestive"),
)
# Words that look plural but are not.
_KEEP = {"diabetes", "stress", "dizziness", "weakness", "tiredness", "numbness", "shortness of breath", "jaundice",
         "hives", "measles", "mumps", "rabies", "herpes", "lupus", "sinus", "bronchitis", "arthritis"}


def norm_symptom(tag: str) -> str:
    """Lowercase, trimmed, simple plural merged ('palpitations' -> 'palpitation')."""
    t = re.sub(r"\s+", " ", tag.strip().lower()).strip(" .,;:")
    if not t or t in _KEEP or t.endswith(("ss", "us", "is", "ness")):
        return t
    if re.search(r"(sh|x|ss|zz)es$", t) or (t.endswith("ches") and not t.endswith("aches")):
        return t[:-2]
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("s") and len(t) > 3:
        return t[:-1]
    return t


def _tags(raw: list[str]) -> list[str]:
    out: list[str] = []
    for t in raw[:3]:
        n = norm_symptom(t)
        if n and n not in out and len(n) <= 40:
            out.append(n)
    return out


def _line(text: str, fallback: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text or safety.violations(text):
        text = re.sub(r"\s+", " ", fallback.strip())
    words = text.split(" ")
    return " ".join(words[:MAX_LINE_WORDS]) + ("…" if len(words) > MAX_LINE_WORDS else "")


def posts_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    """A specialist's validated findings as board posts: abnormal and borderline first, at most 6."""
    findings = sorted(report["findings"], key=lambda f: SIGNIFICANCE_ORDER.get(f["significance"], 9))
    posts = []
    for f in findings[:MAX_POSTS_PER_MEMBER]:
        posts.append({
            "id": f["id"], "by": report["specialty"], "by_name": report["name"],
            "system": f.get("system") if f.get("system") in SYSTEMS else "general",
            "symptoms": _tags(f.get("symptoms") or []),
            "line": _line(f.get("board_line", ""), f["statement"]),
            "significance": f["significance"], "region": f.get("region"), "document": f["document"],
        })
    return posts


def posts_from_pharmacist(pharm: dict[str, Any]) -> list[dict[str, Any]]:
    urgency_order = {"urgent": 0, "soon": 1, "routine": 2}
    issues = sorted(pharm["issues"], key=lambda i: urgency_order.get(i["urgency"], 9))
    return [{
        "id": i["id"], "by": PHARMACIST_ID, "by_name": "Clinical pharmacist", "system": "medication",
        "symptoms": _tags(i.get("symptoms") or []),
        "line": _line(i.get("board_line", ""), f"{', '.join(i['medications'])}: {i['explanation']}"),
        "significance": "abnormal" if i["urgency"] != "routine" else "borderline", "region": None,
        "document": "medication review",
    } for i in issues[:MAX_POSTS_PER_MEMBER]]


def _lab_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def lab_system(test: str, pediatric: bool = False) -> str:
    t = f" {test.lower()} "
    for keys, system in LAB_SYSTEMS:
        if any(k in t for k in keys):
            if system == "bone_or_liver":  # in children a high alkaline phosphatase is mostly bone
                return "musculoskeletal" if pediatric else "liver"
            return system
    return "general"


def posts_from_intake_labs(labs: list[Any], covered_text: str, pediatric: bool = False) -> list[dict[str, Any]]:
    """Flagged lab values no specialist posted (e.g. a lab report routed to nobody)."""
    covered = _lab_key(covered_text)
    posts, seen = [], set()
    for lab in labs:
        if lab.flag == "none":
            continue
        key = _lab_key(lab.test)
        if not key or key in seen or key in covered:
            continue
        seen.add(key)
        unit = f" {lab.unit}" if lab.unit else ""
        rng = f" (range {lab.reference_range})" if lab.reference_range else ""
        # A child's report may print adult ranges, so a printed flag no specialist confirmed stays "unclear".
        line = f"{lab.test} {lab.value}{unit}, flagged {lab.flag}{rng}" + ("; printed range may be adult, check for age" if pediatric else "")
        posts.append({
            "id": f"intake.L{len(posts) + 1}", "by": "intake", "by_name": "Intake", "system": lab_system(lab.test, pediatric),
            "symptoms": [], "line": line, "significance": "unclear" if pediatric else "abnormal", "region": None,
            "document": lab.document,
        })
        if len(posts) >= MAX_INTAKE_POSTS:
            break
    return posts


def render(posts: list[dict[str, Any]]) -> str:
    """The board as prompt text. Same order for every reader, so the block can be cached."""
    if not posts:
        return "<case_board>\n(empty)\n</case_board>"
    lines = [f"{p['id']} | {p['system']} | {', '.join(p['symptoms']) or '-'} | {p['line']} | {p['significance']}"
             + (f" | {p['region']}" if p.get("region") else "") for p in posts]
    return ("<case_board>\nid | system | symptom tags | finding | significance | region\n"
            + "\n".join(lines) + "\n</case_board>")


def index(posts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in posts}


def member_name(member: str) -> str:
    extra = {"intake": "Intake", "lifestyle": "Lifestyle & prevention", "skeptic": "Skeptic"}
    return extra.get(member) or (BY_ID[member].name if member in BY_ID else member)
