"""Record fresh runs of the four demo patients for the offline demo HTML.

    .venv/bin/python scripts/record_demo.py            # all four cases (about $0.07)
    .venv/bin/python scripts/record_demo.py case3      # one case

For each synthetic demo patient this runs the full panel (current code, all defenses on),
then asks the panel three chat questions, exactly as the web app would. Everything is saved
to output/demo/recordings/<case>.json, which scripts/build_demo.py packs into the HTML.

The chat needs a case in a database, so this uses its own throwaway database
(storage/demo_recording.db), never the app's.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["CC_DB_PATH"] = str(ROOT / "storage" / "demo_recording.db")
os.environ.setdefault("CC_DAILY_BUDGET_USD", "10")

from backend import chat, config, db  # noqa: E402
from backend.auth import hash_password  # noqa: E402
from backend.documents import read_document  # noqa: E402
from backend.panel import new_run, run_case  # noqa: E402
from backend.profiles import from_demo, to_questionnaire  # noqa: E402

OUT = ROOT / "output" / "demo" / "recordings"
QUESTIONS = {
    "case1_adult_multisystem": ["Are my tiredness, racing heart and stomach problems connected?",
                                "Should I keep taking ibuprofen for my headaches?",
                                "What should I ask the gastroenterologist first?"],
    "case2_autoimmune_pattern": ["Could my rash, kidney results and low blood counts be related?",
                                 "Which tests could I ask about?",
                                 "Is it OK to keep taking naproxen with my kidney results?"],
    "case3_pediatric_ranges": ["Urgent care said his labs were normal. Are they normal for a 7-year-old?",
                               "Why is he so thirsty and wetting the bed again?",
                               "What should we ask the pediatrician first?"],
    "case4_polypharmacy": ["Is he taking two medicines that do the same thing?",
                           "Could his medicines explain the dizziness and the fall?",
                           "What should we ask his cardiologist?"],
}


async def record(case_dir: Path) -> None:
    raw = json.loads((case_dir / "profile.json").read_text())
    profile, concern = from_demo(raw)
    files = [(f.name, f.read_bytes()) for f in sorted((case_dir / "documents").iterdir()) if not f.name.startswith(".")]
    events = new_run("demo-recording", case_dir.name)
    started = time.perf_counter()
    result = await run_case(user_id="demo-recording", case_id=case_dir.name, questionnaire=to_questionnaire(profile, concern),
                            files=files, events=events, use_cache=True)
    print(f"  {case_dir.name}: panel {result['status']} ${result['usage']['totals']['cost_usd']:.4f} {time.perf_counter() - started:.0f}s", flush=True)

    # The chat runs against a case stored in the throwaway database, as in the app.
    email = f"{case_dir.name}@demo-recording.example"
    user = db.user_by_email(email)
    uid = user["id"] if user else db.create_user(email, hash_password(os.urandom(16).hex()))
    pid = db.create_profile(uid, profile.model_dump())
    cid = db.create_case(uid, pid, raw["case_title"], concern)
    for name, data in files:
        doc = read_document(name, data)
        db.add_file(uid, cid, name, doc.sha256, doc.kind, {"read_by": doc.read_by}, data)
    db.update_case(uid, cid, status=result["status"], result=result, profile_snapshot=profile.model_dump())
    chats = []
    for question in QUESTIONS[case_dir.name]:
        chat_events = chat.new_chat_events(uid, cid)
        t0 = time.perf_counter()
        try:
            message = await chat.answer_question(user_id=uid, case_id=cid, question=question, events=chat_events)
        except chat.ChatError as exc:
            print(f"    chat failed: {exc}")
            continue
        chats.append({"question": question, "message": message, "seconds": round(time.perf_counter() - t0, 1),
                      "events": [e for e in chat_events.events if e["type"] != "spend"]})
        print(f"    asked: {question[:60]} -> {', '.join(message['meta'].get('routed') or [])} "
              f"${(message['meta'].get('usage') or {}).get('cost_usd', 0):.4f}", flush=True)
    usage_rows = db.list_usage(uid, cid)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{case_dir.name}.json").write_text(json.dumps({
        "case_id": case_dir.name, "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": profile.model_dump(), "case_title": raw["case_title"], "case_summary": raw["case_summary_for_demo"],
        "main_concern": concern, "result": result, "events": events.events, "chat": chats,
        "chat_usage": [r for r in usage_rows if r["kind"] == "chat"],
    }, indent=1))


async def main() -> None:
    if not config.KEY_STATUS.loaded:
        sys.exit(config.missing_key_banner())
    db.init()
    cases = sorted(p for p in config.TEST_CASES_DIR.iterdir() if (p / "profile.json").is_file()
                   and (len(sys.argv) < 2 or p.name.startswith(tuple(sys.argv[1:]))))
    print(f"Recording {len(cases)} case(s)...", flush=True)
    async def safe(c: Path) -> None:
        try:
            await record(c)
        except Exception as exc:
            print(f"  {c.name}: FAILED {type(exc).__name__}: {str(exc)[:200]}", flush=True)
    await asyncio.gather(*[safe(c) for c in cases])
    print(f"Saved to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    asyncio.run(main())
