"""Rounds 2 and 3 of the conference, the parts decided in code.

  round 2  every specialist proposes up to 2 connections between case-board posts
           -> validate_connections: refs must exist, at least 2 posts from at least 2 systems
           -> merge_candidates: overlapping cards become one candidate C1..Cn (at most 6)
  round 3  the skeptic challenges every candidate; the involved specialists defend,
           concede, support or challenge
           -> score_candidates: the strength label comes from this arithmetic, never from a
              model, and is never a probability

Nothing here calls a model, so every rule is covered by offline tests.
"""

from __future__ import annotations

import re
from typing import Any

from . import safety
from .patterns import by_id as pattern_by_id

MAX_CARDS_PER_MEMBER = 2
MAX_CANDIDATES = 6
MAX_REFS = 8
TOP_N = 3
PANEL_PROPOSED = "panel-proposed"
NOT_A_DIAGNOSIS = "Possible explanation to discuss with your doctor, not a diagnosis."


def _clean_list(items: list[str], limit: int) -> list[str]:
    out = []
    for x in items:
        x = re.sub(r"\s+", " ", x).strip()
        if x and not safety.violations(x) and x not in out:
            out.append(x)
    return out[:limit]


def validate_connections(member: str, cards: list[Any], posts: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Keep a member's cards that cite real posts covering at least two body systems."""
    kept, dropped = [], []
    for c in cards[:MAX_CARDS_PER_MEMBER]:
        refs = list(dict.fromkeys(r for r in c.board_refs if r in posts))
        systems = {posts[r]["system"] for r in refs}
        if len(refs) < 2:
            dropped.append({"item": c.title[:160], "reason": "needs at least 2 existing board posts", "by": member})
            continue
        if len(systems) < 2:
            dropped.append({"item": c.title[:160], "reason": "all posts are in one body system", "by": member})
            continue
        if safety.violations(c.title):
            dropped.append({"item": c.title[:160], "reason": f"forbidden language: {', '.join(safety.violations(c.title))}", "by": member})
            continue
        pid = c.pattern_id if c.pattern_id in pattern_by_id() else PANEL_PROPOSED
        kept.append({"by": member, "title": c.title.strip(), "refs": refs[:MAX_REFS], "pattern_id": pid,
                     "why_it_fits": _clean_list(c.why_it_fits, 3), "would_help_tell": _clean_list(c.would_help_tell, 2)})
    return kept, dropped


def same_candidate(a: dict, b: dict) -> bool:
    """Two cards naming the same library pattern are one candidate; two different library
    patterns never are, even if they cite the same posts (bleeding risk and kidney strain
    can share a lab value and still be two things to discuss). A panel-proposed card joins
    another card when they share at least half of all their posts."""
    pa, pb = a["pattern_id"], b["pattern_id"]
    if pa != PANEL_PROPOSED and pb != PANEL_PROPOSED:
        return pa == pb
    ra, rb = set(a["refs"]), set(b["refs"])
    return len(ra & rb) / len(ra | rb) >= 0.5


def merge_candidates(cards: list[dict], posts: dict[str, dict]) -> list[dict]:
    """Group cards that describe the same candidate (see same_candidate). Rank by number of
    proposers, then abnormal posts, then posters from different members."""
    groups: list[list[dict]] = []
    for card in cards:
        target = None
        for g in groups:
            if any(same_candidate(card, x) for x in g):
                target = g
                break
        if target is None:
            groups.append([card])
        else:
            target.append(card)
    candidates = []
    for g in groups:
        lead = max(g, key=lambda x: (len(x["refs"]), x["pattern_id"] != PANEL_PROPOSED))
        refs = list(dict.fromkeys(r for x in [lead, *g] for r in x["refs"]))[:MAX_REFS]
        pids = [x["pattern_id"] for x in g if x["pattern_id"] != PANEL_PROPOSED]
        candidates.append({
            "title": lead["title"], "refs": refs,
            "pattern_id": max(set(pids), key=pids.count) if pids else PANEL_PROPOSED,
            "proposers": list(dict.fromkeys(x["by"] for x in g)),
            "why_it_fits": _clean_list([w for x in [lead, *g] for w in x["why_it_fits"]], 4),
            "would_help_tell": _clean_list([w for x in [lead, *g] for w in x["would_help_tell"]], 3),
            "systems": sorted({posts[r]["system"] for r in refs}),
            "posters": sorted({posts[r]["by"] for r in refs}),
            "abnormal_refs": sum(1 for r in refs if posts[r]["significance"] in ("abnormal", "borderline")),
        })
    candidates.sort(key=lambda c: (-len(c["proposers"]), -c["abnormal_refs"], -len(c["posters"])))
    for i, c in enumerate(candidates[:MAX_CANDIDATES], start=1):
        c["id"] = f"C{i}"
    return candidates[:MAX_CANDIDATES]


def render_candidates(candidates: list[dict], challenges: dict[str, dict] | None = None) -> str:
    lines = []
    for c in candidates:
        lib = pattern_by_id().get(c["pattern_id"])
        lines.append(f"{c['id']}: {c['title']}\n  posts: {', '.join(c['refs'])}\n  pattern: "
                     + (f"{c['pattern_id']} {lib['name']}" if lib else "panel-proposed (not in the library)")
                     + f"\n  proposed by: {', '.join(c['proposers'])}"
                     + "".join(f"\n  fits: {w}" for w in c["why_it_fits"]))
        ch = (challenges or {}).get(c["id"])
        if ch:
            lines.append(f"  SKEPTIC verdict {ch['verdict']}: {ch['reason']}"
                         + "".join(f"\n  simpler explanation: {x}" for x in ch["simpler_explanations"])
                         + "".join(f"\n  missing: {x}" for x in ch["missing"])
                         + (f"\n  posts that do not support it: {', '.join(ch['unsupported_refs'])}" if ch["unsupported_refs"] else ""))
    return "<candidates>\n" + ("\n".join(lines) or "(none)") + "\n</candidates>"


def validate_skeptic(out: Any, candidates: list[dict], posts: dict[str, dict]) -> tuple[dict[str, dict], dict | None, list[dict]]:
    """Challenges keyed by candidate id (unknown ids ignored), plus an optional alternative
    card from the skeptic that passes the same rules as everyone else's."""
    ids = {c["id"] for c in candidates}
    challenges: dict[str, dict] = {}
    for ch in out.challenges:
        if ch.candidate in ids and ch.candidate not in challenges:
            challenges[ch.candidate] = {
                "verdict": ch.verdict, "reason": ch.reason.strip(),
                "simpler_explanations": _clean_list(ch.simpler_explanations, 3),
                "unsupported_refs": [r for r in ch.unsupported_refs if r in posts],
                "missing": _clean_list(ch.missing, 3),
            }
    alternative, dropped = None, []
    if out.alternative is not None:
        kept, dropped = validate_connections("skeptic", [out.alternative], posts)
        alternative = kept[0] if kept else None
    return challenges, alternative, dropped


def validate_stances(member: str, stances: list[Any], candidates: list[dict], posts: dict[str, dict]) -> list[dict]:
    """defend/concede only make sense on your own card; elsewhere they become support/ignored."""
    by_id = {c["id"]: c for c in candidates}
    out, seen = [], set()
    for st in stances:
        c = by_id.get(st.candidate)
        if c is None or st.candidate in seen:
            continue
        stance = st.stance
        own = member in c["proposers"]
        if not own and stance == "defend":
            stance = "support"
        if not own and stance == "concede":
            continue
        if own and stance == "support":
            stance = "defend"
        if own and stance == "challenge":
            stance = "concede"
        seen.add(st.candidate)
        out.append({"by": member, "candidate": st.candidate, "stance": stance, "reason": st.reason.strip(),
                    "refs": [r for r in st.board_refs if r in posts]})
    return out


def score_candidates(candidates: list[dict], challenges: dict[str, dict], stances: list[dict]) -> list[dict]:
    """+1 per proposer, +1 per support, -1 per challenge, -1 for a skeptic 'weaken'.
    A skeptic 'drop' is final if any proposer concedes or none defends; if a proposer defends,
    the card stays with -2. A proposer who concedes no longer counts as a proposer.
    Strength: 3+ stronger match, 1-2 possible match, 0 or less weaker match."""
    scored = []
    for c in candidates:
        mine = [s for s in stances if s["candidate"] == c["id"]]
        conceded = {s["by"] for s in mine if s["stance"] == "concede"}
        defended = {s["by"] for s in mine if s["stance"] == "defend"}
        supports = [s for s in mine if s["stance"] == "support"]
        challenges_ = [s for s in mine if s["stance"] == "challenge"]
        verdict = (challenges.get(c["id"]) or {}).get("verdict", "keep")
        proposers = [p for p in c["proposers"] if p not in conceded]
        score = len(proposers) + len(supports) - len(challenges_)
        removed = None
        if verdict == "weaken":
            score -= 1
        elif verdict == "drop":
            if conceded or not defended:
                removed = "skeptic: drop, " + ("conceded by the proposer" if conceded else "not defended")
            else:
                score -= 2
        if not proposers and not removed:
            removed = "every proposer conceded"
        strength = "stronger" if score >= 3 else "possible" if score >= 1 else "weaker"
        scored.append({**c, "score": score, "strength": strength, "removed": removed, "skeptic": challenges.get(c["id"]),
                       "supports": supports, "challenges": challenges_, "defended_by": sorted(defended),
                       "conceded_by": sorted(conceded)})
    scored.sort(key=lambda c: (c["removed"] is not None, -c["score"], -c["abnormal_refs"]))
    return scored


def top_candidates(scored: list[dict], n: int = TOP_N) -> list[dict]:
    return [c for c in scored if c["removed"] is None][:n]


def regions_for(refs: list[str], posts: dict[str, dict]) -> list[str]:
    """Body regions of a card come from its posts (set in code), never from a model."""
    return list(dict.fromkeys(posts[r]["region"] for r in refs if r in posts and posts[r].get("region")))


# ---- round 4: the coordinator's cards, finished in code ------------------------------------

def render_top(top: list[dict], removed: list[dict]) -> str:
    """What the coordinator sees: the surviving top candidates with the full debate record."""
    lines = []
    for c in top:
        lib = pattern_by_id().get(c["pattern_id"])
        sk = c.get("skeptic") or {}
        lines.append(f"{c['id']} [{c['strength']} match] {c['title']}\n  posts: {', '.join(c['refs'])}\n  pattern: "
                     + (f"{c['pattern_id']} {lib['name']}" if lib else "panel-proposed")
                     + f"\n  proposed by: {', '.join(c['proposers'])}"
                     + "".join(f"\n  fits: {w}" for w in c["why_it_fits"])
                     + "".join(f"\n  could help tell: {w}" for w in c["would_help_tell"])
                     + (f"\n  skeptic ({sk.get('verdict')}): {sk.get('reason', '')}" if sk else "")
                     + "".join(f"\n  simpler explanation: {x}" for x in sk.get("simpler_explanations", []))
                     + "".join(f"\n  {x['by']} supports: {x['reason']}" for x in c.get("supports", []))
                     + "".join(f"\n  {x['by']} challenges: {x['reason']}" for x in c.get("challenges", [])))
    text = "<top_candidates>\n" + ("\n".join(lines) or "(none survived the debate)") + "\n</top_candidates>"
    if removed:
        text += "\n<removed_in_debate>\n" + "\n".join(f"- {c['id']} {c['title']} ({c['removed']})" for c in removed) + "\n</removed_in_debate>"
    return text


def build_cards(out_cards: list[dict], top: list[dict], posts: dict[str, dict], names: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Patient-facing cards: the coordinator's wording on the debate's facts. Strength, regions,
    label, specialists and the source come from code. A top candidate the coordinator left
    out still gets a card from the debate record; a card for anything else is dropped."""
    by_id = {c["id"]: c for c in top}
    written = {}
    dropped = []
    for oc in out_cards:
        if oc["candidate"] not in by_id:
            dropped.append({"section": "explanations", "item": oc["title"][:160], "reason": "not a top candidate from the debate"})
            continue
        written.setdefault(oc["candidate"], oc)
    cards = []
    for c in top:
        oc = written.get(c["id"])
        why = []
        for pt in (oc or {}).get("why_it_fits", []):
            refs = [r for r in pt["finding_refs"] if r in posts]
            if refs:
                why.append({"text": pt["text"], "finding_refs": refs})
        if not why:
            why = [{"text": w, "finding_refs": c["refs"]} for w in c["why_it_fits"][:3]]
        sk = c.get("skeptic") or {}
        against = _clean_list((oc or {}).get("argues_against", []), 3) or _clean_list(
            sk.get("simpler_explanations", []) + [x["reason"] for x in c.get("challenges", [])], 3)
        refs = list(dict.fromkeys(c["refs"] + [r for w in why for r in w["finding_refs"]]))
        lib = pattern_by_id().get(c["pattern_id"])
        members = list(dict.fromkeys(c["proposers"] + [posts[r]["by"] for r in refs if r in posts]))
        cards.append({
            "id": c["id"], "title": (oc or {}).get("title") or c["title"], "label": NOT_A_DIAGNOSIS,
            "strength": c["strength"], "score": c["score"],
            "why_it_fits": why, "argues_against": against,
            "would_help_tell": _clean_list((oc or {}).get("would_help_tell", []), 3) or c["would_help_tell"],
            "refs": refs, "regions": regions_for(refs, posts),
            "specialists": [{"id": m, "name": names.get(m, m)} for m in members if m not in ("intake", "skeptic")],
            "pattern": {"id": lib["id"], "name": lib["name"], "source": lib["source"]} if lib else None,
            "debate": {"skeptic_verdict": sk.get("verdict"), "skeptic_reason": sk.get("reason"),
                       "supports": len(c.get("supports", [])), "challenges": len(c.get("challenges", [])),
                       "defended_by": c.get("defended_by", []), "conceded_by": c.get("conceded_by", [])},
            "written_by": "coordinator" if oc else "debate record",
        })
    return cards, dropped
