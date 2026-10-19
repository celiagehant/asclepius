# Panel upgrade: draft spec for review

Status: **built** (2026-10-14). **Update 2026-10-18:** at the user's request the separate skeptic
agent was removed; the case coordinator now challenges every candidate in round 3 (same rules:
simpler explanations, unsupported posts, keep / weaken / drop), and adds the alternatives in chat
connection answers. Read "skeptic" below as "the coordinator's challenge".

Goal: the panel works as a team. It connects findings across specialties, proposes
possible explanations, challenges them, and gives practical next steps. It is still never
a diagnosis.

## 0. The framing line (how "possible explanations" stays inside "does not diagnose")

The project's non-negotiable rule is "The app does not diagnose and does not prescribe."
Explanation cards come closer to that line than anything we have now, so these rules apply
everywhere: prompts, code checks, safety reviewer and UI.

- A card describes a **pattern doctors consider**, never a label applied to the patient.
  - Allowed: "Low iron from slow blood loss in the gut is a pattern that could connect your
    tiredness, racing heart and low ferritin."
  - Not allowed: "You have iron-deficiency anemia," "This is…," "confirms," "diagnosed with."
- Every card carries the fixed label **"Possible explanation to discuss with your doctor,
  not a diagnosis."** The UI renders it from the card data, so the check is real.
- Every card shows **what argues against it**, so no card is one-sided.
- **No percentages or probabilities.** Strength is "stronger match / possible match /
  weaker match", computed in code from the debate (section 3), not stated by a model.
  Model-stated percentages are uncalibrated and read like a diagnosis.
- **No cancer patterns.** The no-oncology rule stays. A record that mentions a mass, biopsy
  or pending pathology still gets only the calm "ask your doctor soon" red flag.
- Recommendations are **"ask about," "bring up," "see first."** Never "get this test" as an
  order, never a medication change.

## 1. Shared case board

After round 1, every finding becomes a one-line post on a board that every panel agent reads.

**Recommendation:** build the board in code from the validated findings instead of asking
agents to write separate posts.
- Each `Finding` gets three new fields:
  - `board_line`: at most 15 words.
  - `system`: one tag from a fixed list.
  - `symptoms`: up to 3 short lowercase tags, such as "fatigue" or "palpitations".
- Posts therefore inherit the quote check. A finding that fails verification never
  reaches the board, and no extra model call is needed.

- **Post format** (about 25 tokens each):
  `cardiology.F2 | cardiovascular | palpitations, fatigue | Resting heart rate 112 on ECG | abnormal | heart`
- **System tags (fixed list):** cardiovascular, respiratory, digestive, liver, kidney_urinary,
  endocrine_metabolic, blood, immune_joints, nervous_system, mental_health, skin,
  musculoskeletal, reproductive, eyes, ear_nose_throat, medication, lifestyle, general.
- **Who posts:**
  - Every active specialist posts its findings.
  - The pharmacist posts its issues, tagged `medication`.
  - The lifestyle agent posts lifestyle facts, tagged `lifestyle`.
  - Intake posts abnormal labs that no specialist covered, tagged by system, `intake.L1`.
- **Size:** at most 6 posts per specialist and about 40 in total. At most 5 specialists
  plus the pharmacist and lifestyle agent keeps the board under about 1,000 tokens.
- **Normalizing symptom tags:** code lowercases them and merges simple plurals. The UI
  filters on them, and chat routing uses them (section 8).
- **Live feed:** a `board_post` event is emitted for each post.

## 2. Pattern library (data, in the cached prompt)

- **Format:** `backend/patterns/patterns.json`, about 25 entries.
- **Fields per entry:**
  - `id`
  - `name`: plain language.
  - `systems`: the system tags involved.
  - `clues`: typical symptom tags and lab or record clues.
  - `specialties`: who usually considers it.
  - `often_confused_with`: alternatives the skeptic should raise.
  - `what_doctors_may_check`: written as things to *ask about*.
  - `age_or_pregnancy_notes`
  - `source`: one MedlinePlus or NIH link. **I check every link before it ships.**
- **Placement:** rendered as a compact block right after the shared base prompt, so it sits
  in the cached prefix every panel agent shares. About 2,500 tokens, written to cache once
  and then billed at the cached rate ($0.01 per 1M tokens).
- **The prompt says:** "a starting point, not a limit." Agents may propose an explanation
  that is not in the library. Such a card is marked `panel-proposed` and gets extra
  skeptic scrutiny.
- **Draft list (names only; you can add or remove):**

| Systems | Pattern |
|---|---|
| blood + digestive + heart | Iron loss from slow bleeding in the gut (NSAID or anticoagulant use as clues) |
| blood + nervous system + digestive | Low vitamin B12 (clues: metformin or acid-reducer use, numbness, anemia) |
| blood + digestive + skin | Celiac disease (anemia, gut symptoms, rash, fatigue) |
| endocrine + heart + mental health | Overactive thyroid (racing heart, weight loss, anxiety, tremor) |
| endocrine + mental health + skin | Underactive thyroid (tiredness, weight gain, dry skin, low mood, cholesterol) |
| endocrine + skin + reproductive | Polycystic ovary syndrome (acne, weight, irregular periods, blood sugar) |
| endocrine + heart + kidney | Metabolic syndrome (weight, blood pressure, glucose, lipids) |
| endocrine + skin + heart | Cortisol excess (weight, acne, blood pressure, glucose, easy bruising) |
| endocrine (child) | New high blood sugar in a child (thirst, bedwetting, weight loss): urgent |
| immune + kidney + blood + skin | Lupus-like autoimmune pattern (rash, kidney results, low blood counts, joints) |
| immune + digestive + skin + eyes | Inflammatory bowel disease with joint, skin or eye involvement |
| kidney + blood | Kidney disease with anemia |
| kidney + medication | Kidney strain from NSAIDs, especially with blood-pressure medicines |
| heart + lungs + kidney | Fluid overload / heart failure pattern (swelling, breathlessness, kidney results) |
| heart + nervous system + respiratory | Sleep apnea (tiredness, high blood pressure, irregular rhythm, morning headaches) |
| medication + nervous system | Medication cascade or duplication in older adults (dizziness, falls, confusion) |
| medication + heart + nervous system | Low blood pressure on standing (dizziness, falls, several blood-pressure drugs) |
| medication + blood | Anticoagulant effect too strong (bruising, high INR, interacting medicines) |
| medication + digestive | NSAID or aspirin irritation of the stomach (pain, dark stools, anemia) |
| liver + endocrine + joints + skin | Iron overload (liver results, diabetes, joint pain, skin color) |
| mental health + many systems | Depression or anxiety with body symptoms (fatigue, palpitations, gut, sleep) |
| general + lifestyle | Dehydration (dizziness, kidney results, low blood pressure) |
| reproductive + blood + heart | Anemia in pregnancy (pregnancy mode) |
| reproductive + kidney + nervous system | High blood pressure in pregnancy with headache or vision change (pregnancy mode): urgent |
| infection + immune + nervous system | Post-infection fatigue (fatigue after a viral illness, sleep, concentration) |

## 3. The four rounds

The hard stop stays: no round repeats, and each round has a fixed agent count and token cap.

### Round 1: Independent review (existing round, extended)
- **Who:**
  - Active specialists (cap 5, unchanged), each reading only its own documents
    (`documents_for` scoping unchanged).
  - The pharmacist (unchanged).
  - **New:** the lifestyle agent, first call (section 4).
- **Output:** the existing report, plus `board_line`, `system` and `symptoms` on each finding.
- **Then:** code builds the board and emits a `board_post` for each line.

### Round 2: Connection round
- **Who:** every specialist who posted at least one abnormal or borderline finding, in parallel,
  with no tools.
- **Reads:**
  - The pattern library and the **whole board**. Both sit in the cached prefix, so the
    parallel calls share it.
  - The agent's own round-1 report and the questions addressed to it.
  - Peer reports are no longer passed. The board replaces them, which is cheaper.
- **Output, up to 2 proposed connections per specialist:**
  - `title`: pattern phrasing, as in section 0.
  - `board_refs`: at least 2 posts covering at least 2 systems. They should come from at
    least 2 specialties, or from 1 specialty plus the pharmacist or intake.
  - `pattern_id`: a library id, or `panel-proposed`.
  - `why_it_fits`: 1–3 bullets, each tied to refs.
  - `would_help_tell`: 1–2 things to ask about that would support it or rule it out.
  - Also: answers to questions addressed to the specialist.
- **Code merges** cards whose ref sets overlap by at least half, plus same-pattern cards, into
  candidates C1…Cn. It records who proposed each one and drops cards whose refs do not
  exist. At most 6 candidates go to round 3, ranked by number of proposers and then by
  abnormal refs.
- **UI:** a `connection` event draws a glowing thread between the involved doctor cards.

### Round 3: Debate with a skeptic
- **3a. Skeptic** (new agent, 1 call, no tools, no patient documents):
  - Reads the board, the candidates and the pharmacist issues.
  - For each candidate it challenges the card:
    - **Simpler explanations:** medication effect, normal variation, age-specific ranges, a
      lab or timing artifact, lifestyle, coincidence.
    - **Refs that don't support the claim**, and **what is missing.**
  - It gives a verdict: `keep`, `weaken` or `drop`, with a reason.
  - It may propose 1 alternative candidate of its own, which must cite board refs.
- **3b. Panel response** (one short call per specialist involved in any candidate, in
  parallel, no tools):
  - Each specialist answers the skeptic on the cards it proposed: `defend` or `concede`,
    with a reason and refs.
  - It may also `support` or `challenge` any other candidate where its specialty has
    something to say.
- **Scoring in code, not by a model:**
  - Points: +1 per proposer, +1 per support, −1 per challenge, −1 for a skeptic `weaken`.
  - A skeptic `drop` that the proposer concedes removes the card.
  - The score maps to stronger, possible or weaker match.
  - The top 3 go to round 4. If fewer than 2 survive, the summary says so honestly and does
    not pad the list.
- **UI:** a `challenge` event draws an **amber** thread from the challenger to the card's
  doctors. A `support` event brightens the existing thread.

### Round 4: Recommendations
- **Lifestyle agent, second call:**
  - Writes the self-care steps (section 4).
  - Runs **in parallel with round 3**, because it needs the board and red flags, not the
    debate. This saves about 15 seconds.
- **Coordinator:** builds the new summary (section 5) from:
  - the board
  - the top-3 cards with the debate record
  - pharmacist issues
  - the lifestyle steps
  - red flags and concerns
  - consider-seeing
- **Then:** the safety reviewer (section 6), the code safety pass and the emergency logic,
  all unchanged in role.

The optional consult stays where it is (between rounds 1 and 2), and its findings join the board.

### Cost and time estimate (to be measured, not promised)

| | Now | After (estimate) |
|---|---|---|
| Model calls per case | about 10–12 | about 16–20 |
| Cost per case | $0.0128 (measured) | about $0.018–0.024 |
| Time | about 70 s | about 90–110 s |

- **Budgets unchanged:** $0.05 per run, $0.30 per user per day on the public site, $3 global.
- **New per-agent reservations:** round 3 and lifestyle get their own, so `can_start` still
  stops cleanly when the budget runs out.
- **Token logging:** every call keeps its own entry in the usage log, Run details and the
  spend meter. New members: `skeptic`, `lifestyle`.

## 4. Lifestyle and prevention agent (always on)

- **Status:** always on, outside the cap of 5. It is an "AI specialist agent" like the others.
- **Reads:**
  - The questionnaire, the board, red flags, pharmacist issues and the modes (age,
    pregnancy).
  - **No raw documents.** It reads the questionnaire, so it holds no action tools (design
    layer) and gets only the `search_medlineplus` tool.
- **First call (round 1):** posts lifestyle facts from the questionnaire and intake, such as
  "drinks 4 coffees a day" or "sleeps 5 hours". At most 3 posts, no tools, about $0.0005.
- **Second call (round 4):** writes up to 5 self-care steps.

### Rules for self-care steps

1. **Low-risk and widely recommended only.**
   - Categories, as a fixed list: sleep, activity, eating_pattern, hydration,
     symptom_tracking, stress, avoid_known_trigger, visit_preparation.
   - Every step is something a public-health source recommends to most people.
2. **Every step cites a source returned by MedlinePlus in this run.** Code checks the URL
   against the tool results, exactly like specialist sources. No source, no step.
3. **Nothing about medications or supplements.**
   - No starting, stopping, timing or dosing of any medicine, vitamin, supplement or
     herbal product. Medication items belong to the pharmacist.
   - **Code check (structural, not a keyword filter):** a step may not name any medication
     on the intake list or the pharmacist's combined list, and may not contain a dose (a
     number followed by mg, mcg, IU or units).
4. **No diets, fasting, detoxes, weight targets or calorie numbers.**
   - Eating advice stays general, such as "regular meals" or "keep a food and symptom diary".
   - **Never weight-loss advice for anyone under 18.**
5. **Checked against the patient's own context:**
   - No exercise step when there are falls, dizziness, chest pain, a cardiac red flag or
     pregnancy, unless it is phrased "ask your doctor what activity is safe for you."
   - No fluid-increase step when kidney, heart or swelling findings exist.
   - No salt or potassium advice when there are kidney findings.
   - Each step has a `check_first_if` field naming the condition under which the patient
     should ask a doctor first.
6. **Care first.** If any red flag is urgent and present now, the section shows only "Get
   the care described above first" and no steps.
7. **Plain and practical.** One action, the reason it may help (tied to board refs), and
   how to track it. Never framed as treating a condition.

## 5. New summary layout (what the patient sees, in this order)

1. **Emergency banner** if active (unchanged, always on top).
2. **Top 3 possible explanation cards.** Each card shows:
   - the title and the fixed "not a diagnosis" label
   - strength (stronger, possible or weaker match)
   - why it fits, with links to board posts
   - what argues against it (from the skeptic)
   - what could help tell (things to ask about)
   - the specialists involved
   - a source link
   - body regions, derived in code from the referenced findings, never from the model
3. **Who to see first:**
   - An ordered list of up to 3 entries: specialty or named doctor, why, how soon, and which
     card it relates to.
   - Red flags override the order.
4. **What you can do now:** the lifestyle steps with sources, or the care-first message.
5. **Questions for each doctor** (existing, now tied to cards).
6. **Medication items to discuss with prescribers** (existing pharmacist items).
7. Below the fold, unchanged: red flags, key findings, limitations, the plain-language
   summary, and the full board.

Schema: `CaseSummaryOutput` gains `explanations` (top 3), `see_first` and `self_care`. The
old `connections` list is replaced by the cards. Every item keeps `finding_refs`, so
`validate_summary` still drops anything unsupported.

## 6. Safety reviewer and code checks

**Allowed:** possible explanations written as patterns to discuss.

**Blocked, by both the reviewer prompt and code:**

| Problem | Model reviewer | Code check |
|---|---|---|
| "You have / this is / confirms / diagnosed with" applied to the patient | rewrite as pattern | existing negation-aware check, extended to the card fields |
| Card missing the "not a diagnosis" label | n/a | label restored from the constant; the event is logged |
| Card with no "argues against" | rewrite or remove | the card is not shown until the field is non-empty |
| Self-care step breaking rules 1–6 | rewrite or remove (new problem types) | rules 2, 3 and 6 checked structurally |
| Cancer speculation, medication change, unsourced claim | unchanged | unchanged |

New `SafetyEdit.problem` values: `diagnosis_language`, `missing_label`, `unsafe_self_care`.

## 7. UI

- **Threads:**
  - Glowing teal SVG curves link doctor cards in the arc when a connection is proposed.
  - **Amber dashed** curves show a challenge.
  - A support brightens the existing curve.
  - In replay, threads appear in event order.
- **Live case board feed:**
  - A scrolling list beside the arc: system chip, symptom tags, the line, who posted it.
  - Filter by system.
  - Clicking a post highlights the doctor and the body region.
- **Explanation cards:**
  - Hovering or clicking a card pulses its regions on the 3D body and lights its board posts.
  - Clicking a body region highlights the cards that involve it.
  - The 2D fallback gets the same links.

## 8. Chat: explaining connections

- **Router:** gets a new route type, `connection`, for "why are X and Y related?" questions.
  It matches X and Y to board symptom tags and cards.
- **Who answers:** the specialists whose posts carry those tags (at most 2) plus the skeptic.
  - Specialists explain the link in their own voice, citing board refs and the pattern
    library.
  - The skeptic adds what else could explain it.
  - Wrap-up and safety review are unchanged.
- **If X and Y have no board link,** the panel says so plainly rather than inventing one.
- **Budget:** the per-question budget stays $0.03. A connection question costs about
  $0.002–0.003.

## 9. Build order and tests (each step tested on the 4 test cases before the next)

| Step | Build | Test on the 4 cases | Est. spend |
|---|---|---|---|
| 1 | Board fields, board builder, `board_post` events | the board has tagged posts and no unverified lines | $0.05 |
| 2 | Pattern library + cached placement | cache reads on parallel calls; links checked | $0.02 |
| 3 | Rounds 2–3 (connection, skeptic, response, scoring) | sensible candidates per case; the skeptic catches a weak one | $0.10 |
| 4 | Lifestyle agent + rules | steps cite sources; case 4 (falls) gets no exercise step; case 3 (child) gets no weight advice | $0.06 |
| 5 | New summary + coordinator | top-3 cards, see-first, refs valid | $0.10 |
| 6 | Safety reviewer + code checks | offline tests for each blocked pattern, plus planted bad cards | $0.03 |
| 7 | UI (threads, feed, cards ↔ body) | headless-browser screenshots of a replayed run | $0 |
| 8 | Chat connections | "why are my acne and my weight related?" on a case with both | $0.02 |
| 9 | Regression | 48 offline tests plus new ones; re-run the safety suite (defenses off/on) and the cost comparison so the report numbers match the new panel | about $0.60 |

Total test spend is about $1.00 on the course key.

**Expected results per test case:**
- **Case 1** (fatigue, racing heart, gut): iron loss from the gut, with NSAID use as a clue.
- **Case 2** (rash, kidney, low counts): the lupus-like autoimmune pattern, with the skeptic
  raising NSAID kidney strain.
- **Case 3** (child: thirst, bedwetting): new high blood sugar in a child, which is urgent.
- **Case 4** (polypharmacy): duplication, low blood pressure on standing, and a strong
  anticoagulant effect.
