"""Ask the panel a question about a finished case, from the command line.

    .venv/bin/python scripts/run_chat.py --email you@example.com --case 1 "Are any of my medicines doubled up?"

Prints the live events (routing, who answers, tool calls, safety) and the final answer.
The exchange is saved to the case's chat history, as in the web app.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import chat, db  # noqa: E402


def printer(e: dict) -> None:
    t = e["type"]
    if t == "spend":
        return
    if t == "chat_routed":
        print(f"{e['t']:5.1f}s  routed to: {', '.join(e['names'])}  ({e['reason'][:90]})")
    elif t in ("specialist_started", "specialist_done"):
        print(f"{e['t']:5.1f}s  {'LIGHTS UP' if t == 'specialist_started' else 'done     '} {e['name']}")
    elif t == "tool_call":
        print(f"{e['t']:5.1f}s    tool {e['tool']}({e['args'].get('query') or e['args'].get('drug')}) -> {e['status']}")
    elif t in ("coordinator_thinking", "safety_check", "error"):
        print(f"{e['t']:5.1f}s  {t}: {json.dumps({k: v for k, v in e.items() if k not in ('seq', 't', 'type')})[:120]}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--email", required=True)
    ap.add_argument("--case", type=int, required=True)
    args = ap.parse_args()
    db.init()
    user = db.user_by_email(args.email.lower())
    if not user:
        sys.exit("No user with that email.")
    events = chat.new_chat_events(user["id"], args.case)
    events.printers.append(printer)
    try:
        msg = await chat.answer_question(user_id=user["id"], case_id=args.case, question=args.question, events=events)
    except chat.ChatError as exc:
        sys.exit(f"Chat error: {exc}")
    print("\n" + "=" * 100)
    for a in msg["meta"].get("answers", []):
        print(textwrap.fill(f"{a['name']} (AI specialist, confidence {a['confidence']}): {a['text']}", 100))
        if a.get("ask_your_doctor"):
            print(textwrap.fill(f"   Ask your doctor: {a['ask_your_doctor']}", 100))
        for s in a.get("sources", []):
            print(f"   source: {s['title']} <{s['url']}>")
        print()
    print(textwrap.fill(f"Coordinator: {msg['meta'].get('wrap_up', '')}", 100))
    sf = msg["meta"].get("safety") or {}
    print(f"\nSafety: {len(sf.get('edits', []))} reviewer edit(s), {len(sf.get('blocked', []))} blocked by code"
          + (f" | usage: ${msg['meta']['usage']['cost_usd']:.5f}, {msg['meta']['usage']['model_calls']} calls" if msg["meta"].get("usage") else ""))
    for e in sf.get("edits", []):
        print(textwrap.fill(f"  - {e['item_id']}: {e['problem']} -> {e['action']}" + (f": {e['new_text']}" if e.get("new_text") else ""), 100))


if __name__ == "__main__":
    asyncio.run(main())
