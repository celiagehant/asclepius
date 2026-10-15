import { useMemo, useState } from "react";
import { colorOf, REGION_LABELS, SYSTEM_COLORS, SYSTEM_LABELS, type BoardPost, type RosterEntry } from "../lib/panel";

/** The shared case board: one line per verified finding, posted after the independent review and
 *  read by the whole panel. Filter by body system; click a post to light its doctor and body region. */
export default function CaseBoard({ posts, roster, focusRefs, onFocusPost, live }: {
  posts: BoardPost[]; roster: RosterEntry[]; focusRefs: string[]; onFocusPost?: (p: BoardPost | null) => void; live?: boolean;
}) {
  const [system, setSystem] = useState<string | null>(null);
  const names = useMemo(() => Object.fromEntries(roster.map((r) => [r.id, r.name])), [roster]);
  const systems = useMemo(() => {
    const count: Record<string, number> = {};
    posts.forEach((p) => { count[p.system] = (count[p.system] ?? 0) + 1; });
    return Object.entries(count).sort((a, b) => b[1] - a[1]);
  }, [posts]);
  const focus = new Set(focusRefs);
  const shown = (system ? posts.filter((p) => p.system === system) : posts).slice().reverse();  // newest first

  return (
    <aside className="case-board" aria-label="Shared case board">
      <div className="board-head">
        <h3>Case board</h3>
        <span className="muted small">{posts.length ? `${posts.length} posts · read by the whole panel` : live ? "Posts appear as each review finishes" : "No posts"}</span>
      </div>
      {systems.length > 1 && (
        <div className="board-filters" role="group" aria-label="Filter by body system">
          <button className={`sys-chip ${system === null ? "on" : ""}`} onClick={() => setSystem(null)}>All</button>
          {systems.map(([id, n]) => (
            <button key={id} className={`sys-chip ${system === id ? "on" : ""}`} style={{ ["--s" as string]: SYSTEM_COLORS[id] ?? "#607d8b" }}
              onClick={() => setSystem(system === id ? null : id)}>{SYSTEM_LABELS[id] ?? id} <span>{n}</span></button>
          ))}
        </div>
      )}
      <ul className="board-feed" aria-live={live ? "polite" : undefined}>
        {shown.map((p) => (
          <li key={p.id} className={`post sig-${p.significance} ${focus.has(p.id) ? "on" : ""} ${focus.size && !focus.has(p.id) ? "faded" : ""}`}
            tabIndex={0} onClick={() => onFocusPost?.(focus.has(p.id) && focus.size === 1 ? null : p)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onFocusPost?.(p); } }}>
            <div className="post-top">
              <span className="sys-dot" style={{ background: SYSTEM_COLORS[p.system] ?? "#607d8b" }} />
              <span className="post-sys">{SYSTEM_LABELS[p.system] ?? p.system}</span>
              {p.region && <span className="post-region">· {REGION_LABELS[p.region] ?? p.region}</span>}
              <span className="post-id">{p.id}</span>
            </div>
            <div className="post-line">{p.line}</div>
            <div className="post-bottom">
              <span className="post-by" style={{ color: colorOf(p.by) }}>{names[p.by] ?? p.by_name}</span>
              {p.symptoms.map((t) => <span key={t} className="sym-tag">{t}</span>)}
            </div>
          </li>
        ))}
      </ul>
    </aside>
  );
}
