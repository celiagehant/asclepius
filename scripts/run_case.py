"""Run the whole panel on a demo case from the command line, with live events.

    .venv/bin/python scripts/run_case.py case1
    .venv/bin/python scripts/run_case.py case4 --no-cache
    .venv/bin/python scripts/run_case.py case2 --simulate-outage pubmed,medlineplus
    .venv/bin/python scripts/run_case.py case1 --run-budget 0.004          # graceful budget stop
    .venv/bin/python scripts/run_case.py case1 --add data/attack_samples/hidden_text_lab_report.pdf

Saves output/panel/<case>[+variant]/result.json, audit.json and events.jsonl.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402
from backend.schemas import REGION_LABELS, Questionnaire  # noqa: E402

W = 118


def wrap(text: str, indent: str = "    ") -> str:
    return textwrap.fill(text, W, initial_indent=indent, subsequent_indent=indent + "  ")


def printer(e: dict) -> None:
    t, ty = f"{e['t']:6.1f}s", e["type"]
    if ty == "spend":
        if not e["from_cache"]:
            print(f"{t}  $  {e['agent']:<18} +${e['call_usd']:.5f}  total ${e['total_usd']:.5f}")
        return
    if ty == "document_routed":
        hidden = f"  HIDDEN TEXT DROPPED: {', '.join(e['hidden_text'])}" if e["hidden_text"] else ""
        msg = f"routed {e['document']} [{e['read_by']}, {e['doc_type']}] -> {', '.join(e['specialties'])}{hidden}"
    elif ty == "panel_selected":
        msg = (f"panel: {e['coordinator']} (coordinator), pharmacist {'on' if e['pharmacist'] else 'off'}, "
               f"specialists: {', '.join(a['name'] for a in e['active'])}"
               + (f" | consider: {', '.join(e['consider'])}" if e["consider"] else ""))
    elif ty == "specialist_started":
        extra = f"docs: {', '.join(e.get('documents') or []) or '(symptoms only)'}" if e["round"] == 1 else f"peers: {', '.join(e.get('peers') or [])}"
        msg = f"START  {e['agent']:<26} {extra}"
    elif ty == "tool_call":
        query = e["args"].get("query") or e["args"].get("drug") or ""
        terms = f" terms={e['args'].get('terms')}" if e["args"].get("terms") else ""
        msg = f"  tool {e['agent']}: {e['tool']}({query}{terms}) -> {e['summary'][:70]}"
    elif ty == "specialist_done":
        if e["round"] == 1:
            msg = (f"DONE   {e['agent']:<26} {e['findings']} items, conf {e['confidence']}"
                   + (f", {e['dropped']} dropped by validation" if e.get("dropped") else "")
                   + (f" | {e['headline'][:60]}" if e.get("headline") else ""))
        else:
            msg = f"DONE   {e['agent']:<26} {e['connections']} connections, {e['disagreements']} disagreements"
    elif ty == "conference_round":
        msg = f"== ROUND {e['round']} {e['status'].upper()} " + json.dumps({k: v for k, v in e.items() if k not in ('seq', 'type', 't', 'round', 'status')})[:150]
    elif ty == "comment":
        msg = f"  comment {e['from_']} -> {e['to']} [{e['kind']}]: {e['text'][:80]}"
    elif ty == "coordinator_thinking":
        msg = "coordinator: " + json.dumps({k: v for k, v in e.items() if k not in ('seq', 'type', 't')})[:150]
    elif ty == "safety_check":
        msg = "safety: " + json.dumps({k: v for k, v in e.items() if k not in ('seq', 'type', 't')})[:150]
    elif ty == "error":
        msg = f"ERROR {e['agent']}: {e['message']}"
    elif ty == "final":
        msg = f"FINAL {e['status']} | {e['stop_reason']} | ${e['total_usd']:.5f} | {e['seconds']}s"
    else:
        msg = json.dumps({k: v for k, v in e.items() if k not in ('seq', 't')})[:150]
    print(f"{t}  {msg}"[:W + 40])


def print_summary(res: dict) -> None:
    s = res["summary"]
    print("\n" + "=" * W)
    em = res["emergency"]
    if em["active"]:
        print("!! EMERGENCY BANNER !!")
        for r in em["reasons"]:
            print(wrap(r))
        for a in em.get("actions", []):
            print(wrap("-> " + a))
        print(wrap(em["message"] or ""))
        print("-" * W)
    if not s:
        print(f"No summary ({res['stop_reason']}). Specialist reports available: {', '.join(res['specialists'])}")
        return
    print("CASE SUMMARY\n" + wrap(s["plain_language_summary"], ""))
    for title, key, field in (("KEY FINDINGS", "key_findings", "text"), ("CONNECTIONS", "connections", "text"),
                              ("MEDICATIONS TO DISCUSS", "medication_discussion", "text")):
        if s[key]:
            print(f"\n{title}")
            for x in s[key]:
                print(wrap(f"- {x[field]}  [{', '.join(x['finding_refs'])}]"))
    if s["red_flags"]:
        print("\nRED FLAGS")
        for r in s["red_flags"]:
            print(wrap(f"- [{r['urgency']}] {r['flag']} -> {r['what_to_do']}" + (f" (added by {r['added_by']})" if r.get("added_by") else "")))
    print("\nQUESTIONS FOR YOUR DOCTORS")
    for d in s["questions_for_doctors"]:
        print(f"  {d['doctor']}")
        for q in d["questions"]:
            print(wrap(f"- {q}", "      "))
    if s["suggested_specialists"]:
        print("\nSUGGESTED SPECIALISTS: " + "; ".join(f"{x['specialty']} ({x['urgency']})" for x in s["suggested_specialists"]))
    print("\nBODY MAP: " + ", ".join(f"{REGION_LABELS[b['region']]}={b['severity']}" for b in s["body_regions"]))
    if s["limitations"]:
        print("LIMITATIONS: " + " | ".join(s["limitations"]))
    sf = res["safety"]
    print(f"\nSAFETY: {len(sf.get('model_edits', []))} reviewer edits, {len(sf.get('missed_red_flags_added', []))} missed red flags "
          f"added, {len(sf.get('code_blocked', []))} items blocked by code checks")
    for e in sf.get("model_edits", []):
        print(wrap(f"- {e['item_id']} {e['problem']} -> {e['action']}" + (f": {e['new_text'][:90]}" if e.get("new_text") else "")))
    t = res["usage"]["totals"]
    print(f"\nUSAGE: {t['model_calls']} model calls ({t['cache_hits']} cache hits) | input {t['input_tokens']:,} "
          f"(cached {t['cached_input_tokens']:,}) | output {t['output_tokens']:,} | ${t['cost_usd']:.5f} | {res['seconds']}s")
    for agent, g in res["usage"]["by_agent"].items():
        print(f"   {agent:18} {g['calls']:>2} calls  in {g['input_tokens']:>7,} (cached {g['cached_input_tokens']:>7,})  "
              f"out {g['output_tokens']:>6,}  ${g['cost_usd']:.5f}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", help="case id prefix, e.g. case1")
    ap.add_argument("--no-cache", action="store_true", help="fresh intake calls (ignore the per-document cache)")
    ap.add_argument("--add", action="append", default=[], help="extra document to add (e.g. an attack sample)")
    ap.add_argument("--simulate-outage", default="", help="comma list: pubmed,medlineplus,openfda")
    ap.add_argument("--run-budget", type=float, default=None, help="per-run budget in USD (default 0.05)")
    ap.add_argument("--user", default="cli", help="user id for the daily budget ledger")
    ap.add_argument("--quiet", action="store_true", help="do not print live events")
    args = ap.parse_args()
    if not config.KEY_STATUS.loaded:
        sys.exit(config.missing_key_banner())
    if args.simulate_outage:
        os.environ["CC_SIMULATE_OUTAGE"] = args.simulate_outage
    from backend.panel import new_run, run_case  # after the env var is set

    dirs = sorted(p for p in config.TEST_CASES_DIR.iterdir() if p.name.startswith(args.case) and (p / "profile.json").is_file())
    if not dirs:
        sys.exit(f"No case matches {args.case!r}.")
    case_dir = dirs[0]
    q = Questionnaire.model_validate_json((case_dir / "profile.json").read_text())
    files = [(f.name, f.read_bytes()) for f in sorted((case_dir / "documents").iterdir()) if not f.name.startswith(".")]
    files += [(Path(a).name, Path(a).read_bytes()) for a in args.add]
    variant = "".join([f"+{Path(a).stem}" for a in args.add] + ([f"+outage-{args.simulate_outage.replace(',', '-')}"] if args.simulate_outage else [])
                      + ([f"+budget-{args.run_budget}"] if args.run_budget else []))
    events = new_run(args.user, case_dir.name)
    if not args.quiet:
        events.printers.append(printer)
    usage_log = ROOT / "output" / "usage" / "usage_log.jsonl"
    usage_log.parent.mkdir(parents=True, exist_ok=True)

    def log_call(rec) -> None:  # every model call, appended as it happens
        with usage_log.open("a") as f:
            f.write(json.dumps({"run_id": events.run_id, "case": case_dir.name, **asdict(rec)}) + "\n")

    res = await run_case(user_id=args.user, case_id=case_dir.name, questionnaire=q, files=files, events=events,
                         use_cache=not args.no_cache, run_budget=args.run_budget, on_call=log_call)
    print_summary(res)
    folder = ROOT / "output" / "panel" / f"{case_dir.name}{variant}"
    events.save(folder, res, {"stop_reason": res["stop_reason"], "status": res["status"], "budget": res["budget"]})
    print(f"\nSaved {folder.relative_to(ROOT)}/ (result.json, audit.json, events.jsonl)")


if __name__ == "__main__":
    asyncio.run(main())
