"""Background case runs and their live events.

Runs are started by the case API (api.py), never directly: the run registry here has no
HTTP routes of its own, so events and results are only reachable through endpoints that
check the logged-in user owns the case.

Every finished run is saved to storage/runs/<run_id>/ (result, audit trail, events);
storage/ is never committed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any, AsyncIterator, Awaitable, Callable

from . import config
from .events import RunEvents
from .panel import new_run, run_case
from .schemas import Questionnaire

RUNS: dict[str, RunEvents] = {}
TASKS: set[asyncio.Task] = set()
RUNS_DIR = config.REPO_ROOT / "storage" / "runs"


async def start_run(user_id: str, case_id: str, questionnaire: Questionnaire, files: list[tuple[str, bytes]],
                    on_done: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
                    use_cache: bool = True, on_call: Callable[[str, Any], None] | None = None) -> str:
    """`on_call(run_id, record)` receives every model call, for the usage log."""
    events = new_run(user_id, case_id)
    RUNS[events.run_id] = events

    async def job() -> None:
        try:
            result = await run_case(user_id=user_id, case_id=case_id, questionnaire=questionnaire, files=files,
                                    events=events, use_cache=use_cache,
                                    on_call=(lambda rec: on_call(events.run_id, rec)) if on_call else None)
        except Exception as exc:  # run_case handles its own errors; this is a last resort
            result = {"run_id": events.run_id, "status": "failed", "stop_reason": f"{type(exc).__name__}: {exc}"}
            if not events.finished:
                events.emit("error", agent="run", message=result["stop_reason"])
                events.emit("final", status="failed", stop_reason=result["stop_reason"], emergency=None)
        events.save(RUNS_DIR / events.run_id, result, {"status": result.get("status"), "stop_reason": result.get("stop_reason")})
        if on_done:
            maybe = on_done(result)
            if asyncio.iscoroutine(maybe):
                await maybe

    task = asyncio.create_task(job())
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return events.run_id


async def stream_events(run_id: str, owner_id: str) -> AsyncIterator[str]:
    """SSE lines for one run: past events, then live ones. Falls back to the saved log
    after a server restart. The caller has already checked the user owns the case."""
    yield "retry: 3000\n\n"
    events = RUNS.get(run_id)
    if events is None or events.user_id != owner_id:
        log = RUNS_DIR / run_id / "events.jsonl"
        if log.is_file():
            for line in log.read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {line}\n\n"
        yield "event: end\ndata: {}\n\n"
        return
    queue = events.subscribe()
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=15)
        except asyncio.TimeoutError:
            yield ": keep-alive\n\n"
            continue
        if event is None:
            yield "event: end\ndata: {}\n\n"
            return
        yield f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"


def is_running(run_id: str | None) -> bool:
    return bool(run_id and run_id in RUNS and not RUNS[run_id].finished)


def forget_runs(run_ids: list[str]) -> None:
    """Remove runs from memory and their saved copies on disk (delete my data)."""
    for run_id in run_ids:
        RUNS.pop(run_id, None)
        if run_id and all(ch.isalnum() or ch == "-" for ch in run_id):
            shutil.rmtree(RUNS_DIR / run_id, ignore_errors=True)
