"""Deterministic safety checks that back up the model-based safety reviewer.

These run in code, so they work even if a model misbehaves:
  - quote verification: a finding's quote must really appear in the cited document
  - forbidden language: definitive diagnosis, medication changes, cancer words
  - crisis detection: signs of suicidal thoughts or self-harm (with simple negation)
  - calm red flag for any document that intake marked as mentioning a possible malignancy
"""

from __future__ import annotations

import re
import unicodedata

CRISIS_RESOURCES = (
    "If you are thinking about harming yourself or ending your life, please reach out now: in the US, "
    "call or text 988 (Suicide & Crisis Lifeline) or chat at 988lifeline.org. If you are in immediate "
    "danger, call 911 or go to the nearest emergency department. Outside the US, contact your local "
    "emergency number."
)
EMERGENCY_GENERAL = (
    "If symptoms are severe or getting worse, or this feels like an emergency, call 911 (or your local "
    "emergency number) or go to the nearest emergency department."
)

# ---- quote verification ---------------------------------------------------------------------

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[‐-―]", "-", text)
    text = re.sub(r"[\"'`‘’“”]", "", text)
    return re.sub(r"\s+", " ", text).strip(" .,;:")


def quote_supported(quote: str, document_text: str) -> bool:
    """True if the quote appears in the document (ignoring case, spacing and quote marks),
    or nearly so: every number in the quote appears in the document and at least 85% of
    its words do, in a short window. Table spacing and line breaks vary, so exact match
    alone would reject honest quotes."""
    q, d = _norm(quote), _norm(document_text)
    if not q:
        return False
    if q in d:
        return True
    q_words = re.findall(r"[a-z0-9.<>+/-]+", q)
    d_words = re.findall(r"[a-z0-9.<>+/-]+", d)
    if len(q_words) < 2:
        return False
    numbers = [w for w in q_words if re.search(r"\d", w)]
    if any(n not in d_words for n in numbers):
        return False
    d_set = set(d_words)
    return sum(1 for w in q_words if w in d_set) / len(q_words) >= 0.85


# ---- forbidden language ---------------------------------------------------------------------

CANCER = re.compile(r"\b(cancer\w*|malignan\w*|tumou?rs?|carcinoma\w*|oncolog\w*|metasta\w*|lymphoma|leukemia|sarcoma)\b", re.I)
MED_CHANGE = re.compile(
    r"\b(stop|start|discontinue|quit|resume|restart)\s+(taking|using)\b"
    r"|\b(you|he|she|they|patient)\s+should\s+(stop|start|not take|increase|decrease|reduce|switch)\b"
    r"|\b(increase|decrease|reduce|lower|raise|double|halve|adjust|change|switch)\s+(your|the|his|her|their)\s+(dose|dosage|medication|medicine|warfarin|insulin)\b"
    r"|\b(do not|don't|never)\s+take\b",
    re.I,
)
CONDITION = (r"(disease|syndrome|disorder|lupus|anemia|anaemia|cancer|diabetes|failure|infection|deficiency|apnea|celiac|"
             r"pcos|hypothyroidism|hyperthyroidism|hemochromatosis|overload|preeclampsia|ulcer|colitis|crohn'?s)")
DIAGNOSIS = re.compile(
    rf"\byou(?:'ve| have| are suffering from| suffer from)\s+(got\s+)?(an?\s+)?(\w+\s+){{0,3}}{CONDITION}\b"
    r"|\b(diagnosed with|diagnosis of|this confirms|confirms (that|a|an)|this is (a |an )?(clear |classic |definite )?case of)\b"
    rf"|\b(he|she|they|your child) (has|have)\s+(got\s+)?(an?\s+)?(\w+\s+){{0,3}}{CONDITION}\b"
    rf"|\byour (pcos|lupus|celiac disease|hypothyroidism|hyperthyroidism|sleep apnea|hemochromatosis|diabetes)\b",
    re.I,
)
# Odds for an explanation ("a 70% chance", "probability of lupus"). Lab values like "saturation 6%" are fine.
PROBABILITY = re.compile(r"\b\d{1,3}\s*%\s*(chance|likel\w*|probab\w*|certain\w*|sure)\b|\b(odds|probability|likelihood) (of|that|is)\b"
                         r"|\b(very|highly|most) likely (to be|that you have|you have)\b", re.I)
CONDITIONAL = re.compile(r"\b(if|whether|in case|when)\s+[^.;!?]{0,25}$", re.I)


NEGATED = re.compile(r"\b(don'?t|do not|does not|doesn'?t|did not|not|never|can'?t|cannot|won'?t|without|no|isn'?t)\b[^.;!?\n]{0,45}$", re.I)


def _affirmed(pattern: re.Pattern, text: str, *, conditional_ok: bool = False) -> bool:
    """True if the pattern matches somewhere that is not negated ("don't change the
    medication", "does not establish a diagnosis of" are safe). Orders that are negative
    by themselves ("do not take X") always count. With conditional_ok, "ask whether you
    have..." and "if you have..." are safe too (a question, not a statement)."""
    for m in pattern.finditer(text):
        if re.match(r"(do not|don't|never)\s+take", m.group(0), re.I):
            return True
        before = text[max(0, m.start() - 60): m.start()]
        if NEGATED.search(before) or (conditional_ok and CONDITIONAL.search(before)):
            continue
        return True
    return False


def violations(text: str) -> list[str]:
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    found = []
    if CANCER.search(text):
        found.append("cancer_speculation")
    if _affirmed(MED_CHANGE, text):
        found.append("medication_change")
    if _affirmed(DIAGNOSIS, text, conditional_ok=True):
        found.append("diagnosis_language")
    if PROBABILITY.search(text):
        found.append("probability_language")
    return found


# ---- crisis detection ------------------------------------------------------------------------

CRISIS = re.compile(
    r"\b(suicid\w*|kill(ing)? (myself|himself|herself|themselves)|end(ing)? (my|his|her|their) (own )?life|"
    r"take (my|his|her|their) (own )?life|self[- ]harm\w*|hurt(ing)? (myself|himself|herself)|want(s)? to die|"
    r"better off dead|no reason to (live|go on)|don'?t want to (live|be here|wake up)|overdos\w* on purpose|"
    r"cutting (myself|himself|herself))\b",
    re.I,
)
NEGATION = re.compile(r"\b(no|denies|denied|without|negative for|not)\b[^.;\n]{0,40}$", re.I)


def crisis_mentions(text: str) -> list[str]:
    hits = []
    for m in CRISIS.finditer(text):
        before = text[max(0, m.start() - 60): m.start()]
        if NEGATION.search(before):
            continue
        hits.append(text[max(0, m.start() - 40): m.end() + 40].replace("\n", " ").strip())
    return hits


MALIGNANCY_FLAG = (
    "One of your records ({file}) includes a test your doctor ordered to look at more closely, and the result "
    "may still be pending. Please ask your doctor about this result soon."
)


# ---- emergency check on what the user types (no model call, instant) ----------------------

MEDICAL_EMERGENCY = [
    ("chest pain now", re.compile(r"\b(chest|heart)\s+(pain|pressure|tightness|squeez\w*)\b[^.\n]{0,60}\b(now|right now|currently|at the moment|"
                                  r"this (morning|evening|afternoon)|tonight|today|won'?t go away|spreading|crushing|severe)\b"
                                  r"|\b(crushing|severe|sudden)\s+(chest|heart)\s+(pain|pressure)\b", re.I)),
    ("trouble breathing", re.compile(r"\b(can'?t|cannot|struggling to|hard to|unable to)\s+breathe\b|\bgasping\b|"
                                     r"\bshort(ness)? of breath\b[^.\n]{0,30}\b(at rest|now|right now|severe)\b", re.I)),
    ("stroke signs", re.compile(r"\b(face|mouth)\s+(is\s+)?(droop\w*|drooping)\b|\bslurred\s+speech\b|\b(can'?t|cannot)\s+(speak|talk|move (my|his|her) (arm|leg))\b|"
                                r"\b(numb\w*|weak\w*|paraly\w*)\b[^.\n]{0,25}\bone side\b|\bworst headache of (my|his|her|their) life\b", re.I)),
    ("heavy bleeding", re.compile(r"\b(vomit\w*|throw\w* up|cough\w* up)\s+blood\b|\bbleeding (that )?(won'?t|will not|doesn'?t) stop\b|"
                                  r"\b(black|tarry|bloody)\s+(stool|stools|poop)\b[^.\n]{0,40}\b(now|today|right now|dizzy|faint)\b", re.I)),
    ("loss of consciousness or seizure", re.compile(r"\b(passed out|fainted|unconscious|unresponsive|having a seizure|seizing)\b"
                                                     r"[^.\n]{0,30}\b(now|today|just|again)\b", re.I)),
    ("severe allergic reaction", re.compile(r"\b(throat|tongue|lips?)\s+(is |are )?(swelling|swollen|closing)\b|\banaphyla\w*\b", re.I)),
]


def emergency_check(text: str) -> dict:
    """Does what the user wrote describe an emergency right now? Self-harm wins (crisis)."""
    text = text or ""
    crisis = crisis_mentions(text)
    if crisis:
        return {"emergency": True, "kind": "crisis", "matches": ["thoughts of self-harm or suicide"], "message": CRISIS_RESOURCES}
    hits = []
    for label, pattern in MEDICAL_EMERGENCY:
        for m in pattern.finditer(text):
            if not NEGATION.search(text[max(0, m.start() - 60): m.start()]):
                hits.append(label)
                break
    if hits:
        return {"emergency": True, "kind": "medical", "matches": hits,
                "message": "What you describe may need emergency care now. Call 911 (or your local emergency number) "
                           "or go to the nearest emergency department. Do not wait for this app."}
    return {"emergency": False, "kind": None, "matches": [], "message": None}
