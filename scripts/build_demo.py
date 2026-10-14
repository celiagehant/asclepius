"""Pack the offline demo into ONE self-contained HTML file that opens with a double-click.

    .venv/bin/python scripts/build_demo.py              # rebuild the frontend demo bundle, then pack
    .venv/bin/python scripts/build_demo.py --no-build   # reuse frontend/dist-demo (no Node needed)

Inputs:
  output/demo/recordings/*.json    real runs recorded by scripts/record_demo.py
  data/test_cases/*/documents      the synthetic records (images embedded as data URIs)
  output/tokenomics/results.json   measured cost numbers for the headline
  output/safety/results.json       measured safety numbers for the headline
  frontend/dist-demo               the demo build (one JavaScript file, one CSS file)

Output: case_conference_demo.html in the repo folder. It needs no server, no internet, no
login and no API key, contains only synthetic data, and can be emailed or shared as is.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.documents import read_path  # noqa: E402
from backend.llm import PRICES_PER_1M  # noqa: E402
from backend.registry import ROSTER  # noqa: E402

REC = ROOT / "output" / "demo" / "recordings"
DIST = ROOT / "frontend" / "dist-demo"
OUT = ROOT / "case_conference_demo.html"
FAVICON = ("data:image/svg+xml;base64," + base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#0f3d4c"/>'
    b'<circle cx="11" cy="13" r="4" fill="#7fd1c7"/><circle cx="21" cy="13" r="4" fill="#7fd1c7"/><circle cx="16" cy="21" r="4" fill="#fff"/></svg>').decode())


def data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def pdf_page_image(path: Path) -> str:
    import pypdfium2 as pdfium
    img = pdfium.PdfDocument(path.read_bytes())[0].render(scale=1.4).to_pil().convert("RGB")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def documents(case_id: str, result: dict) -> list[dict]:
    seen = {d["filename"]: d for d in (result.get("intake") or {}).get("documents", [])}
    docs = []
    for path in sorted((ROOT / "data" / "test_cases" / case_id / "documents").iterdir()):
        if path.name.startswith("."):
            continue
        local = read_path(path)
        rec = seen.get(path.name, {})
        image = None
        if path.suffix in (".png", ".jpg", ".jpeg"):
            image = data_uri(path)
        elif path.name.endswith("_scanned.pdf"):
            image = pdf_page_image(path)
        kind = {"pdf": "scanned PDF" if image else "PDF", "image": "image", "text": "text"}[local.kind]
        docs.append({"name": path.name, "kind": kind, "read_by": rec.get("read_by", local.read_by),
                     "text": rec.get("text") or local.text, "image": image,
                     "hidden_text": [h["label"] for h in rec.get("hidden_text", [])]})
    return docs


def usage(rec: dict) -> dict:
    """The same shape as GET /api/cases/{id}/usage, from the recorded run and chat."""
    keys = ("requests", "input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "cost_usd")
    runs = []
    panel_calls = [{**c, "id": i} for i, c in enumerate(rec["result"]["usage"]["calls"], start=1)]
    groups = [("panel", rec["result"]["run_id"], rec["recorded_at"], panel_calls)]
    chat_by_run: dict[str, list] = {}
    for row in rec.get("chat_usage", []):
        chat_by_run.setdefault(row["run_id"], []).append(row)
    groups += [("chat", rid, rows[0]["created_at"], rows) for rid, rows in chat_by_run.items()]
    for kind, rid, started, calls in groups:
        totals = {k: sum(c.get(k) or 0 for c in calls) for k in keys}
        totals["cost_usd"] = round(totals["cost_usd"], 6)
        runs.append({"run_id": rid, "kind": kind, "started": started, "calls": calls, "totals": totals})
    return {"runs": runs, "prices_per_1m": {k: float(v) for k, v in PRICES_PER_1M.items()}}


def slim_result(result: dict) -> dict:
    keep = ("run_id", "status", "stop_reason", "seconds", "modes", "emergency", "summary", "specialists", "pharmacist",
            "round2", "consult")
    out = {k: result.get(k) for k in keep}
    out["usage"] = {"totals": result["usage"]["totals"]}
    return out


def age(dob: str | None, fallback: int | None) -> int:
    if not dob:
        return fallback or 0
    b = date.fromisoformat(dob)
    t = date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def headline() -> dict:
    tok = json.loads((ROOT / "output" / "tokenomics" / "results.json").read_text())
    avg = lambda rs: sum(r["totals"]["cost_usd"] for r in rs) / len(rs)  # noqa: E731
    on = [r for r in tok if r["setting"] == "cache_on"]
    off = [r for r in tok if r["setting"] == "cache_off"]
    per_case = avg(on)
    monthly = 2 * per_case + 15 * 0.0011
    saf = json.loads((ROOT / "output" / "safety" / "results.json").read_text())
    att = lambda mode: [r for r in saf if r["kind"] == "attack" and r["mode"] == mode]  # noqa: E731
    cln = [r for r in saf if r["kind"] == "clean" and r["mode"] == "on"]  # the app's setting (defenses on)
    tests = sum(len(re.findall(r"^def test_", p.read_text(), re.M)) for p in (ROOT / "tests").glob("test_*.py"))
    infl = lambda mode: f"{sum((r.get('influence') or {}).get('influenced', False) for r in att(mode))} of {len(att(mode))}"  # noqa: E731
    return {"cost_per_case": round(per_case, 5), "caching_saving": round(1 - per_case / avg(off), 3),
            "monthly_per_user": round(monthly, 4), "monthly_10k": round(monthly * 10_000, 0),
            "attacks_succeeded_on": f"{sum(r['succeeded'] for r in att('on'))} of {len(att('on'))}",
            "influenced_off": infl("off"), "influenced_on": infl("on"),
            "clean_blocked": f"{sum(r['wrongly_blocked'] for r in cln)} of {len(cln)}", "tests": tests}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args()
    recordings = sorted(REC.glob("*.json"))
    if not recordings:
        sys.exit("No recordings found. Run scripts/record_demo.py first.")
    if not args.no_build:
        subprocess.run(["npm", "run", "build:demo"], cwd=ROOT / "frontend", check=True)

    cases = []
    for path in recordings:
        rec = json.loads(path.read_text())
        p = rec["profile"]
        cases.append({"case_id": rec["case_id"], "case_title": rec["case_title"], "case_summary": rec["case_summary"],
                      "recorded_at": rec["recorded_at"], "profile": p, "age": age(p.get("date_of_birth"), p.get("age_years")),
                      "main_concern": rec["main_concern"], "documents": documents(rec["case_id"], rec["result"]),
                      "result": slim_result(rec["result"]), "events": rec["events"],
                      "chat": [{"question": c["question"], "message": c["message"], "seconds": c["seconds"], "events": []} for c in rec["chat"]],
                      "usage": usage(rec)})
    data = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "author": "Celia Gehant",
            "course": "MGT 409, AI Foundations for Managers (Yale SOM)", "model": "gpt-6-luna",
            "roster": [{"id": s.id, "name": s.name, "tier": s.tier, "scope": s.scope} for s in ROSTER],
            "headline": headline(), "cases": cases}

    html = (DIST / "demo.html").read_text()
    css = "".join(p.read_text() for p in sorted((DIST / "assets").glob("*.css")))
    js_files = sorted((DIST / "assets").glob("*.js"))
    if len(js_files) != 1:
        sys.exit(f"Expected one JavaScript file in {DIST}/assets, found {len(js_files)}.")
    js = js_files[0].read_text().replace("</script", "<\\/script")
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = re.sub(r'<script type="module"[^>]*src="[^"]+"[^>]*></script>\s*', "", html)
    html = re.sub(r'<link rel="stylesheet"[^>]*>\s*', "", html)
    html = re.sub(r'<link rel="modulepreload"[^>]*>\s*', "", html)
    html = html.replace("</head>", f'    <link rel="icon" href="{FAVICON}" />\n    <style>{css}</style>\n  </head>')
    html = html.replace("</body>", f"    <script>window.__CC_DEMO__ = {payload};</script>\n"
                                   f"    <script type=\"module\">{js}</script>\n  </body>")
    OUT.write_text(html)
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB, {len(cases)} cases, no external files)")


if __name__ == "__main__":
    main()
