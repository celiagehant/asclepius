import { useEffect, useState } from "react";
import { shortName, type RosterEntry } from "../lib/panel";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;
interface UsageRun { run_id: string; kind: string; started: string; calls: Row[]; totals: Row }

const fmt = (n: number) => n.toLocaleString();

export interface UsageData { runs: UsageRun[]; prices_per_1m: Record<string, number> }

/** Every model call for this case: tokens, cost and latency per agent, from the usage log. */
export default function RunDetails({ caseId, roster, refreshKey }: { caseId: number; roster: RosterEntry[]; refreshKey?: number }) {
  const [data, setData] = useState<UsageData | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (open) fetch(`/api/cases/${caseId}/usage`, { credentials: "same-origin" }).then((r) => r.json()).then(setData).catch(() => undefined);
  }, [open, caseId, refreshKey]);
  return <RunDetailsView data={data} roster={roster} onToggle={setOpen} />;
}

/** The Run details panel for given data (used by the app and by the offline demo). */
export function RunDetailsView({ data, roster, onToggle }: { data: UsageData | null; roster: RosterEntry[]; onToggle?: (open: boolean) => void }) {
  const names: Record<string, string> = { ...Object.fromEntries(roster.map((r) => [r.id, shortName(r.name)])),
    intake: "Intake", coordinator: "Coordinator", safety_reviewer: "Safety reviewer" };
  return (
    <details className="card run-details" onToggle={(e) => onToggle?.((e.target as HTMLDetailsElement).open)}>
      <summary><strong>Run details</strong> <span className="muted small">· tokens, cost and latency for every agent call</span></summary>
      {!data ? <p className="muted small">Loading…</p> : data.runs.length === 0 ? <p className="muted small">No model calls recorded for this case yet.</p> : (
        <>
          <p className="muted small">Prices per million tokens (gpt-6-luna): input ${data.prices_per_1m.input}, cached input ${data.prices_per_1m.cached_input},
            cache write ${data.prices_per_1m.cache_write}, output ${data.prices_per_1m.output}. Input includes cached and cache-write tokens.</p>
          {data.runs.map((run) => <RunTable key={run.run_id} run={run} names={names} />)}
        </>
      )}
    </details>
  );
}

function RunTable({ run, names }: { run: UsageRun; names: Record<string, string> }) {
  const byMember: Record<string, Row> = {};
  for (const c of run.calls) {
    const k = c.member ?? c.agent;
    const g = (byMember[k] ??= { calls: 0, requests: 0, input_tokens: 0, cached_input_tokens: 0, cache_write_tokens: 0, output_tokens: 0, cost_usd: 0, seconds: 0 });
    g.calls += 1;
    for (const f of ["requests", "input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "cost_usd", "seconds"]) g[f] += c[f] ?? 0;
  }
  const t = run.totals;
  const hit = t.input_tokens ? Math.round((t.cached_input_tokens / t.input_tokens) * 100) : 0;
  return (
    <div className="usage-run">
      <h3>{run.kind === "chat" ? "Chat question" : "Panel review"} <span className="muted small">· {new Date(run.started).toLocaleString()} · {run.calls.length} calls ·
        ${t.cost_usd.toFixed(5)} · {hit}% of input read from cache</span></h3>
      <div className="table-scroll">
        <table className="values usage">
          <thead><tr><th>Agent</th><th>Calls</th><th>Requests</th><th>Input</th><th>Cached</th><th>Cache write</th><th>Output</th><th>Cost</th><th>Latency</th></tr></thead>
          <tbody>
            {Object.entries(byMember).sort((a, b) => b[1].cost_usd - a[1].cost_usd).map(([k, g]) => (
              <tr key={k}>
                <td>{names[k] ?? k}</td><td>{g.calls}</td><td>{g.requests}</td><td>{fmt(g.input_tokens)}</td><td>{fmt(g.cached_input_tokens)}</td>
                <td>{fmt(g.cache_write_tokens)}</td><td>{fmt(g.output_tokens)}</td><td>${g.cost_usd.toFixed(5)}</td><td>{g.seconds.toFixed(1)}s</td>
              </tr>
            ))}
            <tr className="total-row">
              <td>Total</td><td>{run.calls.length}</td><td>{t.requests}</td><td>{fmt(t.input_tokens)}</td><td>{fmt(t.cached_input_tokens)}</td>
              <td>{fmt(t.cache_write_tokens)}</td><td>{fmt(t.output_tokens)}</td><td>${t.cost_usd.toFixed(5)}</td><td>—</td>
            </tr>
          </tbody>
        </table>
      </div>
      <details className="call-list">
        <summary className="small">Every call ({run.calls.length})</summary>
        <div className="table-scroll">
          <table className="values usage small">
            <thead><tr><th>Agent</th><th>Step</th><th>In</th><th>Cached</th><th>Write</th><th>Out</th><th>Cost</th><th>Latency</th><th></th></tr></thead>
            <tbody>{run.calls.map((c) => (
              <tr key={c.id} className={c.ok ? "" : "failed-row"}>
                <td>{names[c.member] ?? c.member ?? c.agent}</td><td>{c.label}</td><td>{fmt(c.input_tokens)}</td><td>{fmt(c.cached_input_tokens)}</td>
                <td>{fmt(c.cache_write_tokens)}</td><td>{fmt(c.output_tokens)}</td><td>${c.cost_usd.toFixed(5)}</td><td>{c.seconds.toFixed(1)}s</td>
                <td>{c.from_cache ? "from file cache" : c.ok ? "" : "failed"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
