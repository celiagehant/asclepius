"""Offline tests for chat with the panel (no model calls, no key needed).

    .venv/bin/python tests/test_chat.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory()
os.environ["CC_DB_PATH"] = str(Path(_tmp.name) / "chat_test.db")
os.environ["CC_SIGNUPS_PER_IP_PER_HOUR"] = "1000"  # the tests create many accounts from one address

from fastapi.testclient import TestClient  # noqa: E402
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart  # noqa: E402

from backend import chat, db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.schemas import ChatRouteOutput  # noqa: E402


def turn(i: int, with_tool: bool) -> list:
    msgs = [ModelRequest(parts=[UserPromptPart(content=f"question {i} " + "x" * 400)])]
    if with_tool:
        msgs += [ModelResponse(parts=[ToolCallPart(tool_name="search_medlineplus", args={"query": "anemia"}, tool_call_id=f"call{i}")]),
                 ModelRequest(parts=[ToolReturnPart(tool_name="search_medlineplus", content="ok " + "y" * 600, tool_call_id=f"call{i}")])]
    msgs.append(ModelResponse(parts=[TextPart(content=f"answer {i} " + "z" * 300)]))
    return msgs


def test_memory_is_trimmed_by_whole_turns_and_keeps_tool_pairs():
    history = [m for i in range(12) for m in turn(i, with_tool=i % 2 == 0)]
    assert chat.tool_pairs_intact(history)
    trimmed = chat.trim_memory(history, max_chars=6000)
    assert len(trimmed) < len(history)
    assert chat.tool_pairs_intact(trimmed)                                     # no orphan tool results or calls
    assert isinstance(trimmed[0], ModelRequest) and isinstance(trimmed[0].parts[0], UserPromptPart)  # starts at a question
    assert trimmed[-1].parts[0].content.startswith("answer 11")               # newest turn always kept
    one = chat.trim_memory(history, max_chars=10)                              # budget smaller than one turn
    assert one[0].parts[0].content.startswith("question 11") and chat.tool_pairs_intact(one)
    # Cutting by message count can start mid-turn and orphan a tool result; trimming drops the orphan.
    cut = history[2:]
    assert not chat.tool_pairs_intact(cut)
    assert chat.tool_pairs_intact(chat.trim_memory(cut, 10**6))


def test_routing_is_enforced_in_code():
    members = ["hematology", "cardiology", "nephrology", "clinical_pharmacist"]
    r = ChatRouteOutput(specialists=["cardiology", "oncology", "hematology", "nephrology"], medication_question=False, reason="r")
    assert chat.enforce_route(r, "Why is my heart racing?", members)[0] == ["cardiology", "hematology"]   # panel only, max two
    r = ChatRouteOutput(specialists=["nephrology"], medication_question=False, reason="r")
    assert chat.enforce_route(r, "Should he keep taking naproxen?", members)[0] == ["clinical_pharmacist", "nephrology"]
    assert chat.enforce_route(None, "What about my kidneys? nephrology", members)[0] == ["nephrology"]   # router down: keywords
    assert chat.enforce_route(None, "What now?", members)[0] == ["hematology"]


def _setup_case(client: TestClient, email: str) -> int:
    client.post("/api/auth/signup", json={"email": email, "password": "correct horse", "adult_confirmed": True})
    case_id = client.post("/api/demo/case1_adult_multisystem").json()["case_id"]
    uid = db.user_by_email(email)["id"]
    result = {"specialists": {"hematology": {"specialty": "hematology", "name": "Hematology", "findings": [], "abnormal_values": [],
                                             "concerns": [], "confidence": "high", "questions_for_specialists": []}},
              "pharmacist": None, "summary": {"plain_language_summary": "s", "key_findings": [], "connections": []},
              "modes": {"coordinator": "internal_medicine"}}
    db.update_case(uid, case_id, status="complete", result=result)
    return case_id


def _stream_events(client: TestClient, case_id: int, message: str) -> list[dict]:
    events = []
    with client.stream("POST", f"/api/cases/{case_id}/chat", json={"message": message}) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: {}":
                events.append(json.loads(line[6:]))
    return events


def test_emergency_questions_get_help_at_once_and_history_is_private():
    alice, bob = TestClient(app), TestClient(app)
    alice.__enter__(); bob.__enter__()
    case_id = _setup_case(alice, "alice@chat.test")
    bob.post("/api/auth/signup", json={"email": "bob@chat.test", "password": "correct horse", "adult_confirmed": True})
    events = _stream_events(alice, case_id, "I keep thinking about ending my life")
    final = events[-1]
    assert final["type"] == "final" and final["status"] == "emergency"
    assert final["message"]["role"] == "safety" and "988" in final["message"]["content"]
    assert not any(e["type"] == "spend" for e in events)                          # no model was called
    hist = alice.get(f"/api/cases/{case_id}/chat").json()
    assert [m["role"] for m in hist["messages"]] == ["user", "safety"] and hist["available"]
    assert bob.get(f"/api/cases/{case_id}/chat").status_code == 404
    assert bob.post(f"/api/cases/{case_id}/chat", json={"message": "hi"}).status_code == 404


def test_chat_needs_a_finished_case_and_delete_removes_it():
    c = TestClient(app); c.__enter__()
    c.post("/api/auth/signup", json={"email": "carol@chat.test", "password": "correct horse", "adult_confirmed": True})
    draft = c.post("/api/demo/case2_autoimmune_pattern").json()["case_id"]
    events = _stream_events(c, draft, "What do my results mean?")
    assert events[-1]["status"] == "error" and "finish" in events[-1]["error"]
    case_id = _setup_case(c, "carol@chat.test")
    _stream_events(c, case_id, "Chest pain right now and I can't breathe")
    uid = db.user_by_email("carol@chat.test")["id"]
    db.set_memory(uid, case_id, "hematology", "[]")
    removed = c.post("/api/me/delete-data", json={"confirm": "DELETE"}).json()["removed"]
    assert removed["chat_messages"] >= 2
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat_memory WHERE user_id = ?", (uid,)).fetchone()[0] == 0


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
