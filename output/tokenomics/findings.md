# Tokenomics: findings (four-round conference)

These findings interpret [report.md](report.md): 8 full panel runs on 2026-10-18 (cases 1–4,
caching on and off), every run with fresh intake calls. The earlier two-round panel's
measurements, including the full-documents and round-2 comparisons, are kept in
[earlier_two_round_panel/](earlier_two_round_panel/findings.md).

## Results

| | Two-round panel (2026-10-14) | Four-round conference (2026-10-18) |
|---|---|---|
| Cost per case, caching on | $0.0128 | **$0.0192** (+50%) |
| Cost per case, caching off | $0.0203 | $0.0408 |
| Saving from caching | 37% | **53%** |
| Model calls per case | 18.5 | 27 |
| Share of input read from cache | 65% | 74% |
| Quality: keyword coverage / judge / usefulness (1–5) | 80% / 69% / 4.25 | 89% / 69% / 4.4 |
| Must-not violations (8 summaries) | 0 | 1 (see below) |

## What this shows

**1. The team conference costs about half as much again, not double.** Seven to nine more
model calls per case (the connection round, the coordinator's challenge, the panel response
and two lifestyle calls) add about $0.006. That stays well inside the $0.05 run budget, and
it buys the explanation cards, the debate and the self-care steps.

**2. Caching matters more than before (53% saved, up from 37%).** Three design choices put
most of the new prompt text into prefixes that many calls share:
- the pattern library opens every panel agent's instructions (about 3,700 tokens)
- the case board comes first in every round-2 and round-3 message
- one specialist prompt serves rounds 1–3

With caching off, every one of those tokens is billed at the cache-write price instead.
The check passed: 0 cached tokens across the caching-off runs, with no discarded responses
and no gateway retries.

**3. Quality held or improved slightly.** Keyword coverage rose from 80% to 89%. The judge's
score stayed at 69%, and usefulness rose from 4.25 to 4.4. The judge mostly marks down
details it expected but did not see named; for example, "cardiology lacked the blood count"
in case 1.

**4. One possible must-not violation.** In case 1 (caching on), one of the judge's two
scoring passes flagged "state a diagnosis as fact"; the other did not. The wording
describes the lab results directly ("your blood count and iron tests show anemia with small
red cells", "iron deficiency") rather than an explanation pattern. That is borderline:
"anemia" names what the blood count shows, and it never says "you have". The earlier panel
had no flags.

A possible tightening, not made, so the measured code stays the code that was measured:
ask the agents to describe values ("low hemoglobin, very low ferritin") instead of
condition names unless quoting a record.

## Projection (production design)

At $0.0192 per case and about $0.002 per chat question, a user who reviews 2 cases a month
and asks 15 questions costs about $0.068 a month: $6.80 for 100 users, about $680 for
10,000 users. On the public demo's limit of $0.30 per user per day, that is about 15 case
reviews a day.
