"""The user-facing API. Every endpoint requires a logged-in user and every database call is
filtered by that user's id (see db.py); another user's profile, case, file or run is
always "not found".

Profiles  GET/POST /api/profiles, GET/PUT/DELETE /api/profiles/{id}
Safety    POST /api/emergency-check
Cases     GET/POST /api/cases, GET/DELETE /api/cases/{id}, PUT /api/cases/{id}
Files     POST /api/cases/{id}/files (multipart), DELETE /api/cases/{id}/files/{file_id}
Panel     POST /api/cases/{id}/convene, GET /api/cases/{id}/events (SSE)
Chat      GET /api/cases/{id}/chat, POST /api/cases/{id}/chat (SSE: routing, answering, safety, final)
Demo      POST /api/demo/{demo_id}  (adds a synthetic demo patient and case to this account)
Privacy   POST /api/me/delete-data
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from . import chat, config, db, llm, runs, safety
from .auth import current_user
from .documents import UnsupportedFile, read_document
from .intake import CACHE_DIR
from .profiles import ProfileError, from_demo, to_questionnaire, validate_profile
from .schemas import ProfileData

router = APIRouter(prefix="/api")
MAX_FILES_PER_CASE = 12


def _not_found(what: str = "Not found."):
    return HTTPException(404, what)


def _validated(data: dict) -> ProfileData:
    try:
        return validate_profile(ProfileData.model_validate(data))
    except ValidationError as exc:
        first = exc.errors()[0]
        raise HTTPException(422, f"Please check '{'.'.join(str(x) for x in first['loc'])}': {first['msg']}")
    except ProfileError as exc:
        raise HTTPException(422, str(exc))


def _profile_view(p: dict) -> dict:
    data = ProfileData.model_validate(p["data"])
    return {**p, "age": data.age_on(date.today()), "pediatric": (data.age_on(date.today()) or 99) < 18}


# ---- profiles -------------------------------------------------------------------------------

@router.get("/profiles")
def list_profiles(user: dict = Depends(current_user)) -> list[dict]:
    return [_profile_view(p) for p in db.list_profiles(user["id"])]


@router.post("/profiles")
def create_profile(body: dict, user: dict = Depends(current_user)) -> dict:
    profile = _validated(body)
    pid = db.create_profile(user["id"], profile.model_dump())
    return {**_profile_view(db.get_profile(user["id"], pid)), "emergency": safety.emergency_check(profile.main_concern)}


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: int, user: dict = Depends(current_user)) -> dict:
    p = db.get_profile(user["id"], profile_id)
    if not p:
        raise _not_found("No such profile.")
    return _profile_view(p)


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, body: dict, user: dict = Depends(current_user)) -> dict:
    profile = _validated(body)
    if not db.update_profile(user["id"], profile_id, profile.model_dump()):
        raise _not_found("No such profile.")
    return {**_profile_view(db.get_profile(user["id"], profile_id)), "emergency": safety.emergency_check(profile.main_concern)}


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: int, user: dict = Depends(current_user)) -> dict:
    if not db.get_profile(user["id"], profile_id):
        raise _not_found("No such profile.")
    runs.forget_runs(db.delete_profile(user["id"], profile_id))
    return {"ok": True}


# ---- emergency check --------------------------------------------------------------------------

class TextIn(BaseModel):
    text: str = Field(max_length=5000)


@router.post("/emergency-check")
def emergency_check(body: TextIn, user: dict = Depends(current_user)) -> dict:
    return safety.emergency_check(body.text)


# ---- cases ------------------------------------------------------------------------------------

class CaseIn(BaseModel):
    profile_id: int
    title: str = Field(default="", max_length=120)
    main_concern: str | None = Field(default=None, max_length=3000)


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    main_concern: str | None = Field(default=None, max_length=3000)


@router.get("/cases")
def list_cases(user: dict = Depends(current_user)) -> list[dict]:
    return db.list_cases(user["id"])


@router.post("/cases")
def create_case(body: CaseIn, user: dict = Depends(current_user)) -> dict:
    profile = db.get_profile(user["id"], body.profile_id)
    if not profile:
        raise HTTPException(400, "Complete the health questionnaire for this person first.")
    concern = body.main_concern if body.main_concern is not None else profile["data"].get("main_concern", "")
    title = body.title.strip() or f"Case for {profile['data']['name']} ({date.today():%b %d, %Y})"
    case_id = db.create_case(user["id"], body.profile_id, title, concern)
    return _case_view(user["id"], case_id)


def _case_view(user_id: int, case_id: int) -> dict:
    case = db.get_case(user_id, case_id, with_result=True)
    if not case:
        raise _not_found("No such case.")
    case["files"] = db.list_files(user_id, case_id)
    case["running"] = runs.is_running(case["run_id"])
    return case


@router.get("/cases/{case_id}")
def get_case(case_id: int, user: dict = Depends(current_user)) -> dict:
    return _case_view(user["id"], case_id)


@router.put("/cases/{case_id}")
def update_case(case_id: int, body: CaseUpdate, user: dict = Depends(current_user)) -> dict:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields and not db.update_case(user["id"], case_id, **fields):
        raise _not_found("No such case.")
    return {**_case_view(user["id"], case_id), "emergency": safety.emergency_check(body.main_concern or "")}


@router.delete("/cases/{case_id}")
def delete_case(case_id: int, user: dict = Depends(current_user)) -> dict:
    if not db.get_case(user["id"], case_id):
        raise _not_found("No such case.")
    run_id = db.delete_case(user["id"], case_id)
    runs.forget_runs([run_id] if run_id else [])
    return {"ok": True}


# ---- files ------------------------------------------------------------------------------------

@router.post("/cases/{case_id}/files")
async def upload_files(case_id: int, files: list[UploadFile] = File(...), user: dict = Depends(current_user)) -> dict:
    case = db.get_case(user["id"], case_id)
    if not case:
        raise _not_found("No such case.")
    if case["status"] not in ("draft", "failed", "interrupted", "partial", "complete"):
        raise HTTPException(409, "The panel is reviewing this case; add files when it is done.")
    existing = db.list_files(user["id"], case_id)
    accepted, rejected = [], []
    for upload in files:
        data = await upload.read()
        name = (upload.filename or "document").replace("/", "_").replace("\\", "_")[:120]
        if len(existing) + len(accepted) >= MAX_FILES_PER_CASE:
            rejected.append({"filename": name, "reason": f"At most {MAX_FILES_PER_CASE} files per case."})
            continue
        try:
            doc = read_document(name, data)  # local only: type check, visible text, hidden-text flags
        except UnsupportedFile as exc:
            rejected.append({"filename": name, "reason": str(exc)})
            continue
        info = {"read_by": doc.read_by, "pages": doc.page_count, "notes": doc.notes,
                "hidden_text": [{"label": f.label, "chars": f.char_count, "page": f.page} for f in doc.hidden_text]}
        fid = db.add_file(user["id"], case_id, name, doc.sha256, doc.kind, info, data)
        accepted.append({"id": fid, "filename": name, "kind": doc.kind, "info": info})
    return {"accepted": accepted, "rejected": rejected, "files": db.list_files(user["id"], case_id)}


@router.delete("/cases/{case_id}/files/{file_id}")
def delete_file(case_id: int, file_id: int, user: dict = Depends(current_user)) -> dict:
    if not db.delete_file(user["id"], case_id, file_id):
        raise _not_found("No such file.")
    return {"ok": True}


# ---- convene the panel ----------------------------------------------------------------------

class ConveneIn(BaseModel):
    profile_confirmed: bool
    main_concern: str | None = Field(default=None, max_length=3000)


@router.post("/cases/{case_id}/convene")
async def convene(case_id: int, body: ConveneIn, user: dict = Depends(current_user)) -> dict:
    uid = user["id"]
    case = db.get_case(uid, case_id)
    if not case:
        raise _not_found("No such case.")
    if runs.is_running(case["run_id"]):
        raise HTTPException(409, "The panel is already reviewing this case.")
    if not body.profile_confirmed:
        raise HTTPException(400, "Please confirm the health profile is still up to date first.")
    if not config.KEY_STATUS.loaded:
        raise HTTPException(503, config.KEY_STATUS.message)
    files = db.file_contents(uid, case_id)
    if not files:
        raise HTTPException(400, "Add at least one medical record first.")
    profile = db.get_profile(uid, case["profile_id"])
    if not profile:
        raise _not_found("The profile for this case no longer exists.")
    db.confirm_profile(uid, profile["id"])
    concern = body.main_concern if body.main_concern is not None else case["main_concern"]
    questionnaire = to_questionnaire(ProfileData.model_validate(profile["data"]), concern)

    async def on_done(result: dict) -> None:
        db.update_case(uid, case_id, status=result.get("status", "failed"), result=result,
                       cost_usd=(result.get("usage") or {}).get("totals", {}).get("cost_usd"))

    run_id = await runs.start_run(str(uid), f"case-{case_id}", questionnaire, files, on_done=on_done,
                                  on_call=lambda rid, rec: db.add_usage(uid, case_id, rid, "panel", asdict(rec)))
    db.update_case(uid, case_id, status="running", run_id=run_id, main_concern=concern, result=None,
                   profile_snapshot=profile["data"])
    return {"run_id": run_id, "emergency": safety.emergency_check(concern)}


@router.get("/cases/{case_id}/events")
async def case_events(case_id: int, user: dict = Depends(current_user)) -> StreamingResponse:
    case = db.get_case(user["id"], case_id)
    if not case or not case["run_id"]:
        raise _not_found("This case has no panel run yet.")
    return StreamingResponse(runs.stream_events(case["run_id"], str(user["id"])), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- run details (usage log) ----------------------------------------------------------------

@router.get("/cases/{case_id}/usage")
def case_usage(case_id: int, user: dict = Depends(current_user)) -> dict:
    """Every model call for this case (panel runs and chat), with tokens, cost and latency."""
    if not db.get_case(user["id"], case_id):
        raise _not_found("No such case.")
    rows = db.list_usage(user["id"], case_id)
    runs_: dict[str, dict] = {}
    for r in rows:
        g = runs_.setdefault(r["run_id"], {"run_id": r["run_id"], "kind": r["kind"], "started": r["created_at"], "calls": [],
                                            "totals": {k: 0 for k in ("requests", "input_tokens", "cached_input_tokens",
                                                                      "cache_write_tokens", "output_tokens", "cost_usd")}})
        g["calls"].append(r)
        for k in g["totals"]:
            g["totals"][k] += r[k] or 0
    for g in runs_.values():
        g["totals"]["cost_usd"] = round(g["totals"]["cost_usd"], 6)
    return {"runs": list(runs_.values()), "prices_per_1m": {k: float(v) for k, v in llm.PRICES_PER_1M.items()},
            "price_source": llm.PRICE_SOURCE}


# ---- chat with the panel ----------------------------------------------------------------------

CHATTING: set[tuple[int, int]] = set()


class ChatIn(BaseModel):
    message: str = Field(max_length=chat.MAX_QUESTION_CHARS)


@router.get("/cases/{case_id}/chat")
def chat_history(case_id: int, user: dict = Depends(current_user)) -> dict:
    case = db.get_case(user["id"], case_id, with_result=True)
    if not case:
        raise _not_found("No such case.")
    members = chat.panel_members(case["result"]) if case["result"] and case["result"].get("specialists") else []
    return {"messages": db.list_chat(user["id"], case_id), "available": bool(members), "members": members,
            "busy": (user["id"], case_id) in CHATTING}


@router.post("/cases/{case_id}/chat")
async def chat_ask(case_id: int, body: ChatIn, user: dict = Depends(current_user)) -> StreamingResponse:
    uid = user["id"]
    if not db.get_case(uid, case_id):
        raise _not_found("No such case.")
    if (uid, case_id) in CHATTING:
        raise HTTPException(409, "The panel is still answering your last question.")
    events = chat.new_chat_events(uid, case_id)
    queue = events.subscribe()
    CHATTING.add((uid, case_id))

    async def job() -> None:
        try:
            await chat.answer_question(user_id=uid, case_id=case_id, question=body.message, events=events)
        except chat.ChatError as exc:
            events.emit("error", agent="chat", message=str(exc))
            events.emit("final", status="error", message=None, error=str(exc))
        except Exception as exc:  # never leave the stream hanging
            events.emit("error", agent="chat", message=f"Something went wrong ({type(exc).__name__}). Please try again.")
            events.emit("final", status="error", message=None, error=type(exc).__name__)
        finally:
            CHATTING.discard((uid, case_id))

    task = asyncio.create_task(job())
    runs.TASKS.add(task)
    task.add_done_callback(runs.TASKS.discard)

    async def stream():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                yield "event: end\ndata: {}\n\n"
                return
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- demo patients (synthetic) --------------------------------------------------------------

@router.post("/demo/{demo_id}")
def load_demo(demo_id: str, user: dict = Depends(current_user)) -> dict:
    case_dir = config.TEST_CASES_DIR / demo_id
    if not demo_id.replace("_", "").isalnum() or not (case_dir / "profile.json").is_file():
        raise _not_found("No such demo patient.")
    raw = json.loads((case_dir / "profile.json").read_text())
    profile, concern = from_demo(raw)
    pid = db.create_profile(user["id"], profile.model_dump())
    case_id = db.create_case(user["id"], pid, f"Demo: {raw['case_title']}", concern)
    for f in sorted((case_dir / "documents").iterdir()):
        if f.name.startswith("."):
            continue
        doc = read_document(f.name, f.read_bytes())
        info = {"read_by": doc.read_by, "pages": doc.page_count, "notes": doc.notes,
                "hidden_text": [{"label": h.label, "chars": h.char_count, "page": h.page} for h in doc.hidden_text]}
        db.add_file(user["id"], case_id, f.name, doc.sha256, doc.kind, info, f.read_bytes())
    return {"profile_id": pid, "case_id": case_id}


# ---- delete all my data ---------------------------------------------------------------------

class DeleteIn(BaseModel):
    confirm: str
    delete_account: bool = False


@router.post("/me/delete-data")
def delete_my_data(body: DeleteIn, user: dict = Depends(current_user)) -> dict:
    if body.confirm.strip().upper() != "DELETE":
        raise HTTPException(400, 'Type DELETE to confirm.')
    if any(runs.is_running(c["run_id"]) for c in db.list_cases(user["id"])):
        raise HTTPException(409, "A panel review is still running. Please wait for it to finish, then delete.")
    removed = db.delete_all_user_data(user["id"], delete_account=body.delete_account)
    runs.forget_runs(removed["run_ids"])
    for sha in removed["file_hashes"]:  # derived text of the user's files in the intake cache
        for cached in CACHE_DIR.glob(f"{sha}_*.json"):
            cached.unlink(missing_ok=True)
    return {"ok": True, "removed": removed["counts"], "account_deleted": body.delete_account}
