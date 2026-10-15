"""The lifestyle and prevention agent's outputs, checked in code.

Round 1: up to 3 lifestyle facts for the case board, each with a quote that must appear in
the questionnaire (the same check as every specialist finding).

Round 4: up to 5 self-care steps. The model is told the rules; code enforces the ones that
can be checked structurally, before the safety reviewer sees anything:
  rule 2  the source is a MedlinePlus URL a tool returned in this run
  rule 3  no medicine from this patient's lists, no supplement, no dose
  rule 4  no fasting, detox, calorie numbers or weight targets; no weight advice under 18
  rule 5  context from this patient's board: activity needs "ask your doctor first" after
          falls, dizziness, chest pain or in pregnancy; no "drink more" with kidney, heart
          or swelling findings; no salt or potassium advice with kidney findings
  rule 6  every step says when to check with a doctor first
  care first: if an urgent problem is present now, no steps are shown at all (applied at
          the end of the run, after the safety review, in apply_care_first)
"""

from __future__ import annotations

import re
from typing import Any

from . import safety

MAX_POSTS = 3
MAX_STEPS = 5
CARE_FIRST = "Get the care described above first. Self-care steps can wait until you have spoken with a doctor."

SUPPLEMENT = re.compile(r"\b(supplements?|vitamins?|herbal|herbs?|probiotics?|melatonin|iron (tablets?|pills?))\b", re.I)
# Visit preparation may say "bring every medicine bottle and supplement you take" (no names, no doses).
BRING = re.compile(r"\b(bring|list|show|write down|take along|gather)\b", re.I)
DOSE = re.compile(r"\b\d+(\.\d+)?\s*(mg|mcg|µg|ug|iu|units?|g)\b", re.I)
DIET = re.compile(r"\b(fast(ing)?|intermittent|detox\w*|cleanse\w*|keto\w*|calories?|kcal|low[- ]carb|juice diet|"
                  r"cut out (all|every)|eliminat\w+ diet)\b", re.I)
WEIGHT_TARGET = re.compile(r"\b(lose|drop|shed)\s+(\d+|some|a few)?\s*(kg|kilos?|lbs?|pounds?|weight)\b|\b\d+\s*(kg|lbs?|pounds?)\b"
                           r"|\bweight[- ]loss\b|\bbmi\b", re.I)
WEIGHT_ANY = re.compile(r"\b(weight|diet\w*|calori\w*|portion\w*|slim\w*)\b", re.I)
FLUIDS_UP = re.compile(r"\b(drink|have|increase|add)\b[^.]{0,30}\b(more|extra|plenty|lots of|8|eight|several)\b[^.]{0,20}"
                       r"\b(water|fluids?|liquids?|glasses)\b|\bstay (well[- ])?hydrated\b|\bincrease (your )?fluid", re.I)
SALT = re.compile(r"\b(salt|sodium|potassium|banana|electrolyte\w*)\b", re.I)
ASK_FIRST = re.compile(r"\b(ask|check with|talk (to|with)|speak (to|with)|clear (it )?with)\b[^.]{0,40}\b(doctor|care team|clinician|"
                       r"cardiologist|physician|pediatrician|nurse|provider)\b", re.I)
FALL_TAGS = re.compile(r"fall|dizz|faint|syncope|lighthead|chest pain|chest pressure|palpitation|breathless|shortness of breath", re.I)
SWELLING_TAGS = re.compile(r"swell|edema|oedema|puff", re.I)


def validate_posts(out: Any, q_text: str) -> tuple[list[dict], list[dict]]:
    posts, dropped = [], []
    for p in out.posts[:MAX_POSTS]:
        if not safety.quote_supported(p.quote, q_text):
            dropped.append({"item": p.board_line[:160], "reason": "quote not found in the questionnaire"})
            continue
        if safety.violations(p.board_line):
            dropped.append({"item": p.board_line[:160], "reason": "forbidden language"})
            continue
        posts.append({"line": p.board_line, "symptoms": p.symptoms, "quote": p.quote})
    return posts, dropped


def as_board_posts(posts: list[dict]) -> list[dict]:
    from .board import _line, _tags
    return [{"id": f"lifestyle.L{i}", "by": "lifestyle", "by_name": "Lifestyle & prevention", "system": "lifestyle",
             "symptoms": _tags(p["symptoms"]), "line": _line(p["line"], p["line"]), "significance": "normal_but_relevant",
             "region": None, "document": "questionnaire"} for i, p in enumerate(posts, start=1)]


def context(board_posts: list[dict], *, pediatric: bool, pregnancy: bool, urgent_concerns: list[str]) -> dict[str, Any]:
    """Facts about THIS patient that switch rule 5 on, computed from the board, never by a model."""
    flagged = [p for p in board_posts if p["significance"] in ("abnormal", "borderline")]
    tags = " ".join(t for p in board_posts for t in p["symptoms"]) + " " + " ".join(p["line"] for p in board_posts)
    cardiac_flag = any(re.search(r"chest pain|heart|cardiac|rhythm|faint", c, re.I) for c in urgent_concerns)
    kidney = any(p["system"] == "kidney_urinary" for p in flagged)
    heart = any(p["system"] == "cardiovascular" for p in flagged)
    swelling = bool(SWELLING_TAGS.search(tags))
    falls = bool(FALL_TAGS.search(tags))
    reasons = []
    if falls:
        reasons.append("falls, dizziness, fainting, chest pain or a racing heart are on the board")
    if cardiac_flag:
        reasons.append("a heart-related warning sign was raised")
    if pregnancy:
        reasons.append("pregnancy")
    return {
        "activity_needs_doctor": falls or cardiac_flag or pregnancy,
        "no_extra_fluids": kidney or heart or swelling,
        "no_salt_potassium": kidney,
        "pediatric": pediatric,
        "reasons": reasons,
        "kidney": kidney, "heart": heart, "swelling": swelling,
    }


def context_text(ctx: dict[str, Any]) -> str:
    lines = []
    if ctx["activity_needs_doctor"]:
        lines.append("- Activity: only 'ask your doctor what activity is safe for you first' (" + "; ".join(ctx["reasons"]) + ").")
    if ctx["no_extra_fluids"]:
        lines.append("- Fluids: no step to drink more (kidney, heart or swelling findings on the board).")
    if ctx["no_salt_potassium"]:
        lines.append("- Salt and potassium: no advice (kidney findings on the board).")
    if ctx["pediatric"]:
        lines.append("- Child: no weight, diet or calorie advice at all.")
    return "<context_notes>\n" + ("\n".join(lines) or "(no extra limits)") + "\n</context_notes>"


# Words that appear in medicine names but are not names ("water pill", "Children's multivitamin", "Acetaminophen PM").
GENERIC_WORDS = {
    "tablet", "tablets", "pill", "pills", "capsule", "capsules", "bottle", "daily", "night", "nightly", "with", "extended",
    "release", "cream", "ointment", "drops", "spray", "over", "counter", "children", "childrens", "adult", "extra",
    "strength", "plus", "water", "medicine", "medicines", "medication", "medications", "product", "products", "drug",
    "dose", "doses", "once", "twice", "every", "morning", "evening", "bedtime", "unknown", "brand", "generic", "topical",
    "oral", "only", "regular", "low-dose", "baby", "chewable", "liquid", "patch", "inhaler",
}


def _names(medications: list[str]) -> list[re.Pattern]:
    words = set()
    for m in medications:
        for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", m):
            if w.lower() not in GENERIC_WORDS:
                words.add(w.lower())
    return [re.compile(rf"\b{re.escape(w)}\b", re.I) for w in sorted(words)]


def validate_steps(out: Any, *, tool_urls: set[str], posts: dict[str, dict], ctx: dict[str, Any],
                   medications: list[str], tool_titles: dict[str, str] | None = None) -> tuple[list[dict], list[dict]]:
    """Apply rules 2-6 in code. A step that breaks one is dropped, with the reason logged."""
    med_patterns = _names(medications)
    kept, dropped = [], []
    for st in out.steps:
        text = f"{st.action} {st.why_it_may_help} {st.how_to_track}"
        problems = []
        if st.source_url not in tool_urls or "medlineplus.gov" not in st.source_url:
            problems.append("rule 2: source not returned by MedlinePlus in this run")
        supplement = SUPPLEMENT.search(text) and not (st.category == "visit_preparation" and BRING.search(st.action))
        if any(p.search(text) for p in med_patterns) or supplement or DOSE.search(text):
            problems.append("rule 3: mentions a medicine, supplement or dose")
        if DIET.search(text) or WEIGHT_TARGET.search(text):
            problems.append("rule 4: diet, fasting, calorie or weight target")
        if ctx["pediatric"] and WEIGHT_ANY.search(text):
            problems.append("rule 4: weight or diet advice for a child")
        if st.category == "activity" and ctx["activity_needs_doctor"] and not ASK_FIRST.search(st.action):
            problems.append("rule 5: activity step without 'ask your doctor first' (" + "; ".join(ctx["reasons"]) + ")")
        if ctx["no_extra_fluids"] and (st.category == "hydration" or FLUIDS_UP.search(text)):
            problems.append("rule 5: more fluids with kidney, heart or swelling findings")
        if ctx["no_salt_potassium"] and SALT.search(text):
            problems.append("rule 5: salt or potassium advice with kidney findings")
        if not st.check_first_if.strip():
            problems.append("rule 6: no 'check with a doctor first if'")
        bad_words = safety.violations(text)
        if bad_words:
            problems.append("forbidden language: " + ", ".join(bad_words))
        if problems:
            dropped.append({"item": st.action[:160], "category": st.category, "problems": problems})
            continue
        kept.append({"category": st.category, "action": st.action.strip(), "why_it_may_help": st.why_it_may_help.strip(),
                     "refs": [r for r in st.board_refs if r in posts], "how_to_track": st.how_to_track.strip(),
                     "check_first_if": st.check_first_if.strip(), "source_url": st.source_url,
                     "source_title": (tool_titles or {}).get(st.source_url)})
        if len(kept) >= MAX_STEPS:
            break
    return kept, dropped


def apply_care_first(self_care: dict[str, Any], urgent_present: bool) -> dict[str, Any]:
    """Rule 6 of the spec ('care first'): an urgent problem present now hides every step."""
    if urgent_present:
        return {**self_care, "care_first": True, "message": CARE_FIRST, "hidden_steps": len(self_care.get("steps", [])),
                "steps": []}
    return {**self_care, "care_first": False, "message": None}
