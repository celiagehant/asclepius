"""Offline tests for tokenomics (no model calls, no key needed).

    .venv/bin/python tests/test_tokenomics.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory()
os.environ["CC_DB_PATH"] = str(Path(_tmp.name) / "tok.db")
os.environ["CC_SIGNUPS_PER_IP_PER_HOUR"] = "1000"  # the tests create many accounts from one address

from fastapi.testclient import TestClient  # noqa: E402
from pydantic_ai.messages import InstructionPart, ModelRequest, UserPromptPart  # noqa: E402
from pydantic_ai.models import ModelRequestParameters  # noqa: E402

from backend import db, llm  # noqa: E402
from backend.main import app  # noqa: E402
from backend.panel import member_of  # noqa: E402


def test_cost_formula_uses_the_published_prices():
    # input $0.10, cached input $0.01, cache write $0.125, output $0.50 per 1M; input includes cached + written
    assert llm.cost_usd(1_000_000, 0, 0, 0) == 0.10
    assert llm.cost_usd(1_000_000, 1_000_000, 0, 0) == 0.01
    assert llm.cost_usd(1_000_000, 0, 1_000_000, 0) == 0.125
    assert llm.cost_usd(0, 0, 0, 1_000_000) == 0.50
    # 10,000 input of which 6,000 cached and 1,000 written, plus 2,000 output
    expected = 3_000 * 0.10 / 1e6 + 6_000 * 0.01 / 1e6 + 1_000 * 0.125 / 1e6 + 2_000 * 0.50 / 1e6
    assert abs(llm.cost_usd(10_000, 6_000, 1_000, 2_000) - expected) < 1e-12


def test_every_call_is_attributed_to_a_panel_member():
    m = llm.UsageMeter(member_of=member_of)
    for agent, label in [("intake_extract", "a.pdf"), ("specialist_r1", "r1.cardiology"), ("specialist_r2", "r2.cardiology"),
                         ("pharmacist", "r1.clinical_pharmacist"), ("coordinator", "coordinator.synthesis"), ("safety_reviewer", "safety_reviewer")]:
        m.add(llm.CallRecord(agent, label, 1, 1000, 500, 0, 200, 0, 1.0, llm.cost_usd(1000, 500, 0, 200), True))
    groups = m.by_member()
    assert set(groups) == {"intake", "cardiology", "clinical_pharmacist", "coordinator", "safety_reviewer"}
    assert groups["cardiology"]["calls"] == 2
    assert abs(sum(g["cost_usd"] for g in groups.values()) - m.totals()["cost_usd"]) < 1e-9


def test_caching_off_puts_a_fresh_random_string_first_on_every_request():
    params = ModelRequestParameters(instruction_parts=[InstructionPart("You are the intake agent.")])
    msgs = [ModelRequest(parts=[UserPromptPart(content="doc")], instructions="You are the intake agent.")]
    (m1, p1), (m2, p2) = llm._with_nonce(msgs, params), llm._with_nonce(msgs, params)
    a, b = p1.instruction_parts[0].content, p2.instruction_parts[0].content
    assert a.startswith("[request ") and a.endswith("You are the intake agent.") and a != b   # differs every request
    assert m1[0].instructions.startswith("[request ")
    assert params.instruction_parts[0].content == "You are the intake agent."                 # the original is untouched
    llm.set_prompt_cache(False)
    assert type(llm.model()).__name__ == "NoPromptCacheModel"
    llm.set_prompt_cache(True)


def test_round2_reads_one_shared_board_not_every_report():
    """Round 2 hands every reader the same board block first in the message (cacheable),
    instead of N-1 peer reports each; new members are metered under their own names."""
    from backend import board, patterns
    posts = [{"id": f"m{i}.F1", "by": f"m{i}", "system": "blood", "symptoms": ["fatigue"], "line": "Hb 10", "significance": "abnormal",
              "region": "blood"} for i in range(5)]
    assert board.render(posts) == board.render([dict(p) for p in posts])     # identical for every reader
    assert len(board.render(posts)) < 600                                     # about 25 tokens per post
    assert patterns.library_block().startswith("# Pattern library")           # the shared cached prefix
    assert member_of("coordinator", "coordinator.challenge") == "coordinator"
    assert member_of("lifestyle", "r4.lifestyle") == "lifestyle"
    assert member_of("specialist_r2", "r2.hematology (retry 1)") == "hematology"


def test_usage_log_is_private_and_deleted_with_the_data():
    c = TestClient(app); c.__enter__()
    other = TestClient(app); other.__enter__()
    c.post("/api/auth/signup", json={"email": "t@tok.test", "password": "correct horse", "adult_confirmed": True})
    other.post("/api/auth/signup", json={"email": "o@tok.test", "password": "correct horse", "adult_confirmed": True})
    case_id = c.post("/api/demo/case4_polypharmacy").json()["case_id"]
    uid = db.user_by_email("t@tok.test")["id"]
    rec = llm.CallRecord("specialist_r1", "r1.cardiology", 2, 9000, 6000, 500, 1500, 300, 7.5, llm.cost_usd(9000, 6000, 500, 1500), True, member="cardiology")
    db.add_usage(uid, case_id, "run-x", "panel", asdict(rec))
    data = c.get(f"/api/cases/{case_id}/usage").json()
    run = data["runs"][0]
    assert run["totals"]["input_tokens"] == 9000 and run["calls"][0]["member"] == "cardiology" and run["calls"][0]["seconds"] == 7.5
    assert data["prices_per_1m"] == {"input": 0.1, "cached_input": 0.01, "cache_write": 0.125, "output": 0.5}
    assert other.get(f"/api/cases/{case_id}/usage").status_code == 404
    c.post("/api/me/delete-data", json={"confirm": "DELETE"})
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM usage_log WHERE user_id = ?", (uid,)).fetchone()[0] == 0


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
