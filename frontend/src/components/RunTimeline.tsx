import { useEffect, useMemo, useState } from "react";
import type { CaseDetail } from "../api/client";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Ev = Record<string, any> & { seq: number; type: string; t: number };

const EVENT_TYPES = ["run_started", "document_routed", "panel_selected", "specialist_started", "tool_call", "specialist_done",
  "conference_round", "comment", "coordinator_thinking", "safety_check", "spend", "final", "error",
  "board_post", "board_ready", "connection", "challenge", "stance", "explanations"];
const STAGES = ["Reading records", "Round 1: independent reviews", "Round 2: case conference", "Coordinator", "Safety review", "Done"];
const TOOL_NAMES: Record<string, string> = { search_pubmed: "PubMed", search_medlineplus: "MedlinePlus", fda_label_search: "FDA label" };

function stageOf(events: Ev[]): number {
  let s = 0;
  for (const e of events) {
    if (e.type === "conference_round" && e.round === 1) s = Math.max(s, 1);
    if (e.type === "conference_round" && e.round === 2) s = Math.max(s, 2);
    if (e.type === "coordinator_thinking" && e.stage === "synthesis") s = Math.max(s, 3);
    if (e.type === "safety_check") s = Math.max(s, 4);
    if (e.type === "final") s = 5;
  }
  return s;
}

export function useRunEvents(caseId: number, onEnd?: () => void): Ev[] {
  const [events, setEvents] = useState<Ev[]>([]);
  useEffect(() => {
    const source = new EventSource(`/api/cases/${caseId}/events`);
    const seen = new Set<number>();
    const handler = (msg: MessageEvent) => {
      const e = JSON.parse(msg.data) as Ev;
      if (seen.has(e.seq)) return;
      seen.add(e.seq);
      setEvents((cur) => [...cur, e]);
    };
    EVENT_TYPES.forEach((t) => source.addEventListener(t, handler as EventListener));
    source.addEventListener("end", () => { source.close(); onEnd?.(); });
    return () => source.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);
  return events;
}

/** Wait for the saved result after the stream ends (it is written a moment later). */
export async function waitForResult(onFinished: () => Promise<CaseDetail>): Promise<void> {
  for (let i = 0; i < 20; i++) {
    const c = await onFinished();
    if (c.status !== "running") return;
    await new Promise((r) => setTimeout(r, 1000));
  }
}

export function PanelActivity({ events, live, waiting, compact }: { events: Ev[]; live?: boolean; waiting?: boolean; compact?: boolean }) {
  const view = useMemo(() => {
    const docs = events.filter((e) => e.type === "document_routed");
    const panel = events.find((e) => e.type === "panel_selected");
    const spend = [...events].reverse().find((e) => e.type === "spend");
    const agents: Record<string, { name: string; r1: string; r2: string; tools: Ev[]; detail?: string }> = {};
    const ensure = (spec: string, name?: string) => (agents[spec] ??= { name: name ?? spec, r1: "waiting", r2: "—", tools: [] });
    panel?.active?.forEach((a: { specialty: string; name: string }) => ensure(a.specialty, a.name));
    if (panel?.pharmacist) ensure("clinical_pharmacist", "Clinical pharmacist");
    for (const e of events) {
      if (e.type === "specialist_started") {
        const a = ensure(e.specialty, e.name);
        if (e.round === 1) a.r1 = "working"; else a.r2 = "working";
        if (e.consult) a.name = `${e.name} (consult)`;
      }
      if (e.type === "specialist_done") {
        const a = ensure(e.specialty, e.name);
        if (e.round === 1) { a.r1 = "done"; a.detail = `${e.findings} findings · confidence ${e.confidence}`; }
        else a.r2 = "done";
      }
      if (e.type === "tool_call") ensure(e.specialty).tools.push(e);
      if (e.type === "error" && e.specialty && !e.retrying) ensure(e.specialty).r1 = "failed";
    }
    const feed = events.filter((e) => ["comment", "coordinator_thinking", "safety_check", "error", "conference_round", "final"].includes(e.type));
    return { docs, panel, spend, agents, feed, stage: stageOf(events), final: events.find((e) => e.type === "final") };
  }, [events]);

  return (
    <div className="activity">
      <section className="card">
        <div className="stepper">
          {STAGES.map((s, i) => (
            <div key={s} className={`stage ${i < view.stage ? "done" : i === view.stage ? (live && !view.final ? "active" : "done") : ""}`}>
              <span className="dot-stage" />{s}
            </div>
          ))}
        </div>
        <div className="spend-line muted small">
          {view.spend ? <>Spent so far: <strong>${view.spend.total_usd.toFixed(4)}</strong> · {(view.spend.input_tokens + view.spend.output_tokens).toLocaleString()} tokens</> : "Starting…"}
          {view.final && <> · finished in {view.final.seconds}s · {view.final.status}</>}
          {waiting && " · preparing the summary…"}
        </div>
      </section>

      <div className={compact ? "activity-stack" : "activity-grid"}>
        <section className="card">
          <h3>Records</h3>
          {view.docs.length === 0 && <p className="muted small">Reading and routing each record…</p>}
          <ul className="routed">
            {view.docs.map((d) => (
              <li key={d.seq}>
                <strong>{d.document}</strong> <span className="doc-kind">{d.read_by}</span>
                <div className="muted small">{d.summary}</div>
                <div className="chips">{(d.specialties ?? []).map((s: string) => <span key={s} className="chip">{s.replace(/_/g, " ")}</span>)}</div>
                {d.hidden_text?.length > 0 && <div className="hidden-warn">Hidden text removed: {d.hidden_text.join("; ")}</div>}
              </li>
            ))}
          </ul>
        </section>

        {!compact && <section className="card">
          <h3>The panel {view.panel && <span className="muted small">· led by {view.panel.coordinator}</span>}</h3>
          {!view.panel && <p className="muted small">Choosing specialists…</p>}
          <div className="agents">
            {Object.entries(view.agents).map(([spec, a]) => (
              <div key={spec} className={`agent agent-${a.r1}`}>
                <div className="agent-head">
                  <span className={`status-dot s-${a.r1}`} />
                  <strong>{a.name}</strong>
                  <span className="muted small">{a.r1 === "done" ? a.detail : a.r1}{a.r2 !== "—" ? ` · round 2: ${a.r2}` : ""}</span>
                </div>
                {a.tools.map((t) => (
                  <div key={t.seq} className="tool small">
                    ⌕ {TOOL_NAMES[t.tool] ?? t.tool}: "{t.args.query ?? t.args.drug}" <span className={t.status === "ok" ? "ok-text" : "muted"}>{t.status === "ok" ? "found" : t.status.replace("_", " ")}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
          {(view.panel?.consider?.length ?? 0) > 0 && <p className="muted small">Consider seeing (over the cap of 5): {view.panel?.consider.join(", ")}</p>}
        </section>}
      </div>

      <section className="card">
        <h3>Conference log</h3>
        <ul className="feed">
          {view.feed.length === 0 && <li className="muted small">The specialists are reviewing their records independently…</li>}
          {view.feed.map((e) => <FeedItem key={e.seq} e={e} />)}
        </ul>
      </section>
    </div>
  );
}

function FeedItem({ e }: { e: Ev }) {
  const name = (s: string) => s.replace(/_/g, " ");
  if (e.type === "comment") {
    return <li className={`feed-${e.kind}`}><span className="feed-kind">{e.kind}</span> <strong>{name(e.from_)}</strong> → {name(e.to)}: {e.text}</li>;
  }
  if (e.type === "conference_round") {
    return <li className="feed-round">Round {e.round} {e.status}{e.note ? ` · ${e.note}` : ""}</li>;
  }
  if (e.type === "coordinator_thinking") {
    return <li className="feed-coord">Coordinator: {e.stage === "synthesis" ? "writing the case summary" : e.stage === "consult" ? `considering one more specialist (${(e.candidates ?? []).join(", ")})` : e.consult ? `called in ${name(e.consult)}: ${e.reason}` : `no extra consult: ${e.reason}`}</li>;
  }
  if (e.type === "safety_check") {
    const txt = e.stage === "model" ? `reviewer made ${e.edits} edit(s), added ${e.missed_red_flags} missed red flag(s)` :
      e.stage === "code" ? `code checks blocked ${e.blocked} item(s)` : e.stage === "done" ? (e.emergency ? "emergency banner raised" : "summary approved") : "checking the summary";
    return <li className="feed-safety">Safety: {txt}</li>;
  }
  if (e.type === "error") return <li className="feed-error">{e.retrying ? "Retrying" : "Problem"}: {e.agent}: {e.message}</li>;
  if (e.type === "final") return <li className="feed-final">Finished: {e.stop_reason}</li>;
  return null;
}
