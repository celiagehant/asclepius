# Synthetic test cases

Every patient, clinician, clinic and result in this folder is **invented**, and each
document carries a "SYNTHETIC TEST DOCUMENT" banner. `expected.json` is the answer key
used to score the panel. It is never shown to the agents.

| Case | Patient | Mode | Documents | What it tests |
|---|---|---|---|---|
| `case1_adult_multisystem` | Dana Whitfield, 42 F | adult | 6 (PNG, 2 PDF, 3 text) | Fatigue, palpitations, brain fog and stomach symptoms are explained by iron-deficiency anemia with a likely GI blood-loss source (positive FIT, gastric ulcer, daily ibuprofen, H. pylori). Cardiology never saw the blood count. Also tests a borderline TSH, a colonoscopy that was never scheduled, and a pending ulcer biopsy that needs a calm red flag with no cancer speculation. |
| `case2_autoimmune_pattern` | Alicia Moreno, 31 F | adult | 5 (scanned PDF, PDF, 3 text) | Dermatology (an interface dermatitis biopsy), nephrology (glomerular hematuria with proteinuria) and hematology (cytopenias, high ESR) each see one piece. Together with joint pain, mouth ulcers and photosensitivity, they form a multi-system pattern for rheumatology to raise, along with tests to ask about. The panel must not diagnose lupus. |
| `case3_pediatric_ranges` | Theo Lindqvist, 7 M | **pediatric** | 4 (JPG, PDF, 2 text) | The lab printed **adult** reference ranges. Creatinine 0.98 and BUN 24 look normal but are high for a 7-year-old (bedside Schwartz eGFR about 49), and BP 122/80 is high for his age. Alkaline phosphatase and phosphorus are flagged high but are normal for a growing child. Also tests slowing growth, past febrile UTIs and daily ibuprofen. |
| `case4_polypharmacy` | Harold Pike, 78 M | adult | 5 (JPG, 2 PDF, 2 text) | Four prescribers, none with the full list. **Duplication:** simvastatin plus atorvastatin. **Interaction:** warfarin with naproxen and self-started aspirin, with INR 3.9 and bruising. **Overlap:** doxazosin plus tamsulosin (both alpha-blockers), with dizziness and a fall. Also tests metformin at eGFR 40 and diphenhydramine in an older adult. The panel must not tell him to stop or change any medicine. |

| `case5_acne_weight` | Maya Lindqvist, 24 F | adult | 3 (text) | Dermatology (jawline acne, hirsutism, darkened skin folds), primary care (prediabetes-range A1c and fasting glucose, high insulin and testosterone, high triglycerides, low HDL) and gynecology (periods every 60–90 days, many small ovarian follicles) each treat one piece. The panel should connect them as a pattern to discuss (PCOS-like, with a metabolic side) without diagnosing, and chat should explain "why are my acne and my weight related?". Hand-written; added with the four-round conference. |

## Document formats

| Format | How the app will read it |
|---|---|
| `.txt` | read directly |
| text `.pdf` | text extracted locally with `pypdf` (no model call) |
| `*_scanned.pdf` | image-only PDF with no text layer; transcribed once by gpt-6-luna vision |
| `.png` / `.jpg` | transcribed once by gpt-6-luna vision |

Regenerate the documents after editing `scripts/synthetic_documents.py`:

```bash
.venv/bin/python scripts/make_test_cases.py
```
