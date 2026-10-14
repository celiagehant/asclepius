import type { Result } from "../api/client";

const REGION_LABELS: Record<string, string> = {
  brain: "Brain", eyes: "Eyes", ent: "Ear, nose & throat", thyroid: "Thyroid", heart: "Heart", lungs: "Lungs", stomach: "Stomach",
  liver: "Liver", intestines: "Intestines", kidneys: "Kidneys", bladder_prostate: "Bladder & prostate", reproductive: "Reproductive organs",
  blood: "Blood", bones_joints: "Bones & joints", skin: "Skin", mind: "Mind",
};
const SEVERITY_ORDER: Record<string, number> = { urgent: 0, discuss: 1, watch: 2 };

function specialtyOf(ref: string) {
  return ref.split(".")[0].replace(/_/g, " ");
}

function Refs({ refs }: { refs: string[] }) {
  const specs = Array.from(new Set(refs.map(specialtyOf)));
  return <span className="chips inline">{specs.map((s) => <span key={s} className="chip">{s}</span>)}</span>;
}

export default function SummaryView({ result }: { result: Result }) {
  const s = result.summary;
  return (
    <div className="summary">
      {!s && (
        <section className="card">
          <h2>The panel could not finish a full summary</h2>
          <p>{result.stop_reason}</p>
          <p className="muted">What the specialists found is shown below.</p>
        </section>
      )}

      {s && (
        <>
          <section className="card summary-lead">
            <p className="eyebrow">Case summary · prepared by AI specialist agents for you to discuss with your doctors</p>
            <p className="lead">{s.plain_language_summary}</p>
          </section>

          {s.red_flags.some((r: Result) => r.present_now !== false) && (
            <section className="card flags">
              <h2>Needs attention</h2>
              {s.red_flags.filter((r: Result) => r.present_now !== false).map((r: Result, i: number) => (
                <div key={i} className={`flag flag-${r.urgency}`}>
                  <span className="flag-badge">{r.urgency === "urgent" ? "Today" : "Soon"}</span>
                  <div><strong>{r.flag}</strong><p>{r.what_to_do}</p></div>
                </div>
              ))}
            </section>
          )}
          {s.red_flags.some((r: Result) => r.present_now === false) && (
            <section className="card flags safety-net">
              <h2>Seek care if…</h2>
              {s.red_flags.filter((r: Result) => r.present_now === false).map((r: Result, i: number) => (
                <div key={i} className="flag flag-net">
                  <span className="flag-badge">If</span>
                  <div><strong>{r.flag}</strong><p>{r.what_to_do}</p></div>
                </div>
              ))}
            </section>
          )}

          <div className="summary-grid">
            <section className="card">
              <h2>What the records show</h2>
              <ul className="points">{s.key_findings.map((k: Result, i: number) => <li key={i}>{k.text} <Refs refs={k.finding_refs} /></li>)}</ul>
            </section>
            <section className="card">
              <h2>Connections worth asking about</h2>
              {s.connections.length === 0 ? <p className="muted">No cross-specialty connections were found.</p> :
                <ul className="points">{s.connections.map((k: Result, i: number) => <li key={i}>{k.text} <Refs refs={k.finding_refs} /></li>)}</ul>}
            </section>
          </div>

          {s.medication_discussion.length > 0 && (
            <section className="card">
              <h2>Medicines to discuss with your prescribers</h2>
              <p className="muted small">The panel never tells you to start, stop or change a medicine. These are questions for the doctors who prescribe them.</p>
              <ul className="points">{s.medication_discussion.map((k: Result, i: number) => <li key={i}>{k.text}</li>)}</ul>
            </section>
          )}

          <section className="card">
            <h2>Questions to bring to each doctor</h2>
            <div className="doctor-grid">
              {s.questions_for_doctors.map((d: Result, i: number) => (
                <div key={i} className="doctor-card">
                  <h3>{d.doctor}</h3>
                  <ol>{d.questions.map((q: string, j: number) => <li key={j}>{q}</li>)}</ol>
                </div>
              ))}
            </div>
          </section>

          <div className="summary-grid">
            <section className="card print-only-in-room">
              <h2>Affected areas</h2>
              <ul className="regions">
                {[...s.body_regions].sort((a: Result, b: Result) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]).map((b: Result) => (
                  <li key={b.region} className={`region sev-${b.severity}`}>
                    <span className="region-name">{REGION_LABELS[b.region] ?? b.region}</span>
                    <span className="sev">{b.severity}</span>
                    <span className="muted small">{b.reason}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="card">
              <h2>Specialists you could ask about</h2>
              {s.suggested_specialists.length === 0 ? <p className="muted">None suggested.</p> : (
                <ul className="points">{s.suggested_specialists.map((x: Result, i: number) => <li key={i}><strong>{x.specialty}</strong> ({x.urgency}): {x.reason}</li>)}</ul>
              )}
              {s.limitations.length > 0 && (<><h3 className="sub">What the panel could not assess</h3>
                <ul className="points muted">{s.limitations.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul></>)}
            </section>
          </div>
        </>
      )}

    </div>
  );
}


export function SpecialistReports({ result }: { result: Result }) {
  return (
    <section className="card">
      <h2>Specialist reports</h2>
      <p className="muted small">Every finding quotes the record it comes from. Sources are only those the agents actually retrieved.</p>
      {Object.values(result.specialists ?? {}).map((r: Result) => <SpecialistReport key={r.specialty} r={r} />)}
      {result.consult && <SpecialistReport r={result.consult} />}
      {result.pharmacist && <PharmacistReport p={result.pharmacist} />}
    </section>
  );
}

export function RunMeta({ result }: { result: Result }) {
  return (
    <section className="card meta">
      <div>
        <strong>How this summary was made.</strong> {Object.keys(result.specialists ?? {}).length} AI specialist agents
        {result.pharmacist ? " and a clinical pharmacist agent" : ""} reviewed the records, discussed them in two rounds, and a coordinator
        wrote this summary, which a safety reviewer then checked. Model calls: {result.usage?.totals?.model_calls} · cost $
        {result.usage?.totals?.cost_usd?.toFixed(4)} · {result.seconds}s.
      </div>
    </section>
  );
}

function SpecialistReport({ r }: { r: Result }) {
  return (
    <details className="report">
      <summary>
        <strong>{r.name}{r.consult ? " (consult)" : ""}</strong>
        <span className="muted small"> · {r.findings.length} findings · confidence {r.confidence}{r.insufficient_information ? " · more information needed" : ""}</span>
      </summary>
      <ul className="findings">
        {r.findings.map((f: Result) => (
          <li key={f.id}>
            <span className={`sig sig-${f.significance}`}>{f.significance.replace(/_/g, " ")}</span> {f.statement}
            <blockquote>“{f.quote}” <cite>{f.document}</cite></blockquote>
          </li>
        ))}
      </ul>
      {r.abnormal_values.length > 0 && (
        <table className="values">
          <thead><tr><th>Test</th><th>Value</th><th>Judged against</th></tr></thead>
          <tbody>{r.abnormal_values.map((a: Result, i: number) => (
            <tr key={i}><td>{a.test}</td><td>{a.value} {a.unit ?? ""} <em>({a.interpretation.replace(/_/g, " ")})</em></td><td className="small">{a.reference_used}</td></tr>
          ))}</tbody>
        </table>
      )}
      {r.sources.length > 0 && (
        <p className="small">Sources: {r.sources.map((src: Result, i: number) => <a key={i} href={src.url} target="_blank" rel="noreferrer">{src.title}</a>).reduce((acc: Result[], el: Result, i: number) => (i ? [...acc, " · ", el] : [el]), [])}</p>
      )}
      {r.source_note && <p className="muted small">{r.source_note}</p>}
    </details>
  );
}

function PharmacistReport({ p }: { p: Result }) {
  return (
    <details className="report">
      <summary><strong>Clinical pharmacist</strong><span className="muted small"> · {p.combined_list.length} medicines · {p.issues.length} items to discuss</span></summary>
      <table className="values">
        <thead><tr><th>Medicine</th><th>Dose</th><th>Prescriber</th><th>Seen in</th></tr></thead>
        <tbody>{p.combined_list.map((m: Result, i: number) => (
          <tr key={i}><td>{m.medication}</td><td className="small">{m.dose_and_schedule ?? "—"}</td><td className="small">{m.prescriber ?? "—"}</td><td className="small">{m.sources.join(", ")}</td></tr>
        ))}</tbody>
      </table>
      <ul className="findings">
        {p.issues.map((i: Result) => (
          <li key={i.id}>
            <span className={`sig sig-${i.urgency === "routine" ? "unclear" : "abnormal"}`}>{i.kind.replace(/_/g, " ")}</span> {i.explanation}
            <div className="muted small">Discuss with: {i.discuss_with.join(", ")}
              {i.source_urls.map((u: string, j: number) => <span key={j}> · <a href={u} target="_blank" rel="noreferrer">FDA label</a></span>)}</div>
          </li>
        ))}
      </ul>
      {p.source_note && <p className="muted small">{p.source_note}</p>}
    </details>
  );
}
