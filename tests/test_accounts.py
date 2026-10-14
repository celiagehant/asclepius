"""Offline tests for accounts, profiles, cases and privacy (no model calls, no key needed).

    .venv/bin/python tests/test_accounts.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory()
os.environ["CC_DB_PATH"] = str(Path(_tmp.name) / "test.db")
os.environ["CC_SIGNUPS_PER_IP_PER_HOUR"] = "1000"  # the tests create many accounts from one address

from fastapi.testclient import TestClient  # noqa: E402

from backend import db  # noqa: E402
from backend.main import app  # noqa: E402

ADULT = {"for_whom": "self", "name": "Dana", "date_of_birth": "1984-03-12", "sex_at_birth": "female", "pregnancy": "neither",
         "medications_status": "listed", "medications": [{"name": "Propranolol", "dose": "10 mg"}],
         "allergies_status": "none", "conditions_status": "none", "family_status": "none_known",
         "tobacco": "never", "alcohol": "occasionally", "main_concern": "Tired and my heart races on stairs."}
DOC = (ROOT / "data/test_cases/case1_adult_multisystem/documents/04_ecg_report.txt").read_bytes()


def client(email: str) -> TestClient:
    c = TestClient(app)
    c.__enter__()
    r = c.post("/api/auth/signup", json={"email": email, "password": "correct horse", "adult_confirmed": True})
    assert r.status_code == 200, r.text
    return c


def test_signup_login_logout_and_hashed_passwords():
    c = client("a@example.com")
    assert c.get("/api/auth/me").json()["email"] == "a@example.com"
    with sqlite3.connect(os.environ["CC_DB_PATH"]) as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE email = 'a@example.com'").fetchone()[0]
        token_rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert c.cookies.get("cc_session") not in {t[0] for t in token_rows}  # only the token's hash is stored
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong password"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "A@Example.com", "password": "correct horse"}).status_code == 200
    anon = TestClient(app)
    assert anon.post("/api/auth/signup", json={"email": "kid@example.com", "password": "12345678"}).status_code == 400  # no 18+ confirmation
    assert anon.get("/api/profiles").status_code == 401 and anon.get("/api/cases").status_code == 401


def test_profiles_validation_minors_and_prefer_not():
    c = client("b@example.com")
    r = c.post("/api/profiles", json={**ADULT, "date_of_birth": "2015-01-01"})
    assert r.status_code == 422 and "under 18" in r.json()["detail"]                       # a minor can't be "myself"
    child = c.post("/api/profiles", json={**ADULT, "for_whom": "care", "relationship": "child", "name": "Theo",
                                          "date_of_birth": "2019-04-02", "sex_at_birth": "male", "pregnancy": "pregnant"}).json()
    assert child["pediatric"] and child["data"]["pregnancy"] is None                       # question did not apply
    assert c.post("/api/profiles", json={**ADULT, "date_of_birth": None}).status_code == 422  # age is required
    p = c.post("/api/profiles", json={**ADULT, "sex_at_birth": "prefer_not_to_say", "tobacco": "prefer_not_to_say"}).json()
    from backend.profiles import to_questionnaire
    from backend.schemas import ProfileData
    q = to_questionnaire(ProfileData.model_validate(p["data"]))
    assert "sex assigned at birth" in q.withheld and "tobacco use" in q.withheld
    assert len(c.get("/api/profiles").json()) == 2                                          # several profiles per account


def test_emergency_banner_from_main_concern():
    c = client("c@example.com")
    r = c.post("/api/profiles", json={**ADULT, "main_concern": "I have crushing chest pain right now"}).json()
    assert r["emergency"]["emergency"] and r["emergency"]["kind"] == "medical"
    r = c.post("/api/emergency-check", json={"text": "I keep thinking about ending my life"}).json()
    assert r["kind"] == "crisis" and "988" in r["message"]
    assert not c.post("/api/emergency-check", json={"text": "Tired for months, no chest pain."}).json()["emergency"]


def test_users_cannot_see_each_others_data():
    alice, bob = client("alice@example.com"), client("bob@example.com")
    pid = alice.post("/api/profiles", json=ADULT).json()["id"]
    case_id = alice.post("/api/cases", json={"profile_id": pid}).json()["id"]
    fid = alice.post(f"/api/cases/{case_id}/files", files=[("files", ("ecg.txt", DOC, "text/plain"))]).json()["accepted"][0]["id"]
    assert bob.get(f"/api/profiles/{pid}").status_code == 404
    assert bob.put(f"/api/profiles/{pid}", json=ADULT).status_code == 404
    assert bob.get(f"/api/cases/{case_id}").status_code == 404
    assert bob.post("/api/cases", json={"profile_id": pid}).status_code == 400               # can't attach to Alice's profile
    assert bob.post(f"/api/cases/{case_id}/files", files=[("files", ("x.txt", DOC, "text/plain"))]).status_code == 404
    assert bob.delete(f"/api/cases/{case_id}/files/{fid}").status_code == 404
    assert bob.post(f"/api/cases/{case_id}/convene", json={"profile_confirmed": True}).status_code == 404
    assert bob.get(f"/api/cases/{case_id}/events").status_code == 404
    assert bob.get("/api/profiles").json() == [] and bob.get("/api/cases").json() == []
    assert alice.get(f"/api/cases/{case_id}").json()["files"][0]["filename"] == "ecg.txt"


def test_uploads_are_checked_and_convene_needs_confirmation():
    c = client("d@example.com")
    pid = c.post("/api/profiles", json=ADULT).json()["id"]
    case_id = c.post("/api/cases", json={"profile_id": pid}).json()["id"]
    attack = (ROOT / "data/attack_samples/hidden_text_lab_report.pdf").read_bytes()
    r = c.post(f"/api/cases/{case_id}/files", files=[("files", ("ecg.txt", DOC, "text/plain")),
                                                     ("files", ("virus.exe", b"MZ\x90\x00", "application/octet-stream")),
                                                     ("files", ("labs.pdf", attack, "application/pdf"))]).json()
    assert [a["filename"] for a in r["accepted"]] == ["ecg.txt", "labs.pdf"]
    assert r["rejected"][0]["filename"] == "virus.exe"
    assert len(r["accepted"][1]["info"]["hidden_text"]) == 5                                # flagged before the panel runs
    assert c.post(f"/api/cases/{case_id}/convene", json={"profile_confirmed": False}).status_code == 400


def test_delete_all_my_data():
    c = client("e@example.com")
    pid = c.post("/api/profiles", json=ADULT).json()["id"]
    demo = c.post("/api/demo/case4_polypharmacy").json()
    case_id = c.post("/api/cases", json={"profile_id": pid}).json()["id"]
    c.post(f"/api/cases/{case_id}/files", files=[("files", ("ecg.txt", DOC, "text/plain"))])
    with db.connect() as conn:
        uid = conn.execute("SELECT id FROM users WHERE email = 'e@example.com'").fetchone()[0]
        conn.execute("INSERT INTO chat_messages (case_id, user_id, role, content, created_at) VALUES (?, ?, 'user', 'hi', 'now')",
                     (demo["case_id"], uid))
    assert c.post("/api/me/delete-data", json={"confirm": "nope"}).status_code == 400
    r = c.post("/api/me/delete-data", json={"confirm": "DELETE"}).json()
    assert r["removed"] == {"profiles": 2, "cases": 2, "files": 6, "chat_messages": 1}
    with db.connect() as conn:
        for table in ("profiles", "cases", "files", "chat_messages"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (uid,)).fetchone()[0] == 0
    assert c.get("/api/auth/me").status_code == 200                                         # account kept unless asked
    c.post("/api/me/delete-data", json={"confirm": "DELETE", "delete_account": True})
    assert c.get("/api/auth/me").status_code == 401


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
