"""Trusted medical sources for the panel, as an MCP server (stdio).

Tools (no API keys needed):
  search_pubmed       PubMed via NCBI E-utilities: title, journal, year, link, short abstract
  search_medlineplus  MedlinePlus health topics (NLM): title, link, short summary
  fda_label_search    FDA drug labels via openFDA: label sections, or the sentences that
                      mention given terms (e.g. another drug's name)

There is no open web search. Every tool returns JSON with a "status" field:
"ok", "no_results" or "unreachable". If a source cannot be reached, the tool says so
instead of failing, and the agent must tell the user.

Set CC_SIMULATE_OUTAGE=pubmed,medlineplus,openfda to test the unreachable path.

Run standalone (for debugging):  .venv/bin/python mcp_server/server.py
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

TIMEOUT = httpx.Timeout(8.0, connect=5.0)
USER_AGENT = "CaseConference/0.3 (educational project; MGT 409)"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MEDLINEPLUS = "https://wsearch.nlm.nih.gov/ws/query"
OPENFDA = "https://api.fda.gov/drug/label.json"
FDA_SECTIONS = [
    "boxed_warning", "contraindications", "drug_interactions", "warnings_and_cautions", "warnings",
    "precautions", "use_in_specific_populations", "pregnancy", "pediatric_use", "geriatric_use",
]

logging.getLogger("httpx").setLevel(logging.WARNING)  # stdout is the MCP channel; keep stderr quiet

app = MCPServer(
    "case-conference-sources",
    instructions="Trusted medical sources only: PubMed, MedlinePlus and FDA drug labels. No open web search.",
)
_cache: dict[str, str] = {}
_ncbi_lock = asyncio.Semaphore(2)  # NCBI allows 3 requests/second without a key


def _outage(source: str) -> bool:
    return source in {s.strip().lower() for s in os.environ.get("CC_SIMULATE_OUTAGE", "").split(",")}


def _clean(text: str, limit: int) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _unreachable(source: str, exc: Exception | str) -> str:
    reason = exc if isinstance(exc, str) else type(exc).__name__
    return json.dumps({"status": "unreachable", "source": source,
                       "message": f"{source} could not be reached ({reason}). Say so; do not invent a source."})


async def _get(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> httpx.Response:
    """GET with up to 3 tries when the service is rate-limiting (429) or briefly down (5xx)."""
    for attempt in range(3):
        r = await client.get(url, params=params)
        if r.status_code in (429, 500, 502, 503) and attempt < 2:
            await asyncio.sleep(0.6 * (attempt + 1))
            continue
        r.raise_for_status()
        return r
    return r


@app.tool()
async def search_pubmed(query: str, max_results: int = 3) -> str:
    """Search PubMed (peer-reviewed biomedical literature). Returns up to 5 articles with
    title, journal, year, PubMed link and a short abstract excerpt. Use short, specific
    clinical queries, e.g. "iron deficiency anemia palpitations"."""
    max_results = max(1, min(int(max_results), 5))
    key = f"pubmed|{query.lower()}|{max_results}"
    if key in _cache:
        return _cache[key]
    if _outage("pubmed"):
        return _unreachable("PubMed", "simulated outage")
    try:
        async with _ncbi_lock, httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            search = await _get(client, f"{EUTILS}/esearch.fcgi", {
                "db": "pubmed", "term": query, "retmax": max_results, "retmode": "json", "sort": "relevance",
                "tool": "case_conference"})
            ids = search.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                out = json.dumps({"status": "no_results", "source": "PubMed", "query": query, "results": []})
                _cache[key] = out
                return out
            await asyncio.sleep(0.35)
            fetch = await _get(client, f"{EUTILS}/efetch.fcgi", {
                "db": "pubmed", "id": ",".join(ids), "retmode": "xml", "tool": "case_conference"})
    except Exception as exc:
        return _unreachable("PubMed", exc)
    results = []
    for art in ET.fromstring(fetch.content).iter("PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        abstract = " ".join("".join(a.itertext()) for a in art.iter("AbstractText"))
        year = art.findtext(".//JournalIssue/PubDate/Year") or (art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")[:4]
        results.append({
            "pmid": pmid, "title": _clean(title, 220), "journal": _clean(art.findtext(".//Journal/Title") or "", 100),
            "year": year, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "abstract_excerpt": _clean(abstract, 400),
        })
    out = json.dumps({"status": "ok" if results else "no_results", "source": "PubMed", "query": query, "results": results})
    _cache[key] = out
    return out


@app.tool()
async def search_medlineplus(query: str, max_results: int = 3) -> str:
    """Search MedlinePlus health topics (U.S. National Library of Medicine), written for
    patients. Use a short topic name of 1-3 words, e.g. "anemia", "warfarin", "kidney
    tests". Returns up to 5 topics with title, link and a short summary."""
    max_results = max(1, min(int(max_results), 5))
    key = f"medlineplus|{query.lower()}|{max_results}"
    if key in _cache:
        return _cache[key]
    if _outage("medlineplus"):
        return _unreachable("MedlinePlus", "simulated outage")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            r = await _get(client, MEDLINEPLUS, {"db": "healthTopics", "term": query, "retmax": max_results})
    except Exception as exc:
        return _unreachable("MedlinePlus", exc)
    results = []
    for doc in ET.fromstring(r.content).iter("document"):
        fields = {c.get("name"): "".join(c.itertext()) for c in doc.iter("content")}
        results.append({"title": _clean(fields.get("title", ""), 150), "url": doc.get("url", ""),
                        "summary": _clean(fields.get("FullSummary") or fields.get("snippet", ""), 450)})
    out = json.dumps({"status": "ok" if results else "no_results", "source": "MedlinePlus", "query": query,
                      "results": results[:max_results]})
    _cache[key] = out
    return out


def _sentences_with(text: str, terms: list[str], limit: int) -> list[str]:
    sentences = re.split(r"(?<=[.;])\s+", _clean(text, 20000))
    lowered = [t.lower() for t in terms if t.strip()]
    hits = [s for s in sentences if any(t in s.lower() for t in lowered)]
    return [_clean(s, 450) for s in hits[:limit]]


@app.tool()
async def fda_label_search(drug: str, terms: list[str] | None = None) -> str:
    """Look up the official FDA drug label (openFDA) for one drug by generic name.
    With `terms` (e.g. other drug names or "bleeding"), returns only the label sentences
    that mention them, section by section; without terms, returns the start of the key
    safety sections. Includes a DailyMed link to the full label."""
    terms = [t for t in (terms or []) if t and t.strip()][:8]
    key = f"fda|{drug.lower()}|{'|'.join(sorted(t.lower() for t in terms))}"
    if key in _cache:
        return _cache[key]
    if _outage("openfda"):
        return _unreachable("openFDA", "simulated outage")
    name = drug.strip().lower().replace('"', "")
    # Combination products: openFDA writes "x and y"; also try each ingredient alone.
    parts = [p.strip() for p in re.split(r"\s*(?:/|\+|,| and )\s*", name) if p.strip()]
    names = [name] + ([" and ".join(parts)] + parts if len(parts) > 1 else [])
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            label = None
            for candidate in dict.fromkeys(names):
                for field in ("openfda.generic_name", "openfda.substance_name", "openfda.brand_name"):
                    r = await client.get(OPENFDA, params={"search": f'{field}:"{candidate}"', "limit": 1})
                    if r.status_code == 200 and r.json().get("results"):
                        label = r.json()["results"][0]
                        break
                    if r.status_code not in (200, 404):
                        r.raise_for_status()
                if label:
                    break
    except Exception as exc:
        return _unreachable("openFDA", exc)
    if not label:
        out = json.dumps({"status": "no_results", "source": "openFDA drug label", "drug": drug})
        _cache[key] = out
        return out
    set_id = label.get("set_id", "")
    sections: dict[str, Any] = {}
    for section in FDA_SECTIONS:
        text = " ".join(label.get(section, []))
        if not text:
            continue
        if terms:
            hits = _sentences_with(text, terms, 4)
            if hits:
                sections[section] = hits
        else:
            sections[section] = _clean(text, 500)
    out = json.dumps({
        "status": "ok", "source": "openFDA drug label", "drug": drug,
        "label_title": _clean(" / ".join(label.get("openfda", {}).get("brand_name", [])[:2]) or drug, 80),
        "url": f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}" if set_id else "https://open.fda.gov/apis/drug/label/",
        "terms": terms, "sections": sections,
        "note": "No label sentence mentions these terms." if terms and not sections else None,
    })
    _cache[key] = out
    return out


if __name__ == "__main__":
    app.run("stdio")
