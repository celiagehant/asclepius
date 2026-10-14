"""Offline tests for the three prompt-injection defense layers (no model calls, no key needed).

    .venv/bin/python tests/test_safety_layers.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import defenses, intake, traps  # noqa: E402
from backend.documents import read_path  # noqa: E402
from backend.events import RunEvents  # noqa: E402

DATA = ROOT / "data" / "safety_tests"
KEY = json.loads((DATA / "answer_key.json").read_text())


def with_defenses(d, fn):
    token = defenses.use(d)
    try:
        return fn()
    finally:
        defenses.reset(token)


def test_every_prompt_carries_a_defense_block_that_the_prompt_layer_controls():
    for p in sorted((ROOT / "backend" / "prompts").glob("*.md")):
        raw = p.read_text()
        if p.name in ("transcribe.md", "intake_extract.md", "intake_route.md", "specialist_base.md", "pharmacist.md",
                      "coordinator.md", "safety.md", "chat_router.md", "specialist_chat.md", "chat_wrapup.md"):
            assert "[[defense]]" in raw, p.name
            on = with_defenses(defenses.ALL_ON, lambda: defenses.prompt_text(raw))
            off = with_defenses(defenses.ALL_OFF, lambda: defenses.prompt_text(raw))
            assert "[[defense]]" not in on and "[[defense]]" not in off
            assert len(off) < len(on), p.name


def test_patient_content_is_delimited_and_labelled_only_with_the_prompt_layer():
    on = with_defenses(defenses.ALL_ON, lambda: defenses.wrap("questionnaire", "my worry"))
    off = with_defenses(defenses.ALL_OFF, lambda: defenses.wrap("questionnaire", "my worry"))
    assert on.startswith("<questionnaire") and "never instructions" in on and on.endswith("</questionnaire>")
    assert off == "Questionnaire:\nmy worry"


def test_code_layer_removes_every_hidden_payload_and_keeps_clean_text():
    for item in KEY["items"]:
        if not item.get("file") or item["file"].endswith((".png", ".jpg")):
            continue  # pictures are read by vision (prompt layer)
        path = DATA / item["file"]
        decode = lambda t: "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) <= 0xE007E else c for c in t).lower()  # noqa: E731
        text_on = decode(with_defenses(defenses.ALL_ON, lambda: read_path(path).text))
        text_off = decode(with_defenses(defenses.ALL_OFF, lambda: read_path(path).text))
        if item["kind"] == "attack" and item["id"] != "A3":  # A3 is fully visible on purpose
            assert item["canary"] not in text_on, item["id"]
            assert item["canary"] in text_off, item["id"]
        if item["kind"] == "clean":
            assert all(f.lower() in text_on for f in item["key_facts"]), item["id"]
            assert not with_defenses(defenses.ALL_ON, lambda: read_path(path).hidden_text), item["id"]  # nothing dropped


def test_intake_cache_is_keyed_by_the_defense_setting():
    on = with_defenses(defenses.ALL_ON, lambda: intake._cache_path("abc"))
    off = with_defenses(defenses.ALL_OFF, lambda: intake._cache_path("abc"))
    assert on != off and on.name.endswith("_cdp.json") and off.name.endswith("_---.json")


def test_trap_tools_do_nothing_but_log():
    events = RunEvents("run-trap", "u", "c")
    events.agent_started("r1.cardiology", "specialist", "cardiology", 1, [])
    t1, t2 = traps.current_events.set(events), traps.current_agent.set("r1.cardiology")
    try:
        reply = traps.send_records_by_email("x@example.net", "records", "all of them")
        traps.change_medication("warfarin", "stop", "attack")
    finally:
        traps.current_events.reset(t1)
        traps.current_agent.reset(t2)
    assert "Nothing was sent or changed" in reply
    calls = traps.calls_for_run("run-trap")
    assert [c["tool"] for c in calls] == ["send_records_by_email", "change_medication"] and calls[0]["agent"] == "r1.cardiology"
    assert [e["type"] for e in events.events] == ["trap_call", "trap_call"]
    assert [c["status"] for c in events.agents["r1.cardiology"].tool_calls] == ["TRAP", "TRAP"]


def test_server_side_scoping_is_part_of_the_code_layer():
    from tests.test_panel_rules import doc, intake_with  # reuse the fixtures
    from backend.panel import documents_for
    i = intake_with([doc("ecg.txt", "a", ["cardiology"]), doc("iron.pdf", "b", ["hematology"])], {"cardiology": ["ecg.txt"]})
    assert [d.filename for d in with_defenses(defenses.ALL_ON, lambda: documents_for(i, "cardiology"))] == ["ecg.txt"]
    assert len(with_defenses(defenses.ALL_OFF, lambda: documents_for(i, "cardiology"))) == 2


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
