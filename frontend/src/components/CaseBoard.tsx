import { useMemo, useState } from "react";
import { colorOf, REGION_LABELS, shortName, SPECIALTY_ICONS, SYSTEM_COLORS, SYSTEM_LABELS, type BoardPost, type RosterEntry } from "../lib/panel";

// The shared case board, written for patients: "What the doctors found". One card per finding,
// with the doctor who posted it, a plain label, and the body area. Technical ids stay out of
// sight (they show on hover). Click a finding to light up its doctor and body area.

const SYSTEM_ICONS: Record<string, string> = {
  cardiovascular: "🫀", respiratory: "🫁", digestive: "🍽️", liver: "🟤", kidney_urinary: "🫘", endocrine_metabolic: "🧪",
  blood: "🩸", immune_joints: "🛡️", nervous_system: "🧠", mental_health: "💭", skin: "✋", musculoskeletal: "🦴",
  reproductive: "⚕️", eyes: "👁️", ear_nose_throat: "👂", medication: "💊", lifestyle: "🌿", general: "🩺",
};
const LABEL: Record<string, { text: string; cls: string }> = {
  abnormal: { text: "Out of range", cls: "lab-high" }, borderline: { text: "Borderline", cls: "lab-border" },
  unclear: { text: "Unclear", cls: "lab-unclear" }, normal_but_relevant: { text: "Worth noting", cls: "lab-note" },
};

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
  const doctors = new Set(posts.map((p) => p.by)).size;

  return (
    <aside className="case-board" aria-label="What the doctors found">
      <div className="board-head">
        <h3>What the doctors found</h3>
        <span className="muted small">{posts.length
          ? `${posts.length} finding${posts.length === 1 ? "" : "s"} from ${doctors} panel member${doctors === 1 ? "" : "s"}, shared with everyone at the table`
          : live ? "Findings appear here as each doctor finishes reading" : "No findings yet"}</span>
      </div>
      {systems.length > 1 && (
        <div className="board-filters" role="group" aria-label="Show one body area">
          <button className={`sys-chip ${system === null ? "on" : ""}`} onClick={() => setSystem(null)}>All</button>
          {systems.map(([id, n]) => (
            <button key={id} className={`sys-chip ${system === id ? "on" : ""}`} style={{ ["--s" as string]: SYSTEM_COLORS[id] ?? "#607d8b" }}
              onClick={() => setSystem(system === id ? null : id)} title={`${SYSTEM_LABELS[id] ?? id}: ${n}`}>
              <span aria-hidden>{SYSTEM_ICONS[id] ?? "•"}</span> {SYSTEM_LABELS[id] ?? id} <span className="sys-n">{n}</span>
            </button>
          ))}
        </div>
      )}
      <ul className="board-feed" aria-live={live ? "polite" : undefined}>
        {shown.map((p) => {
          const label = LABEL[p.significance] ?? LABEL.unclear;
          const who = names[p.by] ?? p.by_name;
          return (
            <li key={p.id} className={`post ${focus.has(p.id) ? "on" : ""} ${focus.size && !focus.has(p.id) ? "faded" : ""}`}
              title={`${p.id} · from ${who}${p.document && p.document !== "medication review" ? ` · ${p.document}` : ""}`}
              tabIndex={0} onClick={() => onFocusPost?.(focus.has(p.id) && focus.size === 1 ? null : p)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onFocusPost?.(p); } }}>
              <span className="post-avatar" style={{ ["--c" as string]: colorOf(p.by) }} aria-hidden>{SPECIALTY_ICONS[p.by] ?? "•"}</span>
              <div className="post-body">
                <div className="post-top">
                  <span className="post-by" style={{ color: colorOf(p.by) }}>{shortName(who)}</span>
                  <span className={`post-label ${label.cls}`}>{label.text}</span>
                </div>
                <div className="post-line">{p.line}</div>
                <div className="post-bottom">
                  <span className="post-area"><span aria-hidden>{SYSTEM_ICONS[p.system] ?? "•"}</span> {p.region ? REGION_LABELS[p.region] ?? p.region : SYSTEM_LABELS[p.system] ?? p.system}</span>
                  {p.symptoms.slice(0, 2).map((t) => <span key={t} className="sym-tag">{t}</span>)}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
