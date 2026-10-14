"""Run the intake agent on demo cases and print the routing table.

    .venv/bin/python scripts/run_intake.py --all
    .venv/bin/python scripts/run_intake.py case1 case3
    .venv/bin/python scripts/run_intake.py case1 --add data/attack_samples/hidden_text_lab_report.pdf
    .venv/bin/python scripts/run_intake.py --all --no-cache     # fresh model calls (measures real tokens)

Each run is saved to output/intake/<case>.json (with --add: <case>+attack.json); runs that
used the per-document cache are saved as <case>.cached.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402
from backend.intake import run_intake  # noqa: E402
from backend.schemas import IntakeResult, Questionnaire  # noqa: E402

OUT_DIR = ROOT / "output" / "intake"
WIDTH = 124


def rule(title: str = "", ch: str = "-") -> str:
    return f"{ch * 3} {title} {ch * (WIDTH - len(title) - 5)}" if title else ch * WIDTH


def table(rows: list[list[str]], headers: list[str], widths: list[int]) -> str:
    def fmt(cells: list[str]) -> list[str]:
        wrapped = [textwrap.wrap(c or "-", w) or ["-"] for c, w in zip(cells, widths)]
        height = max(len(w) for w in wrapped)
        return ["  ".join((w[i] if i < len(w) else "").ljust(width) for w, width in zip(wrapped, widths)).rstrip()
                for i in range(height)]
    lines = fmt(headers) + ["  ".join("-" * w for w in widths)]
    for r in rows:
        lines += fmt(r)
    return "\n".join(lines)


def short(name: str) -> str:
    return name.rsplit(".", 1)[0][:32]


def print_result(res: IntakeResult, q: Questionnaire, seconds: float) -> None:
    m, p = res.modes, q.patient
    print()
    print(rule(f"{res.case_label}: {p.name}, {m.age_years:g} y, {p.sex_at_birth}", "="))
    print(f"Mode: {m.age_group}{' + pregnancy' if m.pregnancy else ''} | Coordinator: {m.coordinator_name} | "
          f"Clinical pharmacist: {'ON' if m.pharmacist_active else 'off'} | "
          f"Active specialists: {len(res.active_specialists)}/5")
    print(f"Main concern: {textwrap.shorten(q.main_concern, 100)}")

    print("\n" + rule("DOCUMENTS"))
    rows = []
    for d in res.documents:
        e = d.extraction
        rows.append([short(d.filename), d.read_by, e.doc_type if e else "ERROR", (e.date if e else "") or "?",
                     ", ".join(e.specialties) if e else "", e.summary if e else (d.error or "")])
    print(table(rows, ["file", "read by", "type", "date", "specialties (from document)", "summary"], [32, 6, 17, 10, 22, 27]))

    print("\n" + rule("ROUTING TABLE: ACTIVE PANEL"))
    rows = [[m.coordinator_name + " (coordinator)", "-", "always", "all summaries", "Leads the case."]]
    if m.pharmacist_active:
        rows.append(["Clinical pharmacist", "-", "medications", "all medications", "Patient takes medications."])
    for a in res.active_specialists:
        rows.append([a.name, str(a.relevance), a.why_active, ", ".join(short(x) for x in a.documents) or "(symptoms only)",
                     a.reason])
    print(table(rows, ["specialist", "rel", "why", "documents it reads", "reason"], [26, 3, 18, 34, 31]))
    if res.consider_seeing:
        print("\nConsider seeing (over the cap of 5): " + "; ".join(f"{c.name}: {c.reason}" for c in res.consider_seeing))
    if res.unassigned_documents:
        print("Read by the coordinator only: " + ", ".join(res.unassigned_documents))

    if res.conflicts:
        print("\n" + rule("CONFIRM WITH THE USER (not guessed)"))
        for c in res.conflicts:
            print(textwrap.fill(f"[{c.kind}] {c.message}", WIDTH, subsequent_indent="    "))
    if res.safety_signals:
        print("\n" + rule("SAFETY SIGNALS"))
        for s in res.safety_signals:
            print(textwrap.fill(s, WIDTH, subsequent_indent="    "))
        for d in res.documents:
            for f in d.hidden_text:
                print(textwrap.fill(f"  dropped from {d.filename} ({f.label}): \"{f.preview[:150]}\"", WIDTH, subsequent_indent="    "))

    flagged = [lab for lab in res.labs if lab.flag != "none"]
    print("\n" + rule("EXTRACTED"))
    print(f"Lab values: {len(res.labs)} ({len(flagged)} flagged on the documents): " +
          ", ".join(f"{lab.test} {lab.value}{' ' + lab.unit if lab.unit else ''} [{lab.flag}]" for lab in flagged[:14]) +
          (" ..." if len(flagged) > 14 else ""))
    print(f"Medications (merged, {len(res.medications)}):")
    for med in res.medications:
        print(textwrap.fill(f"  - {med.generic_name}: {'; '.join(med.statuses)} | sources: {', '.join(short(s) for s in med.sources)}",
                            WIDTH, subsequent_indent="      "))

    t = res.usage["totals"]
    print("\n" + rule("USAGE"))
    print(f"Model calls: {t['model_calls']} (cache hits: {t['cache_hits']}, failed: {t['failed_calls']}) | "
          f"input {t['input_tokens']:,} (cached {t['cached_input_tokens']:,}, written {t['cache_write_tokens']:,}) | "
          f"output {t['output_tokens']:,} (reasoning {t['reasoning_tokens']:,}) | cost ${t['cost_usd']:.5f} | {seconds:.1f}s")
    for agent, g in res.usage["by_agent"].items():
        print(f"  {agent:15s} {g['calls']} call(s)  in {g['input_tokens']:>6,} (cached {g['cached_input_tokens']:>5,})"
              f"  out {g['output_tokens']:>5,}  ${g['cost_usd']:.5f}")


def find_cases(names: list[str], all_cases: bool) -> list[Path]:
    dirs = sorted(p for p in config.TEST_CASES_DIR.iterdir() if (p / "profile.json").is_file())
    if all_cases:
        return dirs
    chosen = []
    for n in names:
        match = [d for d in dirs if d.name.startswith(n)]
        if not match:
            sys.exit(f"No case matches '{n}'. Available: {', '.join(d.name for d in dirs)}")
        chosen += match
    return chosen


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*", help="case id prefixes, e.g. case1")
    ap.add_argument("--all", action="store_true", help="run all demo cases")
    ap.add_argument("--no-cache", action="store_true", help="ignore the per-document cache (fresh model calls)")
    ap.add_argument("--add", action="append", default=[], help="extra file to add to the case (e.g. an attack sample)")
    args = ap.parse_args()
    if not args.cases and not args.all:
        ap.error("name at least one case or use --all")
    if not config.KEY_STATUS.loaded:
        sys.exit(config.missing_key_banner())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for case_dir in find_cases(args.cases, args.all):
        q = Questionnaire.model_validate_json((case_dir / "profile.json").read_text())
        files = [(f.name, f.read_bytes()) for f in sorted((case_dir / "documents").iterdir()) if not f.name.startswith(".")]
        files += [(Path(a).name, Path(a).read_bytes()) for a in args.add]
        label = case_dir.name + ("+attack" if args.add else "")
        started = time.perf_counter()
        res = await run_intake(label, q, files, use_cache=not args.no_cache)
        seconds = time.perf_counter() - started
        print_result(res, q, seconds)
        out = res.model_dump()
        out["seconds"] = round(seconds, 1)
        # Fresh runs are the measured evidence; runs that used the cache are saved separately.
        suffix = ".cached" if res.usage["totals"]["cache_hits"] else ""
        (OUT_DIR / f"{label}{suffix}.json").write_text(json.dumps(out, indent=2))
    print(f"\nSaved to {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    asyncio.run(main())
