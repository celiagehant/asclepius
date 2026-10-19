"""FastAPI app: the JSON API under /api, plus the built React app at every other path.

Start it from the repo folder with `python run.py` (or
`.venv/bin/uvicorn backend.main:app --port 8000`) and open http://localhost:8000.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .api import router as api_router
from .auth import router as auth_router

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    if config.KEY_STATUS.loaded:
        log.info("%s Model: %s", config.KEY_STATUS.message, config.MODEL_ID)
    else:
        # Keep serving so the browser can show the same message, but make it loud here.
        log.error(config.missing_key_banner())
    yield


app = FastAPI(title="Case Conference", version="0.4.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(api_router)


@app.get("/api/health")
def health(ping: bool = False) -> JSONResponse:
    """Model name and key status. `?ping=true` also makes one tiny model call."""
    body: dict = {
        "app": "Case Conference",
        "version": app.version,
        "model": config.MODEL_ID,
        "provider": "Portkey (OpenAI-compatible Responses API)",
        "key_loaded": config.KEY_STATUS.loaded,
        "key_source": config.KEY_STATUS.source,
        "message": config.KEY_STATUS.message,
        "status": "ok" if config.KEY_STATUS.loaded else "missing_key",
        "public_demo": config.PUBLIC_DEMO,
    }
    if ping and config.KEY_STATUS.loaded:
        started = time.perf_counter()
        try:
            r = config.sync_client().responses.create(
                model=config.MODEL_ID, input="Reply with the single word: ready", max_output_tokens=64
            )
            body["ping"] = {
                "ok": True,
                "reply": r.output_text.strip(),
                "seconds": round(time.perf_counter() - started, 2),
                "input_tokens": r.usage.input_tokens,
                "output_tokens": r.usage.output_tokens,
            }
        except Exception as exc:  # report, don't crash the health check
            body["ping"] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            body["status"] = "model_unreachable"
    return JSONResponse(body, status_code=200 if body["status"] == "ok" else 503)


def _read_profile(case_dir) -> dict:
    return json.loads((case_dir / "profile.json").read_text())


@app.get("/api/roster")
def roster() -> list[dict]:
    """The full panel roster (from backend/registry.py), for the panel view, plus the lifestyle agent,
    which sits at every table."""
    from .registry import ROSTER
    return [{"id": s.id, "name": s.name, "tier": s.tier, "scope": s.scope} for s in ROSTER] + [
        {"id": "lifestyle", "name": "Lifestyle & prevention", "tier": "always",
         "scope": "Always on: lifestyle facts for the case board and safe self-care steps with sources."},
    ]


@app.get("/api/demo-cases")
def demo_cases() -> list[dict]:
    """The synthetic demo patients shipped in data/test_cases."""
    cases = []
    for case_dir in sorted(p for p in config.TEST_CASES_DIR.iterdir() if (p / "profile.json").is_file()):
        profile = _read_profile(case_dir)
        docs = sorted(f.name for f in (case_dir / "documents").iterdir() if not f.name.startswith("."))
        cases.append(
            {
                "id": case_dir.name,
                "title": profile["case_title"],
                "patient": profile["patient"]["name"],
                "age_years": profile["patient"]["age_years"],
                "sex": profile["patient"]["sex_at_birth"],
                "summary": profile["case_summary_for_demo"],
                "documents": docs,
            }
        )
    return cases


@app.get("/api/demo-cases/{case_id}")
def demo_case(case_id: str) -> dict:
    case_dir = config.TEST_CASES_DIR / case_id
    if not case_id.replace("_", "").isalnum() or not (case_dir / "profile.json").is_file():
        raise HTTPException(404, "No demo case with that id.")
    return _read_profile(case_dir)


# ---- the built React app -------------------------------------------------------------

if (config.FRONTEND_DIST / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Unknown API route.")
        candidate = (config.FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and config.FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)
        # The page itself must never be reused from the browser's cache: after an update it points
        # to new script files (their names change with every build), so an old copy would keep
        # showing the old app. The script files under /assets can be cached; their names are unique.
        return FileResponse(config.FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache, must-revalidate"})

else:

    @app.get("/", include_in_schema=False)
    def no_build() -> HTMLResponse:
        return HTMLResponse(
            "<h1>Case Conference</h1><p>The frontend build (frontend/dist) is missing. "
            "Run <code>cd frontend && npm install && npm run build</code>, then reload.</p>"
            "<p>The API is up: <a href='/api/health'>/api/health</a></p>"
        )
