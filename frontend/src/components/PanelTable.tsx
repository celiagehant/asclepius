import { useEffect, useMemo, useRef, useState } from "react";
import { colorOf, derivePanel, shortName, SPECIALTY_ICONS, type ChatOverlay, type Ev, type MemberState, type RosterEntry } from "../lib/panel";

const BUBBLE_WINDOW = 10; // a comment stays visible for this many later events

// Positions on two concentric half-ellipses around the table (percent of the stage), spaced by equal
// arc length so cards don't bunch up where the ellipse curves steeply.
const CENTER = { x: 50, y: 70 };
const INNER = { rx: 38, ry: 48, from: 157, to: 23 };
const OUTER = { rx: 47, ry: 64, from: 172, to: 8 };
const STAGE_ASPECT = 680 / 1080; // stage height / typical width, to measure arc length in real proportions

function arc(i: number, n: number, ring: typeof INNER) {
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
  const p = point(deg);
  return { left: `${p.x}%`, top: `${p.y}%` };
}

export default function PanelTable({ events, roster, patientName, live, medicationFallback, overlay, autoReplay }: {
  events: Ev[]; roster: RosterEntry[]; patientName: string; live: boolean; medicationFallback?: number; overlay?: ChatOverlay | null;
  autoReplay?: boolean;
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
  const outer = members.filter((r) => !forward.includes(r.id));
  const medications = state.medications ?? medicationFallback ?? null;
  const replaying = replayAt !== null;

  return (
    <section className="card panel-table-card" aria-label="The panel">
      <div className="panel-table-head">
        <div>
          <h2>The panel</h2>
          <p className="muted small">AI specialist agents, not real doctors. Bright cards are on this case; dimmed cards are the rest of the roster.</p>
        </div>
        {!live && events.length > 0 && (
          <button className="btn btn-ghost" onClick={replay} disabled={replaying}>{replaying ? "Replaying…" : "▶ Replay the conference"}</button>
        )}
      </div>
      <div className={`stage-area ${inner.length > 6 ? "crowded" : ""}`}>
        <div className="table-top" aria-hidden>
          <span className="table-label">{patientName}'s case</span>
          <span className="table-stage">{STAGE_LABEL[state.stage]}</span>
          <SpendMeter spend={state.spend} />
        </div>

        {inner.map((r, i) => (
          <DoctorCard key={r.id} entry={r} pos={arc(i, inner.length, INNER)} state={state.members[r.id]} cost={state.spend.byMember[r.id]}
            lastSeq={state.stage === "round1" || state.stage === "round2" ? state.lastSeq : Infinity}
            active={state.selected} consult={state.consults.has(r.id)} medications={r.id === "clinical_pharmacist" ? medications : null} />
        ))}
        {outer.map((r, i) => (
          <DoctorCard key={r.id} entry={r} pos={arc(i, outer.length, OUTER)} state={state.members[r.id]} lastSeq={state.lastSeq} dim />
        ))}

        <div className={`doctor coordinator ${state.coordinator.done ? "is-done" : ""}`} style={{ left: "50%", top: "90%", ["--c" as string]: colorOf(coordinator.id) }}>
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
          {state.spend.total > 0 && (
            <div className="cost-row">
              {(["coordinator", "safety_reviewer", "intake"] as const).filter((k) => state.spend.byMember[k]).map((k) => (
                <span key={k} className="cost-chip">{{ coordinator: "coordinator", safety_reviewer: "safety", intake: "intake" }[k]} ${state.spend.byMember[k].toFixed(4)}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

const STAGE_LABEL: Record<string, string> = {
  intake: "Reading and routing records", round1: "Round 1 · independent reviews", round2: "Round 2 · case conference",
  synthesis: "Coordinator writing the summary", safety: "Safety review", done: "Conference closed",
};

function SpendMeter({ spend }: { spend: { total: number; limit: number | null } }) {
  if (spend.total <= 0) return null;
  const pct = spend.limit ? Math.min(100, (spend.total / spend.limit) * 100) : 0;
  return (
    <span className="spend-meter" title="Live cost of this review (gpt-6-luna prices per million tokens)">
      <span className="spend-num">${spend.total.toFixed(4)}</span>
      {spend.limit && <span className="spend-bar"><i style={{ width: `${pct}%` }} /></span>}
      {spend.limit && <span className="spend-limit">of ${spend.limit.toFixed(2)} budget</span>}
    </span>
  );
}

function DoctorCard({ entry, pos, state, lastSeq, dim, active, consult, medications, cost }: {
  entry: RosterEntry; pos: { left: string; top: string }; state?: MemberState; lastSeq: number;
  dim?: boolean; active?: boolean; consult?: boolean; medications?: number | null; cost?: number;
}) {
  const s = state ?? { status: "idle", activity: "", docs: [], round2: "none" as const };
  const lit = s.status === "lit";
  const bubble = s.bubble && (s.bubble.seq === Number.MAX_SAFE_INTEGER || lastSeq - s.bubble.seq <= BUBBLE_WINDOW) ? s.bubble : null;
  const pharmacist = entry.id === "clinical_pharmacist";
  const cls = ["doctor", dim ? "is-dim" : "is-front", lit ? "is-lit" : "", s.status === "working" ? "is-working" : "",
    s.status === "done" ? "is-done" : "", s.status === "failed" ? "is-failed" : "", bubble && !dim ? "has-bubble" : ""].join(" ");
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
          {cost !== undefined && cost > 0 && <div className="cost-chip card-cost">${cost.toFixed(4)}</div>}
        </>
      )}
    </div>
  );
}
