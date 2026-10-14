# Tokenomics findings

These findings interpret [report.md](report.md), which holds 16 real runs: four synthetic
cases under four settings, all on 2026-10-14 with fresh intake calls. Every model call is
in `usage_log.jsonl`.

## 1. A typical case costs about 1.3 cents

The production design (caching on, summaries passed between agents, targeted round 2)
averaged **$0.0128 per case**. That bought about 91k input tokens (65% read from the cache),
17k output tokens and about 18 model calls.

Where the money goes in a case, on average:
- intake: $0.0027
- each specialist: $0.0007–0.0021
- coordinator: $0.0018
- pharmacist: $0.0014
- safety reviewer: $0.0004

Output tokens are 15% of the tokens but about 65% of the cost, because output is priced 5×
higher than input.

## 2. Prompt caching cuts the cost by more than a third

With a unique random string opening every request, the runs read **0 cached tokens**, as
required. The same work then cost **$0.0203 per case, 58% more**. Equivalently, caching
saves **37%**. Two things combine here:
- Without caching, every input token is billed at the full price.
- Each request is also billed as a cache write, at 1.25× the input price.

Caching works because the design puts the long, stable text first in every request. All
specialists share one base prompt, and each chat answer starts with the same case context,
so later calls read most of their input at a tenth of the price.

## 3. Passing summaries instead of full documents saves tokens, not money

When the hand-offs also carried the full documents, input rose **7.6%** (90.7k → 97.6k
tokens per case). The hand-offs are the round-2 peers, the pharmacist and the coordinator.

The cost did not rise: it was −4%, within run-to-run noise. The added documents repeat in
every agent's request, so caching absorbs most of them (cached input went from 59k to 71k).
Quality did not change measurably either: the judge scored 74% vs 69%, and keyword coverage
was 81% vs 80%.

**Conclusion:** at four to six short documents per case, summaries buy little. They keep
prompts shorter and agents focused, and their value would grow with longer records (more
pages per document, more documents). This is honestly a smaller effect than expected.

## 4. Targeted round 2 halves the conference cost without hurting quality

Letting every specialist read every other report raised the number of peer reports read in
round 2 from 24 to 64 across the four cases. Round-2 cost rose:
- **+14% to +118% per case**
- from $0.0085 to $0.0133 in total across the four cases, about +56%

The whole case cost rose **7%**, because round 2 is only one part of a case. Quality was
within noise: 72% vs 69% (judge), 77% vs 80% (keywords).

The targeting rule keeps round-2 reads growing with the size of the panel instead of its
square. This matters more on larger panels. With 5 specialists, all-to-all means 20 reads,
while targeting with at most 3 peers each means at most 15. Case 3 shows the gap
(2 reads vs 12).

## 5. How much to trust the quality numbers

Each setting ran once per case, so treat quality differences under about ±8 points as
noise. The evidence for that: caching on and caching off run the same design, and still
differ by 6 points on the judge.

The judge (gpt-6-luna, two independent passes averaged) is strict. It marks a finding
missing unless the summary names it, and it found **no "must not" violations** in any of
the 16 summaries.

Keyword coverage is cruder but deterministic. Both measures agree that no cost-saving
setting made the summaries worse.

## 6. At scale

Assume a user reviews 2 cases a month and asks 15 chat questions, at a measured
$0.0011 per question:

| | Model cost per month |
|---|---|
| Per user | $0.042 |
| 100 users | $4.22 |
| 10,000 users | $422 |

The per-user daily budget ($0.50) and per-run budget ($0.05) cap the worst case.

## 7. Notes on measurement

- **Latency was high that day.** The provider took 4–8 minutes per case, against 1–3
  minutes on 2026-10-13, so the times in the report reflect the provider more than the
  design.
- **Retries and caching.** A request retried after a timeout is re-sent byte for byte, and
  can be served from the cache the first attempt created. That makes "caching off" hard to
  measure. The app now retries with a fresh random string, and discards any response that
  still reports cached tokens. In production, the same effect makes retries cheaper.
