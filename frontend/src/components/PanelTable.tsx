import { useEffect, useMemo, useRef, useState } from "react";
import { colorOf, derivePanel, shortName, SPECIALTY_ICONS, type BoardPost, type ChatOverlay, type Ev, type MemberState, type RosterEntry, type Thread } from "../lib/panel";
import CaseBoard from "./CaseBoard";

const BUBBLE_WINDOW = 10; // a comment stays visible for this many later events

// Positions on two concentric half-ellipses around the table (percent of the stage), spaced by equal
// arc length so cards don't bunch up where the ellipse curves steeply.
const CENTER = { x: 50, y: 70 };
const INNER = { rx: 38, ry: 48, from: 157, to: 23 };
const OUTER = { rx: 47, ry: 64, from: 172, to: 8 };
// With more than 6 members at the table, cards alternate between two rows so they don't overlap.
const INNER_LOW = { rx: 35, ry: 40, from: 160, to: 20 };
const INNER_HIGH = { rx: 44, ry: 56, from: 166, to: 14 };
// The two members who sit at every table take the seats beside the coordinator, at the head of the table.
const HEAD_SEATS: Record<string, { x: number; y: number }> = { lifestyle: { x: 18, y: 89 } };
const CROWDED = 6;  // from this many arc cards on, the stage beside the case board is too narrow for one row
const ringFor = (i: number, n: number) => (n >= CROWDED ? (i % 2 ? INNER_HIGH : INNER_LOW) : INNER);
const STAGE_ASPECT = 680 / 1080; // stage height / typical width, to measure arc length in real proportions

function arcPoint(i: number, n: number, ring: typeof INNER) {
  const point = (deg: number) => {
    const rad = (deg * Math.PI) / 180;
    return { x: CENTER.x + ring.rx * Math.cos(rad), y: CENTER.y - ring.ry * Math.sin(rad) };
  };
  let deg = 90;
  if (n > 1) {
    const steps = 180;
    const lengths = [0];
    let prev = point(ring.from);
    for (let k = 1; k <= steps; k++) {
      const p = point(ring.from + ((ring.to - ring.from) * k) / steps);
      lengths.push(lengths[k - 1] + Math.hypot(p.x - prev.x, (p.y - prev.y) * STAGE_ASPECT));
      prev = p;
    }
    const goal = (lengths[steps] * i) / (n - 1);
    const k = lengths.findIndex((l) => l >= goal);
    deg = ring.from + ((ring.to - ring.from) * Math.max(k, 0)) / steps;
  }
  return point(deg);
}

function arc(i: number, n: number, ring: typeof INNER) {
  const p = arcPoint(i, n, ring);
  return { left: `${p.x}%`, top: `${p.y}%` };
}

const FRESH_EVENTS = 12; // a thread drawn within the last 12 events is animated

/** Curved threads between doctor cards: teal glow for a proposed connection, brighter for support,
 *  amber dashes for a challenge. Drawn in stage percentages so they follow the card layout. */
function Threads({ threads, pos, lastSeq, focus }: { threads: Thread[]; pos: Record<string, { x: number; y: number }>; lastSeq: number; focus: Set<string> }) {
  const paths: { key: string; d: string; kind: string; fresh: boolean; dim: boolean }[] = [];
  threads.forEach((t, i) => {
    const a = pos[t.from];
    if (!a) return;
    for (const to of t.to) {
      const b = pos[to];
      if (!b || to === t.from) continue;
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const cx = mx + (50 - mx) * 0.35, cy = my + (62 - my) * 0.45;   // bow toward the table
      paths.push({ key: `${i}-${to}`, d: `M ${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}`, kind: t.kind,
        fresh: lastSeq - t.seq <= FRESH_EVENTS, dim: focus.size > 0 && !(focus.has(t.from) && focus.has(to)) });
    }
  });
  if (!paths.length) return null;
  return (
    <svg className="threads" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
      {paths.map((p) => (
        <path key={p.key} d={p.d} className={`thread thread-${p.kind} ${p.fresh ? "fresh" : ""} ${p.dim ? "dim" : ""}`} vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  );
}

export default function PanelTable({ events, roster, patientName, live, medicationFallback, overlay, autoReplay, focusMembers, focusRefs, onFocusPost, boardFallback }: {
  events: Ev[]; roster: RosterEntry[]; patientName: string; live: boolean; medicationFallback?: number; overlay?: ChatOverlay | null;
  autoReplay?: boolean; focusMembers?: string[]; focusRefs?: string[]; onFocusPost?: (p: BoardPost | null) => void; boardFallback?: BoardPost[];
}) {
  const [replayAt, setReplayAt] = useState<number | null>(null);
  const timer = useRef<number | null>(null);
  const shown = replayAt === null ? events : events.slice(0, replayAt);
  const derived = useMemo(() => derivePanel(shown), [shown]);
  // While a chat question is being answered, the answering doctors light up on the same table.
  const state = useMemo(() => {
    if (!overlay) return derived;
    const members = { ...derived.members };
    for (const [id, o] of Object.entries(overlay.members)) {
      const base = members[id] ?? { status: "idle" as const, activity: "", docs: [], round2: "none" as const };
      members[id] = { ...base, status: o.status === "working" ? "working" : o.status === "failed" ? "failed" : "done",
        activity: o.status === "working" ? "Answering your question" : o.status === "failed" ? "Could not answer" : "Answered your question",
        bubble: o.bubble ? { text: o.bubble, kind: "answer", seq: Number.MAX_SAFE_INTEGER } : undefined };
    }
    return { ...derived, members, coordinator: overlay.coordinator ? { ...derived.coordinator, activity: overlay.coordinator } : derived.coordinator };
  }, [derived, overlay]);

  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);
  const autoStarted = useRef(false);
  useEffect(() => {  // the offline demo replays the conference once when a case opens
    if (autoReplay && !autoStarted.current && events.length) {
      autoStarted.current = true;
      replay();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoReplay, events.length]);
  const replay = () => {
    if (timer.current) window.clearInterval(timer.current);
    setReplayAt(0);
    timer.current = window.setInterval(() => {
      setReplayAt((i) => {
        if (i === null || i >= events.length) { if (timer.current) window.clearInterval(timer.current); return null; }
        return i + 1;
      });
    }, 140);
  };

  const coordinator = roster.find((r) => r.id === state.coordinatorId) ?? { id: state.coordinatorId, name: "Internal medicine", tier: "coordinator", scope: "" };
  const members = roster.filter((r) => r.tier !== "coordinator");
  // Before the panel is chosen, doctors lit by document routing come forward; afterwards, the chosen panel.
  const forward = state.selected
    ? [...state.active].filter((id) => id !== state.coordinatorId)
    : members.filter((r) => state.members[r.id]?.status === "lit").map((r) => r.id);
  const inner = forward.map((id) => members.find((r) => r.id === id)).filter(Boolean) as RosterEntry[];
  const pharmacistIdx = inner.findIndex((r) => r.id === "clinical_pharmacist");
  if (pharmacistIdx >= 0) inner.push(...inner.splice(pharmacistIdx, 1));  // pharmacist at the end of the arc
  const head = members.filter((r) => HEAD_SEATS[r.id]);   // always at the table; dimmed until they take part
  for (const r of head) if (inner.includes(r)) inner.splice(inner.indexOf(r), 1);
  const outer = members.filter((r) => !forward.includes(r.id) && !HEAD_SEATS[r.id]);
  const medications = state.medications ?? medicationFallback ?? null;
  const replaying = replayAt !== null;
  const pos: Record<string, { x: number; y: number }> = Object.fromEntries(inner.map((r, i) => [r.id, arcPoint(i, inner.length, ringFor(i, inner.length))]));
  pos[state.coordinatorId] = { x: 50, y: 90 };
  for (const r of head) pos[r.id] = HEAD_SEATS[r.id];
  const focus = new Set(focusMembers ?? []);
  const bubbleSeq = ["round1", "round2", "round3"].includes(state.stage) ? state.lastSeq : -1;
  const coordBubble = state.coordinator.bubble && bubbleSeq - state.coordinator.bubble.seq <= BUBBLE_WINDOW ? state.coordinator.bubble : null;
  const board = state.board.length ? state.board : (replaying ? [] : boardFallback ?? []);

  return (
    <section className="card panel-table-card" aria-label="The panel">
      <div className="panel-table-head">
        <div>
          <h2>The panel</h2>
          <p className="muted small">AI specialist agents, not real doctors. Bright cards are on this case; dimmed cards are the rest of the roster.</p>
          <div className="thread-legend" aria-hidden><span><i />connects findings</span><span><i className="ch" />challenges</span></div>
        </div>
        {!live && events.length > 0 && (
          <button className="btn btn-ghost" onClick={replay} disabled={replaying}>{replaying ? "Replaying…" : "▶ Replay the conference"}</button>
        )}
      </div>
      <div className="panel-layout">{/* stage on the left, live case board on the right */}
      <div className={`stage-area ${inner.length >= CROWDED ? "crowded" : ""}`}>
        <Threads threads={state.threads} pos={pos} lastSeq={replaying || live ? state.lastSeq : Infinity} focus={focus} />
        <div className="table-top" aria-hidden>
          <span className="table-label">{patientName}'s case</span>
          <span className="table-stage">{STAGE_LABEL[state.stage]}</span>
        </div>

        {inner.map((r, i) => (
          <DoctorCard key={r.id} entry={r} pos={arc(i, inner.length, ringFor(i, inner.length))} state={state.members[r.id]}
            lastSeq={["round1", "round2", "round3"].includes(state.stage) ? state.lastSeq : Infinity} focused={focus.has(r.id)}
            active={state.selected} consult={state.consults.has(r.id)} medications={r.id === "clinical_pharmacist" ? medications : null} />
        ))}
        {head.map((r) => (
          <DoctorCard key={r.id} entry={r} pos={{ left: `${HEAD_SEATS[r.id].x}%`, top: `${HEAD_SEATS[r.id].y}%` }} state={state.members[r.id]}
            lastSeq={["round1", "round2", "round3"].includes(state.stage) ? state.lastSeq : Infinity}
            focused={focus.has(r.id)} active={state.selected} dim={!forward.includes(r.id)} />
        ))}
        {outer.map((r, i) => (
          <DoctorCard key={r.id} entry={r} pos={arc(i, outer.length, OUTER)} state={state.members[r.id]} lastSeq={state.lastSeq} dim />
        ))}

        <div className={`doctor coordinator ${state.coordinator.done ? "is-done" : ""} ${coordBubble ? "has-bubble" : ""} ${focus.has(coordinator.id) ? "is-focus" : ""}`}
          style={{ left: "50%", top: "90%", ["--c" as string]: colorOf(coordinator.id) }}>
          {coordBubble && <div className={`bubble bubble-${coordBubble.kind}`}><span className="bubble-kind">{coordBubble.kind === "agrees" ? "keeps" : "challenges"}</span> {coordBubble.text}</div>}
          <div className="doctor-row">
            <span className="avatar">{SPECIALTY_ICONS[coordinator.id] ?? "⚕"}</span>
            <div>
              <strong>{shortName(coordinator.name)}</strong>
              <div className="doc-tags"><span className="ai-tag">AI specialist</span><span className="lead-tag">Coordinator · head of the table</span></div>
            </div>
            {state.coordinator.done && <span className="done-badge" aria-label="done">✓</span>}
          </div>
          <div className="activity-line">{state.coordinator.activity}</div>
          {state.coordinator.safety && <div className="safety-line">🛡 {state.coordinator.safety}</div>}
        </div>
      </div>
      <CaseBoard posts={board} roster={roster} focusRefs={focusRefs ?? []} onFocusPost={onFocusPost} live={live || replaying} />
      </div>
    </section>
  );
}

const STAGE_LABEL: Record<string, string> = {
  intake: "Reading and routing records", round1: "Round 1 · independent reviews", round2: "Round 2 · connections",
  round3: "Round 3 · the coordinator challenges", synthesis: "Round 4 · recommendations", safety: "Safety review", done: "Conference closed",
};


function DoctorCard({ entry, pos, state, lastSeq, dim, active, consult, medications, focused }: {
  entry: RosterEntry; pos: { left: string; top: string }; state?: MemberState; lastSeq: number;
  dim?: boolean; active?: boolean; consult?: boolean; medications?: number | null; focused?: boolean;
}) {
  const s = state ?? { status: "idle", activity: "", docs: [], round2: "none" as const };
  const lit = s.status === "lit";
  const bubble = s.bubble && (s.bubble.seq === Number.MAX_SAFE_INTEGER || lastSeq - s.bubble.seq <= BUBBLE_WINDOW) ? s.bubble : null;
  const pharmacist = entry.id === "clinical_pharmacist";
  const cls = ["doctor", dim ? "is-dim" : "is-front", lit ? "is-lit" : "", s.status === "working" ? "is-working" : "",
    s.status === "done" ? "is-done" : "", s.status === "failed" ? "is-failed" : "", bubble && !dim ? "has-bubble" : "",
    focused ? "is-focus" : ""].join(" ");
  return (
    <div className={cls} style={{ ...pos, ["--c" as string]: colorOf(entry.id) }} title={dim ? `${entry.name}: ${entry.scope}` : undefined}>
      {bubble && !dim && <div className={`bubble bubble-${bubble.kind}`}><span className="bubble-kind">{bubble.kind}</span> {bubble.text}</div>}
      <div className="doctor-row">
        <span className="avatar">{SPECIALTY_ICONS[entry.id] ?? entry.name[0]}</span>
        <div className="doctor-name">
          <strong>{shortName(entry.name)}{consult ? " · consult" : ""}</strong>
          {!dim && <div className="doc-tags"><span className="ai-tag">AI specialist</span></div>}
        </div>
        {s.status === "done" && !dim && <span className="done-badge" aria-label="done">✓</span>}
        {s.status === "failed" && !dim && <span className="done-badge fail" aria-label="failed">!</span>}
      </div>
      {!dim && (
        <>
          {pharmacist && medications !== null && <div className="pill-line">💊 {medications} medication{medications === 1 ? "" : "s"} under review</div>}
          <div className="activity-line">{s.activity || (active ? "Waiting to start" : lit ? `Reviewing ${s.docs.join(", ")}` : "")}</div>
          {s.round2 !== "none" && <div className="round2-line">Round 2: {s.round2 === "done" ? "done" : "discussing…"}</div>}
          {s.roundLine && s.roundLine !== s.activity && <div className="round2-line">{s.roundLine}</div>}
        </>
      )}
    </div>
  );
}
