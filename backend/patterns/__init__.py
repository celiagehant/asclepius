"""The pattern library: well-known cross-specialty patterns, kept as data (patterns.json).

It is rendered once into a compact text block that opens the instructions of every panel
agent, so all of them share it as one cached prompt prefix. It is a starting point for the
panel, never a limit and never a diagnosis.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).resolve().parent / "patterns.json"


@lru_cache(maxsize=1)
def load() -> list[dict]:
    return json.loads(FILE.read_text())["patterns"]


def by_id() -> dict[str, dict]:
    return {p["id"]: p for p in load()}


@lru_cache(maxsize=1)
def library_block() -> str:
    lines = [
        "# Pattern library (shared by the whole panel)",
        "",
        "Well-known patterns doctors consider when findings from different body systems line up.",
        "Use it as a starting point, not a limit: you may propose a connection that is not listed",
        "(mark it panel-proposed). A pattern is something to discuss with a doctor, never a",
        "diagnosis, and it only applies when findings on the case board support it.",
        "",
    ]
    for p in load():
        parts = [f"{p['id']} {p['name']}", "systems: " + ", ".join(p["systems"]), "clues: " + "; ".join(p["clues"]),
                 "considered by: " + ", ".join(p["specialties"]), "often confused with: " + "; ".join(p["often_confused_with"]),
                 "doctors may check: " + "; ".join(p["what_doctors_may_check"])]
        if p.get("notes"):
            parts.append("note: " + p["notes"])
        lines.append(" | ".join(parts))
    return "\n".join(lines) + "\n\n---\n\n"
