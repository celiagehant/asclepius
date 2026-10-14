"""Live events and the audit trail for one case run.

Every step emits an event (document routed, specialist started/done, tool call, conference
round, comment, coordinator thinking, safety check, spend, final, error). Events go to any
number of subscribers (the browser via SSE, the CLI printer) and are kept for replay.

The audit trail records each agent: what it was given (document names, not contents),
each tool call with a short result, its usage, and why it stopped.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

EventType = Literal[
    "run_started", "document_routed", "panel_selected", "specialist_started", "tool_call", "specialist_done",
    "conference_round", "comment", "coordinator_thinking", "safety_check", "spend", "final", "error",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AgentAudit:
    agent_id: str
    agent: str          # specialist / pharmacist / coordinator / safety_reviewer / intake
    specialty: str | None
    round: int | None
    inputs: list[str] = field(default_factory=list)   # document names or input descriptions
    started: str = field(default_factory=now_iso)
    finished: str | None = None
    status: str = "running"  # completed / failed / skipped
    stop_reason: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    output_summary: str | None = None


@dataclass
class RunEvents:
    run_id: str
    user_id: str
    case_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    agents: dict[str, AgentAudit] = field(default_factory=dict)
    printers: list[Callable[[dict[str, Any]], None]] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)
    finished: bool = False
    _queues: list[asyncio.Queue] = field(default_factory=list)

    # ---- events --------------------------------------------------------------------------
    def emit(self, type_: EventType, **data: Any) -> dict[str, Any]:
        event = {"seq": len(self.events) + 1, "type": type_, "t": round(time.perf_counter() - self.started_at, 2), **data}
        self.events.append(event)
        for q in self._queues:
            q.put_nowait(event)
        for p in self.printers:
            p(event)
        if type_ == "final":
            self.finished = True
            for q in self._queues:
                q.put_nowait(None)  # end of stream
        return event

    def subscribe(self) -> asyncio.Queue:
        """A queue that first replays past events, then receives live ones (None = done)."""
        q: asyncio.Queue = asyncio.Queue()
        for e in self.events:
            q.put_nowait(e)
        if self.finished:
            q.put_nowait(None)
        else:
            self._queues.append(q)
        return q

    # ---- audit ---------------------------------------------------------------------------
    def agent_started(self, agent_id: str, agent: str, specialty: str | None, round_: int | None, inputs: list[str]) -> AgentAudit:
        a = AgentAudit(agent_id, agent, specialty, round_, inputs)
        self.agents[agent_id] = a
        return a

    def agent_finished(self, agent_id: str, status: str, stop_reason: str, output_summary: str | None = None,
                       validation: dict[str, Any] | None = None) -> None:
        a = self.agents[agent_id]
        a.finished, a.status, a.stop_reason = now_iso(), status, stop_reason
        a.output_summary = output_summary
        if validation:
            a.validation.update(validation)

    def audit_dict(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "user_id": self.user_id, "case_id": self.case_id,
            "agents": [a.__dict__ for a in self.agents.values()],
            "tool_calls_total": sum(len(a.tool_calls) for a in self.agents.values()),
            **(extra or {}),
        }

    def save(self, folder: Path, result: dict[str, Any], extra_audit: dict[str, Any] | None = None) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "result.json").write_text(json.dumps(result, indent=2))
        (folder / "audit.json").write_text(json.dumps(self.audit_dict(extra_audit), indent=2))
        (folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in self.events) + "\n")
