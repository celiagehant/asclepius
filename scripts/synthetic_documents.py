"""Text of every synthetic medical document in data/test_cases.

All patients, clinicians, clinics and results here are invented for testing.
`make_test_cases.py` renders each entry to the listed file format:
  txt         plain text file
  pdf         text PDF (text can be extracted locally, no model needed)
  scan_pdf    image-only PDF, like a scanned page (needs vision to read)
  png / jpg   picture of a page, like a portal screenshot or a phone photo

Keep lines under 80 characters so the monospaced renderings fit the page.
"""

BANNER = "SYNTHETIC TEST DOCUMENT - FICTIONAL PATIENT - NOT REAL MEDICAL DATA"

# --------------------------------------------------------------------------------------
# Case 1: adult multi-system. Iron-deficiency anemia from a GI source explains fatigue,
# palpitations, brain fog and digestive symptoms; plus a borderline TSH.
# --------------------------------------------------------------------------------------
CASE1 = [
    (
        "01_primary_care_labs.png",
        """\
RIVERBEND FAMILY MEDICINE - LABORATORY RESULTS
Patient: Dana Whitfield        DOB: 03/12/1984      Sex: F
Collected: 07/08/2026 08:14    Ordering: Laura Chen, MD (Family Medicine)

COMPLETE BLOOD COUNT          RESULT    FLAG   REFERENCE        UNITS
WBC                            6.8              4.0 - 11.0      x10^3/uL
RBC                            4.02             3.90 - 5.20     x10^6/uL
Hemoglobin                     10.1      L      12.0 - 15.5     g/dL
Hematocrit                     32.4      L      36.0 - 46.0     %
MCV                            76        L      80 - 100        fL
MCH                            25.1      L      27.0 - 33.0     pg
RDW                            17.6      H      11.5 - 14.5     %
Platelets                      438       H      150 - 400       x10^3/uL

COMPREHENSIVE METABOLIC PANEL
Sodium                         139              135 - 145       mmol/L
Potassium                      4.1              3.5 - 5.1       mmol/L
Creatinine                     0.8              0.6 - 1.1       mg/dL
Glucose, fasting               88               70 - 99         mg/dL
ALT                            22               7 - 35          U/L
AST                            19               10 - 35         U/L
Albumin                        4.0              3.5 - 5.0       g/dL
Calcium                        9.2              8.6 - 10.3      mg/dL

THYROID / VITAMINS
TSH                            4.9       H      0.4 - 4.5       mIU/L
Free T4                        1.0              0.8 - 1.8       ng/dL
Vitamin B12                    412              200 - 900       pg/mL

Physician comment (L. Chen, 07/10/2026): Mild anemia. TSH slightly high
with normal free T4. Repeat CBC and TSH in 3 months.
""",
    ),
    (
        "02_iron_studies_and_stool_tests.pdf",
        """\
LAKESIDE DIGESTIVE HEALTH - LABORATORY REPORT
Patient: Dana Whitfield        DOB: 03/12/1984      Sex: F
Collected: 08/19/2026          Ordering: Marcus Feld, MD (Gastroenterology)

IRON STUDIES                  RESULT    FLAG   REFERENCE        UNITS
Iron, serum                    28        L      50 - 170        ug/dL
TIBC                           462       H      250 - 450       ug/dL
Transferrin saturation         6         L      15 - 50         %
Ferritin                       6         L      15 - 150        ng/mL

CELIAC SCREEN
tTG-IgA                        <1.0             <4.0 negative   U/mL
Total IgA                      210              70 - 400        mg/dL

STOOL TESTS
Fecal immunochemical test (FIT)     POSITIVE   (reference: negative)
H. pylori stool antigen             POSITIVE   (reference: negative)

Comment: Iron studies consistent with iron deficiency. Celiac screen
negative with normal total IgA. Upper endoscopy scheduled.
""",
    ),
    (
        "03_cardiology_consult.txt",
        """\
HARBORVIEW HEART ASSOCIATES - CARDIOLOGY CONSULTATION
Patient: Dana Whitfield    DOB: 03/12/1984    Date of visit: 07/29/2026
Consultant: Anika Rhodes, MD (Cardiology)
Referred by: Laura Chen, MD, for palpitations

HISTORY
42-year-old woman with 4 months of palpitations, worse climbing stairs,
with fatigue and occasional lightheadedness on standing. No chest pain,
no fainting. Drinks 2 cups of coffee a day. No prior heart history.

VITAL SIGNS
BP 108/68   HR 102 (regular)   SpO2 99% on room air   BMI 23.1

EXAM
Regular rhythm, mildly fast. Soft 2/6 systolic flow murmur at the left
sternal border. Lungs clear. No leg swelling.

TESTS REVIEWED
- ECG today: sinus tachycardia, otherwise normal (separate report).
- 48-hour Holter (07/15-07/17/2026): sinus rhythm throughout. Average HR
  96, maximum 148 with exertion, minimum 68 asleep. Rare isolated PACs
  (<1% of beats). No atrial fibrillation, no sustained arrhythmia.
- Echocardiogram (07/22/2026): normal left ventricular size and function,
  ejection fraction 60%. No significant valve disease. Murmur consistent
  with a benign flow murmur.
- Recent blood counts were not available at the time of this visit.

ASSESSMENT
Palpitations with sinus tachycardia and a structurally normal heart.
No arrhythmia identified.

PLAN
1. Propranolol 10 mg by mouth up to twice daily as needed for palpitations.
2. Reduce caffeine.
3. Return in 6 months, sooner if fainting or chest pain.
""",
    ),
    (
        "04_ecg_report.txt",
        """\
HARBORVIEW HEART ASSOCIATES - 12-LEAD ECG REPORT
Patient: Dana Whitfield    DOB: 03/12/1984    Recorded: 07/29/2026 10:42
Read by: Anika Rhodes, MD (Cardiology)

MEASUREMENTS
Ventricular rate     104 bpm
PR interval          148 ms
QRS duration          86 ms
QT / QTc (Bazett)    330 / 434 ms
Axis                 +52 degrees

INTERPRETATION
Sinus tachycardia. Normal intervals and axis. No ST-segment or T-wave
changes. No signs of chamber enlargement.
Otherwise normal ECG. No prior ECG available for comparison.
""",
    ),
    (
        "05_upper_endoscopy_report.pdf",
        """\
LAKESIDE DIGESTIVE HEALTH - UPPER ENDOSCOPY (EGD) REPORT
Patient: Dana Whitfield        DOB: 03/12/1984
Date of procedure: 09/02/2026  Endoscopist: Marcus Feld, MD

INDICATIONS
Iron-deficiency anemia, positive fecal immunochemical test, 3 months of
upper abdominal discomfort and bloating, daily ibuprofen use for
headaches, positive H. pylori stool antigen.

FINDINGS
Esophagus: normal.
Stomach: patchy redness of the antrum with 5 to 6 small superficial
erosions. One 6 mm clean-based ulcer in the antrum with no active
bleeding and no visible vessel.
Duodenum: normal to the second portion.

BIOPSIES
Gastric antrum and body (H. pylori, histology). Ulcer margin sampled per
standard practice. Duodenal biopsies to exclude celiac disease.
Pathology: PENDING at the time of this report.

IMPRESSION
Antral erosions and a small clean-based gastric ulcer, most likely
related to NSAID use and/or H. pylori infection.

RECOMMENDATIONS
1. Avoid ibuprofen and other NSAIDs.
2. Omeprazole 40 mg daily before breakfast for 8 weeks.
3. Treat H. pylori once pathology is back.
4. Colonoscopy recommended to complete the evaluation of iron deficiency
   and the positive FIT (not yet scheduled).
5. Clinic follow-up to review pathology in 2 to 3 weeks.
""",
    ),
    (
        "06_medication_list.txt",
        """\
PATIENT PORTAL - CURRENT MEDICATIONS (printed 09/10/2026)
Patient: Dana Whitfield    DOB: 03/12/1984
Pharmacy on file: Corner Street Pharmacy

MEDICATION                          DIRECTIONS                     PRESCRIBER
Propranolol 10 mg tablet            1 tab up to twice daily as     A. Rhodes, MD
                                    needed for palpitations        (Cardiology)
                                    Started 07/29/2026
Omeprazole 40 mg capsule            1 cap daily before breakfast   M. Feld, MD
                                    for 8 weeks                    (Gastroenterology)
                                    Started 09/02/2026
Norgestimate/ethinyl estradiol      1 tab daily                    S. Patel, MD
0.25 mg/0.035 mg tablet             Long-term                      (OB/GYN)
Ibuprofen 200 mg tablet (OTC)       2 tabs up to 3 times daily     Self-reported
                                    for headaches                  (over the counter)

Allergies: No known drug allergies.
""",
    ),
]

# --------------------------------------------------------------------------------------
# Case 2: autoimmune pattern. Dermatology, nephrology and hematology each see one piece;
# together they form a multi-system pattern for rheumatology to raise.
# --------------------------------------------------------------------------------------
CASE2 = [
    (
        "01_dermatology_note.txt",
        """\
CLEARVIEW DERMATOLOGY - CLINIC NOTE
Patient: Alicia Moreno    DOB: 05/21/1995    Date of visit: 06/11/2026
Clinician: Helen Brooks, MD (Dermatology)

HISTORY
31-year-old woman with 3 months of redness over both cheeks and the bridge
of the nose, worse after time in the sun. New scaly pink patches on both
upper arms after a beach weekend in May. Reports more hair shedding than
usual. No new skin products.

EXAM
Red patches over the cheeks and nasal bridge, sparing the folds beside the
nose. Several 1-2 cm scaly pink plaques on both outer upper arms. Diffuse
mild hair thinning on the scalp without scarring. Incidental painless
shallow ulcer on the hard palate.

ASSESSMENT
Photosensitive facial eruption. Differential: rosacea, photosensitive
dermatitis, cutaneous lupus.

PLAN
1. 4 mm punch biopsy, left upper arm.
2. Hydrocortisone 2.5% cream to the face twice daily for 2 weeks.
3. Broad-spectrum sunscreen SPF 50 daily; sun avoidance.
4. Follow up with biopsy results.

ADDENDUM 06/25/2026 (H. Brooks, MD)
Biopsy result reviewed with the patient by phone. Arms: start
triamcinolone 0.1% cream twice daily for 2 weeks. Recheck in 3 months.
""",
    ),
    (
        "02_skin_biopsy_pathology.pdf",
        """\
NORTHGATE PATHOLOGY GROUP - SURGICAL PATHOLOGY REPORT
Patient: Alicia Moreno        DOB: 05/21/1995      Sex: F
Specimen received: 06/12/2026 Reported: 06/18/2026
Submitting clinician: Helen Brooks, MD (Dermatology)

SPECIMEN
Skin, left upper arm, 4 mm punch biopsy.

MICROSCOPIC DESCRIPTION
Vacuolar interface change along the dermal-epidermal junction with
scattered apoptotic keratinocytes. Superficial and deep perivascular and
periadnexal lymphocytic infiltrate. Increased dermal mucin on colloidal
iron stain. Mild basement membrane thickening.

DIAGNOSIS
Vacuolar interface dermatitis with superficial and deep perivascular
lymphocytic infiltrate and increased dermal mucin.

COMMENT
These findings can be seen in cutaneous lupus erythematosus or
dermatomyositis. Clinical and serologic correlation is recommended.

Electronically signed: R. Vance, MD (Dermatopathology)
""",
    ),
    (
        "03_nephrology_consult_scanned.pdf",
        """\
CITY KIDNEY CARE - NEPHROLOGY CONSULTATION
Patient: Alicia Moreno    DOB: 05/21/1995    Date: 08/14/2026
Consultant: Omar Haddad, MD (Nephrology)
Referred by primary care for protein and blood on a urine dipstick.

HISTORY: Annual physical in July showed protein and blood in the urine.
No visible blood in urine, no urinary symptoms. Mild ankle puffiness by
evening. Takes over-the-counter naproxen for joint aches a few times a
week. Usual blood pressure in the 110s systolic.

VITALS: BP 136/86 (repeat 134/84)   HR 84   Weight 61 kg

URINALYSIS (08/14/2026)             RESULT        REFERENCE
Protein                             2+            Negative
Blood                               2+            Negative
Red blood cells                     15-20 /hpf    0-2 /hpf
Dysmorphic red cells                Present       Absent
Red cell casts                      Few           None
White blood cells                   0-2 /hpf      0-5 /hpf
Urine protein/creatinine ratio      0.9 g/g       <0.2 g/g

BLOOD (08/14/2026)
Creatinine 0.9 mg/dL (0.6-1.1)   eGFR >90   Potassium 4.2   Albumin 3.6

ASSESSMENT: Glomerular-pattern hematuria with proteinuria below the
nephrotic range; kidney filtration currently preserved.

PLAN: Start lisinopril 5 mg by mouth once daily for protein in the urine
and blood pressure. Renal ultrasound. Repeat urinalysis, protein/creatinine
ratio and potassium in 6-8 weeks. Serologic workup to be discussed at the
follow-up visit (scheduled 10/30/2026). If findings persist, consider
kidney biopsy.
""",
    ),
    (
        "04_hematology_note.txt",
        """\
WESTFIELD HEMATOLOGY - CLINIC NOTE
Patient: Alicia Moreno    DOB: 05/21/1995    Date of visit: 09/03/2026
Clinician: Grace Liu, MD (Hematology)
Referred by primary care for low blood counts.

HISTORY
Low white cells and platelets found on labs in July. Reports fatigue,
aching hand joints, and one episode of low-grade fever in August. No
night sweats, no weight loss, no unusual bleeding.

LABS (09/03/2026)             RESULT    FLAG   REFERENCE        UNITS
WBC                            3.2       L      4.0 - 11.0      x10^3/uL
Absolute neutrophils           2.1              1.5 - 7.5       x10^3/uL
Absolute lymphocytes           0.7       L      1.0 - 4.0       x10^3/uL
Hemoglobin                     11.0      L      12.0 - 15.5     g/dL
MCV                            88               80 - 100        fL
Platelets                      112       L      150 - 400       x10^3/uL
Reticulocytes                  2.6       H      0.5 - 2.5       %
LDH                            262              140 - 280       U/L
ESR                            52        H      0 - 20          mm/hr
B12 / folate                   normal

PERIPHERAL SMEAR
Mild lymphopenia. No blasts. No schistocytes. Platelets mildly decreased
with normal morphology.

ASSESSMENT
Mild decrease in all three cell lines (leukopenia with lymphopenia, mild
normocytic anemia, mild thrombocytopenia). Possibly post-viral. No sign
of a primary bone marrow disorder on the smear.

PLAN
Repeat CBC in 3 months. Bone marrow biopsy only if counts fall further.
Joint pain and fatigue deferred to primary care.
""",
    ),
    (
        "05_medication_list.txt",
        """\
MEDICATION LIST - prepared by patient for appointments (09/10/2026)
Patient: Alicia Moreno    DOB: 05/21/1995

1. Hydrocortisone 2.5% cream - face, twice daily as needed
   Prescribed by Dr. Brooks (dermatology), June 2026
2. Triamcinolone 0.1% cream - arms, twice daily as needed
   Prescribed by Dr. Brooks (dermatology), June 2026
3. Levonorgestrel/ethinyl estradiol 0.15 mg/0.03 mg - 1 tablet daily
   Prescribed by Dr. Okafor (gynecology), for several years
4. Naproxen 220 mg (over the counter) - 1 to 2 tablets, 3-4 times a week
   for joint aches. My own choice, not prescribed.

Allergies: sulfa drugs (rash).
""",
    ),
]

# --------------------------------------------------------------------------------------
# Case 3: pediatric. Labs printed with ADULT reference ranges: kidney values look normal
# but are high for a 7-year-old; alkaline phosphatase and phosphorus look high but are
# normal for a growing child. BP is "normal" for an adult but high for age.
# --------------------------------------------------------------------------------------
CASE3 = [
    (
        "01_urgent_care_visit.txt",
        """\
NORTHSIDE URGENT CARE - VISIT NOTE
Patient: Theo Lindqvist    DOB: 04/02/2019 (7 y)    Visit: 09/20/2026
Clinician: Jordan Kim, PA-C
Accompanied by: father (Erik Lindqvist)

CHIEF COMPLAINT
Headaches for 2 weeks; tired.

HISTORY (per father)
Frontal headaches most mornings for 2 weeks. More tired than usual, less
interested in playing. Drinking a lot of water, waking at night to pass
urine, and two recent bedwetting episodes after being dry for years.
Eating less. No vomiting, no fever, no vision changes, no head injury.

VITAL SIGNS
Temp 36.9 C   HR 92   BP 122/80   RR 20   SpO2 99%
Weight 20.1 kg   Height 116 cm

EXAM
Well appearing, somewhat pale. Neurologic exam normal; no neck stiffness.
Throat and ears normal. Heart and lungs normal.

LABS: Drawn today, see lab report. Alkaline phosphatase and phosphorus
flagged high by the lab; likely normal for a growing child. Hemoglobin
mildly low; suggested iron-rich foods. Kidney function within normal
limits. Urine dilute.

ASSESSMENT
Headache, likely tension-type or viral. Blood pressure within normal
limits.

PLAN
Ibuprofen 200 mg by mouth every 6-8 hours as needed for headache.
Encourage fluids. Follow up with pediatrician if not improved in 1 week.
""",
    ),
    (
        "02_urgent_care_lab_panel.jpg",
        """\
NORTHSIDE REFERENCE LAB - CHEMISTRY AND HEMATOLOGY
Patient: LINDQVIST, THEO     DOB: 04/02/2019    Sex: M
Collected: 09/20/2026 14:05  Ordering: J. Kim, PA-C (Northside Urgent Care)
Reference ranges shown are ADULT ranges.

TEST                     RESULT    FLAG    REFERENCE (ADULT)    UNITS
Sodium                    138               135 - 145           mmol/L
Potassium                 5.0               3.5 - 5.1           mmol/L
Chloride                  106               98 - 107            mmol/L
CO2 (bicarbonate)         21                21 - 31             mmol/L
BUN                       24                7 - 25              mg/dL
Creatinine                0.98              0.70 - 1.30         mg/dL
Glucose                   92                70 - 99             mg/dL
Calcium                   9.4               8.6 - 10.3          mg/dL
Phosphorus                5.4       H       2.5 - 4.5           mg/dL
Alkaline phosphatase      245       H       40 - 130            U/L
Albumin                   4.1               3.5 - 5.0           g/dL

Hemoglobin                11.0      L       13.5 - 17.5         g/dL
Hematocrit                33.1      L       40.0 - 52.0         %
MCV                       84                80 - 100            fL
WBC                       7.4               4.0 - 11.0          x10^3/uL
Platelets                 301               150 - 400           x10^3/uL
""",
    ),
    (
        "03_growth_record.pdf",
        """\
MAPLE GROVE PEDIATRICS - GROWTH AND VITALS RECORD
Patient: Theo Lindqvist       DOB: 04/02/2019      Sex: M
Printed: 09/24/2026           Pediatrician: Nadia Petrov, MD (Pediatrics)

DATE        AGE     HEIGHT    HT %ILE   WEIGHT    WT %ILE   BP
04/2023     4 y     103.0 cm   ~57th    16.5 kg   ~55th     98/58
04/2024     5 y     109.5 cm   ~52nd    18.6 kg   ~55th     100/62
04/2025     6 y     113.0 cm   ~28th    19.6 kg   ~35th     104/64
09/2026*    7 y 5m  116.0 cm   ~6th     20.1 kg   ~8th      122/80

* 09/2026 measurements copied from the Northside Urgent Care visit.
  The 04/2026 well-child visit was missed.

Height gain since age 6: about 2 cm per year (typical for this age:
about 5 to 6 cm per year).

Note from 04/2025 visit (N. Petrov): Height crossing percentiles
downward. Recheck growth at next well visit.

PAST HISTORY ON FILE
Born at 36 weeks. Three urinary tract infections with fever before age 3
(two emergency visits). Kidney ultrasound was recommended in 2022 but not
completed after the family moved.
""",
    ),
    (
        "04_urinalysis.txt",
        """\
NORTHSIDE REFERENCE LAB - URINALYSIS
Patient: LINDQVIST, THEO    DOB: 04/02/2019    Collected: 09/20/2026

TEST                    RESULT          REFERENCE
Color                   Pale yellow     Yellow
Clarity                 Clear           Clear
Specific gravity        1.005           1.005 - 1.030
pH                      6.0             5.0 - 8.0
Protein                 1+   (FLAG)     Negative
Glucose                 Negative        Negative
Ketones                 Negative        Negative
Blood                   Negative        Negative
Leukocyte esterase      Negative        Negative
Nitrite                 Negative        Negative

MICROSCOPY
WBC 0-2 /hpf, RBC 0-1 /hpf, no casts, no bacteria.

Comment: Dilute specimen.
""",
    ),
]

# --------------------------------------------------------------------------------------
# Case 4: polypharmacy. Four prescribers, none with the full list. Duplication: two
# statins. Interaction: warfarin + naproxen (plus self-started aspirin). Overlap: two
# alpha-blockers from two doctors, with dizziness and a fall.
# --------------------------------------------------------------------------------------
CASE4 = [
    (
        "01_primary_care_visit_summary.txt",
        """\
OAKWOOD INTERNAL MEDICINE - VISIT SUMMARY
Patient: Harold Pike    DOB: 02/17/1948    Date of visit: 05/06/2026
Clinician: Robert Alvarez, MD (Internal Medicine, primary care)

PROBLEM LIST
Hypertension. Type 2 diabetes. High cholesterol. Acid reflux (GERD).
Chronic kidney disease, stage 3a. Enlarged prostate (seen by urology).

VITAL SIGNS
BP 132/78 seated   HR 74   Weight 84 kg

RECENT LABS (04/22/2026)
HbA1c 7.1%   Creatinine 1.5 mg/dL   eGFR 47   Potassium 4.8
Hemoglobin 13.4 g/dL   LDL 88 mg/dL

MEDICATIONS PRESCRIBED BY THIS OFFICE
Lisinopril 20 mg - 1 tablet daily (blood pressure)
Doxazosin 4 mg - 1 tablet at bedtime (blood pressure, added 2025)
Simvastatin 40 mg - 1 tablet at bedtime (cholesterol)
Metformin 1000 mg - 1 tablet twice daily (diabetes)
Omeprazole 20 mg - 1 capsule daily (reflux)

PLAN
Continue current medications. Labs and visit in 6 months.
""",
    ),
    (
        "02_cardiology_discharge_summary.pdf",
        """\
ST. BRENDAN REGIONAL HOSPITAL - DISCHARGE SUMMARY
Patient: Harold Pike          DOB: 02/17/1948      Sex: M
Admitted: 06/10/2026          Discharged: 06/14/2026
Attending: Sunita Rao, MD (Cardiology)

REASON FOR ADMISSION
New atrial fibrillation with rapid heart rate (HR 138), shortness of
breath on exertion.

HOSPITAL COURSE
Rate controlled with metoprolol. Echocardiogram: mildly enlarged left
atrium, ejection fraction 55%. Stroke-risk score (CHA2DS2-VASc) 4.
Anticoagulation started with warfarin; INR 2.1 at discharge.
Statin changed to atorvastatin for cardiovascular risk reduction.

HOME MEDICATION HISTORY
Limited: patient unsure of all home medications. Doxazosin and
simvastatin were not reported on admission.

DISCHARGE MEDICATIONS
Warfarin 5 mg daily (dose adjusted by anticoagulation clinic)  NEW
Metoprolol succinate 50 mg daily                               NEW
Atorvastatin 40 mg daily                                       NEW
Lisinopril 20 mg daily                                         continue
Metformin 1000 mg twice daily                                  continue
Omeprazole 20 mg daily                                         continue

FOLLOW-UP
Anticoagulation clinic in 1 week (INR goal 2.0-3.0).
Cardiology clinic in 4 weeks.
""",
    ),
    (
        "03_orthopedics_note.txt",
        """\
SUMMIT ORTHOPEDICS - CLINIC NOTE
Patient: Harold Pike    DOB: 02/17/1948    Date of visit: 08/05/2026
Clinician: Kevin O'Brien, MD (Orthopedic Surgery)

HISTORY
Bilateral knee pain for 2 years, right worse than left, worse on stairs.
Fell 3 weeks ago when getting up at night to use the bathroom; felt
dizzy on standing. Bruised left hip, no fracture on hip X-ray at the
time.

Medications per patient: lisinopril, metformin, "a heart pill" and
"a cholesterol pill". Unsure of names.

KNEE X-RAYS (standing, both knees)
Moderate narrowing of the inner joint space on both sides, right worse.
Bone spurs present. No fracture.

ASSESSMENT
Moderate osteoarthritis of both knees.

PLAN
1. Naproxen 500 mg by mouth twice daily with food for 4 weeks, then as
   needed.
2. Physical therapy referral.
3. Consider a steroid injection if not improved in 6 weeks.
""",
    ),
    (
        "04_urology_note_scanned.jpg",
        """\
RIVERSIDE UROLOGY - CLINIC NOTE
Patient: Harold Pike    DOB: 02/17/1948    Date of visit: 07/15/2026
Clinician: Michael Stein, MD (Urology)

HISTORY
Enlarged prostate with waking 3-4 times a night to urinate and a weak
stream. Previously managed with watchful waiting.
Current medications per patient: lisinopril, metformin, warfarin.

EXAM
Smoothly enlarged prostate, no nodules.

TESTS
PSA 3.1 ng/mL (stable compared with 2.9 in 2025).
Post-void residual by bladder scan: 90 mL.

ASSESSMENT
Benign prostatic enlargement with nighttime urination.

PLAN
Start tamsulosin 0.4 mg once daily, 30 minutes after the same meal each
day. Return in 3 months.
""",
    ),
    (
        "05_lab_panel.pdf",
        """\
OAKWOOD INTERNAL MEDICINE - LABORATORY RESULTS
Patient: Harold Pike          DOB: 02/17/1948      Sex: M
Collected: 09/08/2026         Ordering: Anticoagulation clinic / R. Alvarez, MD

TEST                          RESULT    FLAG   REFERENCE        UNITS
INR                            3.9       H      2.0 - 3.0 (goal) ratio
Hemoglobin                     11.9      L      13.5 - 17.5     g/dL
Platelets                      214              150 - 400       x10^3/uL
Creatinine                     1.7       H      0.7 - 1.3       mg/dL
eGFR                           40        L      >60             mL/min/1.73m2
Potassium                      5.3       H      3.5 - 5.1       mmol/L
Sodium                         137              135 - 145       mmol/L
HbA1c                          7.0       H      <5.7            %
ALT                            28               7 - 55          U/L
AST                            31               8 - 48          U/L
Creatine kinase (CK)           236       H      40 - 200        U/L
LDL cholesterol                58               <100            mg/dL

Previous (04/22/2026): Hemoglobin 13.4, creatinine 1.5, eGFR 47,
potassium 4.8.
""",
    ),
]

CASES = {
    "case1_adult_multisystem": CASE1,
    "case2_autoimmune_pattern": CASE2,
    "case3_pediatric_ranges": CASE3,
    "case4_polypharmacy": CASE4,
}
