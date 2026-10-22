import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { colorOf, derivePanel, shortName, SPECIALTY_ICONS, type BoardPost, type ChatOverlay, type Ev, type MemberState, type RosterEntry, type Thread } from "../lib/panel";
import { webglAvailable } from "./BodyMap";
import CaseBoard from "./CaseBoard";
import ConversationFeed from "./ConversationFeed";
import type { RoomLayout, Seat } from "./ConferenceRoom3D";

const ConferenceRoom3D = lazy(() => import("./ConferenceRoom3D"));  // three.js loads only when the room is shown

/** The 3D room needs WebGL and some width; phones and old browsers get the card layout. */
function useRoom3d(): boolean {
  const query = "(min-width: 821px)";
  const [ok, setOk] = useState(() => webglAvailable() && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setOk(webglAvailable() && mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return ok;
}

/** Seat angles around the table: the coordinator at the head (90°), the others split left and right. */
function seatAngles(ids: string[]): Record<string, number> {
  const left = ids.slice(0, Math.ceil(ids.length / 2)), right = ids.slice(Math.ceil(ids.length / 2));
  const spread = (list: string[], from: number, to: number) =>
    Object.fromEntries(list.map((id, i) => [id, list.length === 1 ? (from + to) / 2 : from + ((to - from) * i) / (list.length - 1)]));
  // Use the whole table: from the near-left corner round to the near-right corner (the coordinator sits at 90°).
  const span = ids.length > 4 ? [208, 116, 64, -28] : [178, 122, 58, 2];
  return { ...spread(left, span[0], span[1]), ...spread(right, span[2], span[3]) };
}

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
  const [paused, setPaused] = useState(false);
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

  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  const autoStarted = useRef(false);
  useEffect(() => {  // the offline demo replays the conference once when a case opens
    if (autoReplay && !autoStarted.current && events.length) {
      autoStarted.current = true;
      replay();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoReplay, events.length]);
  // Replay at a human pace: what the doctors say gets time to be read; bookkeeping events go by quickly.
  const delayFor = (e?: Ev) => !e ? 100 : ["connection", "challenge", "stance", "comment"].includes(e.type) ? 1500
    : e.type === "board_post" ? 380 : e.type === "conference_round" ? 900 : e.type === "spend" ? 15 : 110;
  const step = (i: number) => {
    if (i >= events.length) { setReplayAt(null); setPaused(false); return; }
    setReplayAt(i + 1);
    timer.current = window.setTimeout(() => step(i + 1), delayFor(events[i]));
  };
  const replay = () => {
    if (timer.current) window.clearTimeout(timer.current);
    setPaused(false);
    setReplayAt(0);
    timer.current = window.setTimeout(() => step(0), 300);
  };
  const togglePause = () => {
    if (replayAt === null) return;
    if (paused) { setPaused(false); step(replayAt); }
    else { if (timer.current) window.clearTimeout(timer.current); setPaused(true); }
  };
  const skip = () => { if (timer.current) window.clearTimeout(timer.current); setReplayAt(null); setPaused(false); };

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
  const [talkFocus, setTalkFocus] = useState<string[] | null>(null);
  const focus = new Set(talkFocus ?? focusMembers ?? []);
  const bubbleSeq = ["round1", "round2", "round3"].includes(state.stage) ? state.lastSeq : -1;
  const coordBubble = state.coordinator.bubble && bubbleSeq >= 0 && bubbleSeq - state.coordinator.bubble.seq <= BUBBLE_WINDOW ? state.coordinator.bubble : null;
  const board = state.board.length ? state.board : (replaying ? [] : boardFallback ?? []);
  const room3d = useRoom3d();
  const [tabPick, setTabPick] = useState<"talk" | "found" | null>(null);
  const talking = (live || replaying) && ["round2", "round3", "synthesis"].includes(state.stage);
  const tab = tabPick ?? (talking ? "talk" : "found");
  const spoken = state.talk.filter((t) => t.kind !== "round" && t.kind !== "lookup").length;
  const [layout, setLayout] = useState<RoomLayout | null>(null);
  const atTable = [...inner, ...head.filter((r) => forward.includes(r.id))];
  const speaking = [
    ...(coordBubble ? [{ id: coordinator.id, seq: coordBubble.seq }] : []),
    ...atTable.map((r) => ({ id: r.id, seq: state.members[r.id]?.bubble?.seq ?? -1 })).filter((x) => x.seq >= 0),
  ].filter((x) => x.id === coordinator.id || (x.seq === Number.MAX_SAFE_INTEGER || (bubbleSeq >= 0 && bubbleSeq - x.seq <= BUBBLE_WINDOW)))
    .sort((a, b) => b.seq - a.seq).slice(0, 2).map((x) => x.id);
  const angles = seatAngles(atTable.map((r) => r.id));
  // A bubble shows while its round is running (or while answering a chat question), never after the conference closes.
  const recent = (seq?: number) => seq !== undefined && (seq === Number.MAX_SAFE_INTEGER || (bubbleSeq >= 0 && bubbleSeq - seq <= BUBBLE_WINDOW));
  const seats: Seat[] = [
    { id: coordinator.id, color: colorOf(coordinator.id), angle: 90, coordinator: true, focused: focus.has(coordinator.id),
      // Before round 1 the coordinator sorts the incoming records: it reads through a file.
      reading: (live || replaying) && state.stage === "intake",
      talking: !!coordBubble || (!state.coordinator.done && ["round3", "synthesis", "safety"].includes(state.stage) && (live || replaying)) },
    ...atTable.map((r) => {
      const m = state.members[r.id];
      // A doctor reads as soon as a record is routed to them (before round 1) and through their round-1 review.
      const reading = (live || replaying) && (m?.status === "lit" || (m?.status === "working" && (state.stage === "round1" || state.stage === "intake")));
      return { id: r.id, color: colorOf(r.id), angle: angles[r.id], focused: focus.has(r.id), reading,
        talking: !reading && (m?.status === "working" || recent(m?.bubble?.seq)) };
    }),
  ];

  return (
    <section className="card panel-table-card" aria-label="The panel">
      <div className="panel-table-head">
        <div>
          <h2>The panel</h2>
          <p className="muted small">AI specialist agents, not real doctors. Everyone at the table is reviewing this case; whoever is working leans in to talk.</p>
          <div className="thread-legend" aria-hidden><span><i />connects findings</span><span><i className="ch" />challenges</span></div>
        </div>
        {!live && events.length > 0 && (replaying ? (
          <div className="replay-ctl">
            <button className="btn btn-ghost" onClick={togglePause}>{paused ? "▶ Resume" : "❚❚ Pause"}</button>
            <button className="btn btn-ghost" onClick={skip}>Skip to the end</button>
          </div>
        ) : <button className="btn btn-ghost" onClick={replay}>▶ Replay the conference</button>)}
      </div>
      <div className="panel-layout">{/* stage on the left, live case board on the right */}
      {room3d ? (
        <div className="room-col">
          <div className="room3d">
            <Suspense fallback={<div className="room-loading">Setting up the conference room…</div>}>
              <ConferenceRoom3D seats={seats} onLayout={setLayout} />
            </Suspense>
            {layout && (
              <>
                <Threads threads={state.threads} pos={layout.chest} lastSeq={replaying || live ? state.lastSeq : Infinity} focus={focus} />
                <div className="room-table-label" style={{ left: `${layout.table.x}%`, top: `${layout.table.y}%` }}>
                  <span className="table-label">{patientName}'s case</span>
                  <span className="table-stage">{STAGE_LABEL[state.stage]}</span>
                </div>
                {seats.map((seat) => {
                  const entry = seat.coordinator ? coordinator : atTable.find((r) => r.id === seat.id)!;
                  const m = state.members[seat.id];
                  const raw = seat.coordinator ? (coordBubble ? { ...coordBubble, kind: coordBubble.kind === "agrees" ? "keeps" : "challenges" } : null)
                    : (m?.bubble && recent(m.bubble.seq) ? m.bubble : null);
                  const bubble = raw && speaking.includes(seat.id) ? raw : null;   // only the two newest speakers, so bubbles don't pile up
                  const head = layout.head[seat.id], tag = layout.tag[seat.id];
                  if (!head || !tag) return null;
                  return (
                    <div key={seat.id}>
                      {bubble && <div className={`room-bubble bubble-${bubble.kind}`}
                        style={{ left: `${Math.min(Math.max(head.x, 14), 86)}%`, top: `${Math.max(head.y, 24)}%` }}>
                        <span className="bubble-kind">{bubble.kind}</span> {bubble.text.length > 90 ? `${bubble.text.slice(0, 88).trimEnd()}…` : bubble.text}</div>}
                      <NameTag entry={entry} state={seat.coordinator ? undefined : m} coordinator={seat.coordinator}
                        coordinatorState={seat.coordinator ? state.coordinator : undefined} focused={seat.focused} pos={tag}
                        consult={state.consults.has(seat.id)} medications={seat.id === "clinical_pharmacist" ? medications : null} active={state.selected} />
                    </div>
                  );
                })}
              </>
            )}
          </div>
          {outer.length > 0 && (
            <div className="on-call" aria-label="Rest of the roster">
              <span className="muted small">On call, not needed for this case:</span>
              {outer.map((r) => <span key={r.id} className="on-call-chip" title={`${r.name}: ${r.scope}`}>
                <span className="avatar" style={{ ["--c" as string]: colorOf(r.id) }}>{SPECIALTY_ICONS[r.id] ?? r.name[0]}</span>{shortName(r.name)}</span>)}
            </div>
          )}
        </div>
      ) : (
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
      )}
      <aside className="side-panel">
        <div className="side-tabs" role="tablist">
          <button role="tab" aria-selected={tab === "talk"} className={tab === "talk" ? "on" : ""} onClick={() => setTabPick("talk")}>
            💬 Conversation {spoken > 0 && <span className="tab-n">{spoken}</span>}</button>
          <button role="tab" aria-selected={tab === "found"} className={tab === "found" ? "on" : ""} onClick={() => setTabPick("found")}>
            📋 Findings {board.length > 0 && <span className="tab-n">{board.length}</span>}</button>
        </div>
        {tab === "talk"
          ? <ConversationFeed talk={state.talk} roster={roster} coordinatorId={state.coordinatorId} live={live || replaying} focus={focus}
              onFocus={(ms) => setTalkFocus(ms)} />
          : <CaseBoard posts={board} roster={roster} focusRefs={focusRefs ?? []} onFocusPost={onFocusPost} live={live || replaying} />}
      </aside>
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


/** The name tag under each person at the 3D table: who they are, what they are doing, and a check when done. */
function NameTag({ entry, state, coordinator, coordinatorState, focused, pos, consult, medications, active }: {
  entry: RosterEntry; state?: MemberState; coordinator?: boolean; coordinatorState?: { activity: string; done: boolean; safety: string | null };
  focused: boolean; pos: { x: number; y: number }; consult?: boolean; medications?: number | null; active?: boolean;
}) {
  const s = state ?? { status: "idle", activity: "", docs: [], round2: "none" as const };
  const done = coordinator ? coordinatorState?.done : s.status === "done";
  const working = coordinator ? !coordinatorState?.done : s.status === "working";
  const activity = coordinator ? coordinatorState?.activity : (s.activity || (active ? "Waiting to start" : ""));
  return (
    <div className={`name-tag ${coordinator ? "is-coordinator" : ""} ${working ? "is-working" : ""} ${focused ? "is-focus" : ""} ${s.status === "failed" ? "is-failed" : ""}`}
      style={{ left: `${Math.min(Math.max(pos.x, 8), 92)}%`, top: `${pos.y}%`, ["--c" as string]: colorOf(entry.id) }}
      title={`${entry.name}${activity ? ` · ${activity}` : ""}${coordinator ? "" : `\n${entry.scope}`}`}>
      <div className="tag-row">
        <span className="tag-dot" aria-hidden />
        <strong>{shortName(entry.name)}{consult ? " · consult" : ""}</strong>
        {done && <span className="tag-check" aria-label="done">✓</span>}
        {s.status === "failed" && <span className="tag-check fail" aria-label="failed">!</span>}
      </div>
      <div className="tag-role">{coordinator ? "Coordinator · AI specialist" : medications !== null && medications !== undefined
        ? `AI specialist · 💊 ${medications}` : "AI specialist"}</div>
      {coordinator && activity && <div className="tag-line">{activity}</div>}
      {coordinator && coordinatorState?.safety && <div className="tag-line">🛡 {coordinatorState.safety}</div>}
    </div>
  );
}
