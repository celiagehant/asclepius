"""SQLite storage. Every function that reads or changes user data takes `user_id` and
filters by it, so one user can never reach another user's rows: a row that belongs to
someone else is simply "not found".

The database lives in storage/case_conference.db (never committed). Uploaded files are
stored as blobs in the same database, so "Delete all my data" removes them with the rest.
Set CC_DB_PATH to use another file (the tests do).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config

DB_PATH = Path(os.environ.get("CC_DB_PATH", config.REPO_ROOT / "storage" / "case_conference.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    main_concern TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    run_id TEXT,
    profile_snapshot TEXT,
    result TEXT,
    cost_usd REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT NOT NULL,
    info TEXT NOT NULL DEFAULT '{}',
    content BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_memory (
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_key TEXT NOT NULL,
    messages TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (case_id, agent_key)
);
CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- panel or chat
    agent TEXT NOT NULL,
    label TEXT NOT NULL,
    member TEXT,
    requests INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    cached_input_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    reasoning_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    seconds REAL NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    from_cache INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_case ON usage_log(case_id, user_id);
CREATE INDEX IF NOT EXISTS idx_profiles_user ON profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_cases_user ON cases(user_id);
CREATE INDEX IF NOT EXISTS idx_files_case ON files(case_id, user_id);
CREATE INDEX IF NOT EXISTS idx_chat_case ON chat_messages(case_id, user_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(SCHEMA)
        columns = {r["name"] for r in c.execute("PRAGMA table_info(chat_messages)")}
        if "meta" not in columns:  # added in Phase 6
            c.execute("ALTER TABLE chat_messages ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'")
        # A server restart interrupts any run in progress.
        c.execute("UPDATE cases SET status = 'interrupted', updated_at = ? WHERE status = 'running'", (now(),))


# ---- users and sessions -------------------------------------------------------------------

def create_user(email: str, password_hash: str) -> int:
    with connect() as c:
        cur = c.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)", (email, password_hash, now()))
        return int(cur.lastrowid)


def user_by_email(email: str) -> sqlite3.Row | None:
    with connect() as c:
        return c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def create_session(token_hash: str, user_id: int, expires_at: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (token_hash, user_id, now(), expires_at))


def user_for_session(token_hash: str) -> sqlite3.Row | None:
    with connect() as c:
        return c.execute(
            "SELECT users.id, users.email FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.token_hash = ? AND sessions.expires_at > ?", (token_hash, now())).fetchone()


def delete_session(token_hash: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


# ---- profiles -----------------------------------------------------------------------------

def _profile(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "data": json.loads(row["data"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"], "confirmed_at": row["confirmed_at"]}


def list_profiles(user_id: int) -> list[dict[str, Any]]:
    with connect() as c:
        return [_profile(r) for r in c.execute("SELECT * FROM profiles WHERE user_id = ? ORDER BY id", (user_id,))]


def get_profile(user_id: int, profile_id: int) -> dict[str, Any] | None:
    with connect() as c:
        row = c.execute("SELECT * FROM profiles WHERE id = ? AND user_id = ?", (profile_id, user_id)).fetchone()
        return _profile(row) if row else None


def create_profile(user_id: int, data: dict[str, Any]) -> int:
    with connect() as c:
        t = now()
        cur = c.execute("INSERT INTO profiles (user_id, data, created_at, updated_at, confirmed_at) VALUES (?, ?, ?, ?, ?)",
                        (user_id, json.dumps(data), t, t, t))
        return int(cur.lastrowid)


def update_profile(user_id: int, profile_id: int, data: dict[str, Any]) -> bool:
    with connect() as c:
        t = now()
        cur = c.execute("UPDATE profiles SET data = ?, updated_at = ?, confirmed_at = ? WHERE id = ? AND user_id = ?",
                        (json.dumps(data), t, t, profile_id, user_id))
        return cur.rowcount == 1


def confirm_profile(user_id: int, profile_id: int) -> bool:
    with connect() as c:
        cur = c.execute("UPDATE profiles SET confirmed_at = ? WHERE id = ? AND user_id = ?", (now(), profile_id, user_id))
        return cur.rowcount == 1


def delete_profile(user_id: int, profile_id: int) -> list[str]:
    """Deletes the profile with its cases, files and chat. Returns the run ids and file hashes removed."""
    with connect() as c:
        runs = [r["run_id"] for r in c.execute("SELECT run_id FROM cases WHERE profile_id = ? AND user_id = ? AND run_id IS NOT NULL",
                                               (profile_id, user_id))]
        c.execute("DELETE FROM profiles WHERE id = ? AND user_id = ?", (profile_id, user_id))
        return runs


# ---- cases and files ----------------------------------------------------------------------

CASE_FIELDS = "id, profile_id, title, main_concern, status, run_id, cost_usd, created_at, updated_at"


def list_cases(user_id: int) -> list[dict[str, Any]]:
    with connect() as c:
        rows = c.execute(f"SELECT {CASE_FIELDS}, (SELECT COUNT(*) FROM files WHERE files.case_id = cases.id) AS file_count "
                         "FROM cases WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def get_case(user_id: int, case_id: int, *, with_result: bool = False) -> dict[str, Any] | None:
    with connect() as c:
        fields = CASE_FIELDS + (", result, profile_snapshot" if with_result else "")
        row = c.execute(f"SELECT {fields} FROM cases WHERE id = ? AND user_id = ?", (case_id, user_id)).fetchone()
        if not row:
            return None
        case = dict(row)
        if with_result:
            case["result"] = json.loads(case["result"]) if case["result"] else None
            case["profile_snapshot"] = json.loads(case["profile_snapshot"]) if case["profile_snapshot"] else None
        return case


def create_case(user_id: int, profile_id: int, title: str, main_concern: str) -> int:
    with connect() as c:
        t = now()
        cur = c.execute("INSERT INTO cases (user_id, profile_id, title, main_concern, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (user_id, profile_id, title, main_concern, t, t))
        return int(cur.lastrowid)


def update_case(user_id: int, case_id: int, **fields: Any) -> bool:
    allowed = {"title", "main_concern", "status", "run_id", "profile_snapshot", "result", "cost_usd"}
    sets = {k: (json.dumps(v) if k in ("profile_snapshot", "result") and v is not None else v)
            for k, v in fields.items() if k in allowed}
    if not sets:
        return False
    with connect() as c:
        assignments = ", ".join(f"{k} = ?" for k in sets) + ", updated_at = ?"
        cur = c.execute(f"UPDATE cases SET {assignments} WHERE id = ? AND user_id = ?",
                        (*sets.values(), now(), case_id, user_id))
        return cur.rowcount == 1


def delete_case(user_id: int, case_id: int) -> str | None:
    with connect() as c:
        row = c.execute("SELECT run_id FROM cases WHERE id = ? AND user_id = ?", (case_id, user_id)).fetchone()
        c.execute("DELETE FROM cases WHERE id = ? AND user_id = ?", (case_id, user_id))
        return row["run_id"] if row else None


def add_file(user_id: int, case_id: int, filename: str, sha256: str, kind: str, info: dict[str, Any], content: bytes) -> int:
    with connect() as c:
        cur = c.execute("INSERT INTO files (case_id, user_id, filename, sha256, size, kind, info, content, created_at) "
                        "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM cases WHERE id = ? AND user_id = ?)",
                        (case_id, user_id, filename, sha256, len(content), kind, json.dumps(info), content, now(), case_id, user_id))
        if cur.rowcount != 1:
            raise LookupError("case not found")
        return int(cur.lastrowid)


def list_files(user_id: int, case_id: int) -> list[dict[str, Any]]:
    with connect() as c:
        rows = c.execute("SELECT id, filename, sha256, size, kind, info, created_at FROM files WHERE case_id = ? AND user_id = ? "
                         "ORDER BY id", (case_id, user_id)).fetchall()
        return [{**dict(r), "info": json.loads(r["info"])} for r in rows]


def file_contents(user_id: int, case_id: int) -> list[tuple[str, bytes]]:
    with connect() as c:
        rows = c.execute("SELECT filename, content FROM files WHERE case_id = ? AND user_id = ? ORDER BY id", (case_id, user_id))
        return [(r["filename"], bytes(r["content"])) for r in rows]


def delete_file(user_id: int, case_id: int, file_id: int) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM files WHERE id = ? AND case_id = ? AND user_id = ?", (file_id, case_id, user_id))
        return cur.rowcount == 1


# ---- chat ---------------------------------------------------------------------------------

def add_chat_message(user_id: int, case_id: int, role: str, content: str, meta: dict[str, Any] | None = None) -> int:
    with connect() as c:
        cur = c.execute("INSERT INTO chat_messages (case_id, user_id, role, content, meta, created_at) "
                        "SELECT ?, ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM cases WHERE id = ? AND user_id = ?)",
                        (case_id, user_id, role, content, json.dumps(meta or {}), now(), case_id, user_id))
        if cur.rowcount != 1:
            raise LookupError("case not found")
        return int(cur.lastrowid)


def list_chat(user_id: int, case_id: int, limit: int = 200) -> list[dict[str, Any]]:
    with connect() as c:
        rows = c.execute("SELECT id, role, content, meta, created_at FROM chat_messages WHERE case_id = ? AND user_id = ? "
                         "ORDER BY id DESC LIMIT ?", (case_id, user_id, limit)).fetchall()
        return [{**dict(r), "meta": json.loads(r["meta"] or "{}")} for r in reversed(rows)]


def get_memory(user_id: int, case_id: int, agent_key: str) -> str | None:
    with connect() as c:
        row = c.execute("SELECT messages FROM chat_memory WHERE case_id = ? AND user_id = ? AND agent_key = ?",
                        (case_id, user_id, agent_key)).fetchone()
        return row["messages"] if row else None


def set_memory(user_id: int, case_id: int, agent_key: str, messages_json: str) -> None:
    with connect() as c:
        c.execute("INSERT INTO chat_memory (case_id, user_id, agent_key, messages, updated_at) "
                  "SELECT ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM cases WHERE id = ? AND user_id = ?) "
                  "ON CONFLICT (case_id, agent_key) DO UPDATE SET messages = excluded.messages, updated_at = excluded.updated_at",
                  (case_id, user_id, agent_key, messages_json, now(), case_id, user_id))


# ---- usage log ----------------------------------------------------------------------------

USAGE_FIELDS = ("agent", "label", "member", "requests", "input_tokens", "cached_input_tokens", "cache_write_tokens",
                "output_tokens", "reasoning_tokens", "cost_usd", "seconds", "ok", "error", "from_cache")


def add_usage(user_id: int, case_id: int | None, run_id: str, kind: str, record: dict[str, Any]) -> None:
    values = [record.get(f) for f in USAGE_FIELDS]
    with connect() as c:
        c.execute(f"INSERT INTO usage_log (user_id, case_id, run_id, kind, {', '.join(USAGE_FIELDS)}, created_at) "
                  f"VALUES (?, ?, ?, ?, {', '.join('?' for _ in USAGE_FIELDS)}, ?)", (user_id, case_id, run_id, kind, *values, now()))


def list_usage(user_id: int, case_id: int) -> list[dict[str, Any]]:
    with connect() as c:
        rows = c.execute("SELECT * FROM usage_log WHERE case_id = ? AND user_id = ? ORDER BY id", (case_id, user_id)).fetchall()
        return [dict(r) for r in rows]


# ---- delete everything --------------------------------------------------------------------

def delete_all_user_data(user_id: int, *, delete_account: bool = False) -> dict[str, Any]:
    """Profiles, questionnaire answers, cases, files, reports and chat. Returns what was
    removed plus the run ids and file hashes so their copies on disk can be removed too."""
    with connect() as c:
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id = ?", (user_id,)).fetchone()[0]
                  for t in ("profiles", "cases", "files", "chat_messages")}
        runs = [r[0] for r in c.execute("SELECT run_id FROM cases WHERE user_id = ? AND run_id IS NOT NULL", (user_id,))]
        hashes = [r[0] for r in c.execute("SELECT DISTINCT sha256 FROM files WHERE user_id = ?", (user_id,))]
        for table in ("usage_log", "chat_memory", "chat_messages", "files", "cases", "profiles"):
            c.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        if delete_account:
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return {"counts": counts, "run_ids": runs, "file_hashes": hashes}
