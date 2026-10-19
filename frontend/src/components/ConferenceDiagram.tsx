import type { Result } from "../api/client";
import { colorOf, SPECIALTY_ICONS } from "../lib/panel";

// How the conference ran, at the bottom of the case page: the four rounds in order, who took part,
// what came out of each, and what each one cost. Costs live here only, never on the panel itself.

type Call = { agent: string; label: string; input_tokens: number; cached_input_tokens: number; output_tokens: number; cost_usd: number; from_cache?: boolean };
type StageId = "reading" | "s1" | "s2" | "s3" | "s4" | "safety";

function stageOf(c: Call): StageId {
  const label = c.label.split(" (")[0];
  if (c.agent.startsWith("intake")) return "reading";
  if (c.agent === "safety_reviewer") return "safety";
  if (label.startsWith("r2.")) return "s2";
  if (label.startsWith("r3.") || label === "coordinator.challenge") return "s3";
  if (label.startsWith("r4.") || label === "coordinator.synthesis") return "s4";
  return "s1";  // round-1 reviews, the consult decision and a consult
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const fmt = (n: number) => n >= 10_000 ? `${(n / 1000).toFixed(0)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;

export default function ConferenceDiagram({ result, names }: { result: Result; names: Record<string, string> }) {
  const calls: Call[] = (result.usage?.calls ?? []).filter((c: Call) => !c.from_cache);
  const tot = (id: StageId) => {
    const cs = calls.filter((c) => stageOf(c) === id);
    return { calls: cs.length, input: cs.reduce((a, c) => a + c.input_tokens, 0), cached: cs.reduce((a, c) => a + c.cached_input_tokens, 0),
      output: cs.reduce((a, c) => a + c.output_tokens, 0), cost: cs.reduce((a, c) => a + c.cost_usd, 0) };
  };
  const nameOf = (id: string) => names[id] ?? (id === "lifestyle" ? "Lifestyle & prevention" : id.replace(/_/g, " "));
  const s = result.summary ?? {};
  const board: Result[] = result.board ?? [];
  const debate = result.debate ?? {};
  const cands: Result[] = debate.candidates ?? [];
  const stances: Result[] = debate.stances ?? [];
  const coordinator: string = result.modes?.coordinator ?? "internal_medicine";
  const r1 = [...Object.keys(result.specialists ?? {}), ...(result.consult ? [result.consult.specialty] : []),
    ...(result.pharmacist ? ["clinical_pharmacist"] : []), ...((result.lifestyle?.posts?.length || result.lifestyle?.steps?.length) ? ["lifestyle"] : [])];
  const r2 = Object.keys(result.round2 ?? {});
  const r3 = [coordinator, ...new Set(stances.map((x) => x.by as string))];
  const verdicts = (v: string) => cands.filter((c) => (c.challenge ?? c.skeptic)?.verdict === v).length;
  const stance = (k: string) => stances.filter((x) => x.stance === k).length;
  const steps = s.self_care?.steps?.length ?? 0;
  const docs = result.intake?.documents?.length ?? 0;
  const safety = result.safety ?? {};

  const stages = [
    { id: "s1" as const, n: 1, title: "Individual review", who: r1,
      what: [`Each specialist read only their own records`, `${board.length} findings posted on the shared case board`,
        `${new Set(board.map((p) => p.system)).size} body systems covered`] },
    { id: "s2" as const, n: 2, title: "Joint review", who: r2,
      what: [`Everyone read the whole board`, `${r2.reduce((a, k) => a + (result.round2[k].connections?.length ?? 0), 0)} connections proposed`,
        `${cands.length} candidate explanations after merging`] },
    { id: "s3" as const, n: 3, title: "Challenge", who: cands.length ? r3 : [],
      what: cands.length ? [`The coordinator challenged every candidate: ${verdicts("keep")} kept, ${verdicts("weaken")} weakened, ${verdicts("drop")} dropped`,
        `Specialists answered: ${stance("defend")} defended, ${stance("concede")} conceded, ${stance("support")} supported, ${stance("challenge")} challenged`,
        `${cands.filter((c) => c.removed).length} removed in the debate`] : ["No candidate reached the debate"] },
    { id: "s4" as const, n: 4, title: "Possible explanations and recommendations", who: [coordinator, ...(steps || s.self_care?.care_first ? ["lifestyle"] : [])],
      what: [`${s.explanations?.length ?? 0} explanation card${(s.explanations?.length ?? 0) === 1 ? "" : "s"} (not a diagnosis)`,
        `${s.see_first?.length ?? 0} doctors to see first`,
        s.self_care?.care_first ? "Self-care steps held back: get care first" : `${steps} self-care step${steps === 1 ? "" : "s"} with sources`] },
  ];
  const all = calls.reduce((a, c) => ({ input: a.input + c.input_tokens, cached: a.cached + c.cached_input_tokens, output: a.output + c.output_tokens, cost: a.cost + c.cost_usd }),
    { input: 0, cached: 0, output: 0, cost: 0 });
  const reading = tot("reading"), safe = tot("safety");

  return (
    <section className="card conference-diagram" aria-label="How the conference ran">
      <h2>How the conference ran</h2>
      <p className="muted small">The AI specialist agents worked in four rounds, then a safety reviewer checked everything the patient sees.
        Tokens are the units of text the model reads and writes; cached tokens are reused from earlier calls at a tenth of the price.</p>
      <div className="flow">
        <MiniStep title="Reading the records" line={`${docs} document${docs === 1 ? "" : "s"} read and routed`} t={reading} />
        {stages.map((st) => {
          const t = tot(st.id);
          return (
            <div key={st.id} className={`flow-stage ${t.calls ? "" : "skipped"}`}>
              <div className="flow-num">{st.n}</div>
              <h3>{st.title}</h3>
              <div className="flow-who">{st.who.map((id) => (
                <span key={id} className="who-dot" style={{ ["--c" as string]: colorOf(id) }} title={nameOf(id)}>{SPECIALTY_ICONS[id] ?? "•"}</span>
              ))}</div>
              <ul>{st.what.map((w, i) => <li key={i}>{w}</li>)}</ul>
              <div className="flow-tokens">{t.calls ? <>{fmt(t.input)} in ({fmt(t.cached)} cached) · {fmt(t.output)} out · <strong>${t.cost.toFixed(4)}</strong></> : "not part of this run"}</div>
            </div>
          );
        })}
        <MiniStep title="Safety review" line={`${plural(safety.model_edits?.length ?? 0, "edit")} by the reviewer · ${safety.code_blocked?.length ?? 0} blocked by code`} t={safe} />
      </div>
      <div className="flow-total">
        <div><span className="muted small">Total cost</span><strong>${all.cost.toFixed(4)}</strong></div>
        <div><span className="muted small">Tokens read</span><strong>{all.input.toLocaleString()}</strong></div>
        <div><span className="muted small">Of which cached</span><strong>{all.input ? Math.round((100 * all.cached) / all.input) : 0}%</strong></div>
        <div><span className="muted small">Tokens written</span><strong>{all.output.toLocaleString()}</strong></div>
        <div><span className="muted small">Model calls</span><strong>{calls.length}</strong></div>
        <div><span className="muted small">Time</span><strong>{result.seconds ? `${Math.round(result.seconds)} s` : "—"}</strong></div>
      </div>
    </section>
  );
}

function MiniStep({ title, line, t }: { title: string; line: string; t: { calls: number; input: number; cached: number; output: number; cost: number } }) {
  return (
    <div className="flow-mini">
      <h4>{title}</h4>
      <p className="small">{line}</p>
      <div className="flow-tokens">{t.calls ? <>{fmt(t.input + t.output)} tokens · <strong>${t.cost.toFixed(4)}</strong></> : "from the saved reading (no new cost)"}</div>
    </div>
  );
}
