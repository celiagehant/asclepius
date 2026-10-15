import type { Result } from "../api/client";
import { colorOf } from "../lib/panel";

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

export interface CardFocus { cards: string[]; refs: string[] }

const STRENGTH_LABEL: Record<string, string> = { stronger: "Stronger match", possible: "Possible match", weaker: "Weaker match" };
const CATEGORY_ICON: Record<string, string> = {
  sleep: "☾", activity: "🚶", eating_pattern: "🍽", hydration: "💧", symptom_tracking: "📓", stress: "🌿",
  avoid_known_trigger: "⛱", visit_preparation: "📋",
};

export default function SummaryView({ result, focus, onFocusCard, onFocusRef, names }: {
  result: Result; focus?: CardFocus; onFocusCard?: (card: Result | null, pin?: boolean) => void; onFocusRef?: (ref: string) => void;
  names?: Record<string, string>;
}) {
  const s = result.summary;
  const legacy = s && !s.explanations;  // a case saved before the four-round conference
  const present = s ? s.red_flags.filter((r: Result) => r.present_now !== false) : [];
  const safetyNet = s ? s.red_flags.filter((r: Result) => r.present_now === false) : [];
  const sc = s?.self_care;
  return (
    <div className="summary">
      {!s && (
        <section className="card">
          <h2>The panel could not finish a full summary</h2>
          <p>{result.stop_reason}</p>
          <p className="muted">What the specialists found is shown below.</p>
        </section>
      )}

      {s && !legacy && (
        <>
          <section className="card explanations" aria-label="Possible explanations">
            <p className="eyebrow">Prepared by AI specialist agents for you to discuss with your doctors</p>
            <h2>Possible explanations the panel discussed</h2>
            {s.explanations.length === 0 && <p className="muted">The panel did not find a connection across specialties that it could support. The findings below are still worth discussing.</p>}
            <div className="ex-cards">
              {s.explanations.map((c: Result, i: number) => (
                <ExplanationCard key={c.id} card={c} rank={i + 1} names={names ?? {}} active={focus?.cards.includes(c.id) ?? false}
                  faded={!!focus?.cards.length && !focus.cards.includes(c.id)} onFocus={onFocusCard} onRef={onFocusRef} />
              ))}
            </div>
            {s.explanations.length === 1 && <p className="muted small">Only one explanation survived the panel's debate; the panel does not pad the list.</p>}
          </section>

          <section className="card see-first">
            <h2>Who to see first</h2>
            {present.map((r: Result, i: number) => (
              <div key={`f${i}`} className={`flag flag-${r.urgency}`}>
                <span className="flag-badge">{r.urgency === "urgent" ? "Today" : "Soon"}</span>
                <div><strong>{r.flag}</strong><p>{r.what_to_do}</p></div>
              </div>
            ))}
            <ol className="see-list">
              {s.see_first.map((x: Result, i: number) => (
                <li key={i} className={`see-${x.urgency}`}>
                  <div className="see-who"><strong>{x.who}</strong> <span className={`urg urg-${x.urgency}`}>{x.urgency === "urgent" ? "today" : x.urgency}</span>
                    {x.related_to.map((id: string) => <button key={id} className="card-ref" onClick={() => onFocusCard?.(s.explanations.find((c: Result) => c.id === id) ?? null, true)}>{id}</button>)}
                  </div>
                  <p>{x.why}</p>
                </li>
              ))}
            </ol>
          </section>

          <section className="card self-care">
            <h2>What you can do now</h2>
            {sc?.care_first ? (
              <div className="care-first">{sc.message}</div>
            ) : sc?.steps?.length ? (
              <>
                <p className="muted small">Low-risk steps from the lifestyle and prevention agent, each with a source. They do not treat anything and never replace your doctors' advice.
                  {sc.limits?.length ? ` Activity suggestions say to ask your doctor first, because ${sc.limits.join(" and ")}.` : ""}</p>
                <ul className="steps">
                  {sc.steps.map((st: Result, i: number) => (
                    <li key={i}>
                      <span className="step-icon" aria-hidden>{CATEGORY_ICON[st.category] ?? "•"}</span>
                      <div>
                        <strong>{st.action}</strong>
                        <p>{st.why_it_may_help}</p>
                        <p className="muted small">How to track it: {st.how_to_track}</p>
                        <p className="small check-first"><strong>Check with a doctor first:</strong> {st.check_first_if}</p>
                        <a className="small" href={st.source_url} target="_blank" rel="noreferrer">Source: {st.source_title || "MedlinePlus"} (MedlinePlus)</a>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            ) : <p className="muted">No self-care steps passed the safety rules for this case. Bring your questions to your doctors.</p>}
          </section>

          <section className="card">
            <h2>Questions to bring to each doctor</h2>
            <div className="doctor-grid">
              {s.questions_for_doctors.map((d: Result, i: number) => (
                <div key={i} className="doctor-card">
                  <h3>{d.doctor} {(d.related_to ?? []).map((id: string) => <button key={id} className="card-ref" onClick={() => onFocusCard?.(s.explanations.find((c: Result) => c.id === id) ?? null, true)}>{id}</button>)}</h3>
                  <ol>{d.questions.map((q: string, j: number) => <li key={j}>{q}</li>)}</ol>
                </div>
              ))}
            </div>
          </section>

          {s.medication_discussion.length > 0 && (
            <section className="card">
              <h2>Medicines to discuss with your prescribers</h2>
              <p className="muted small">The panel never tells you to start, stop or change a medicine. These are questions for the doctors who prescribe them.</p>
              <ul className="points">{s.medication_discussion.map((k: Result, i: number) => <li key={i}>{k.text}</li>)}</ul>
            </section>
          )}

          <details className="card more-details">
            <summary><strong>More details</strong> <span className="muted small">· summary in plain words, what the records show, safety net, limits</span></summary>
            <section>
              <h3 className="sub">In plain words</h3>
              <p className="lead">{s.plain_language_summary}</p>
            </section>
            {safetyNet.length > 0 && (
              <section className="flags safety-net">
                <h3 className="sub">Seek care if…</h3>
                {safetyNet.map((r: Result, i: number) => (
                  <div key={i} className="flag flag-net"><span className="flag-badge">If</span><div><strong>{r.flag}</strong><p>{r.what_to_do}</p></div></div>
                ))}
              </section>
            )}
            <section>
              <h3 className="sub">What the records show</h3>
              <ul className="points">{s.key_findings.map((k: Result, i: number) => <li key={i}>{k.text} <Refs refs={k.finding_refs} /></li>)}</ul>
            </section>
            <section>
              <h3 className="sub">Affected areas</h3>
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
            {s.limitations.length > 0 && (
              <section>
                <h3 className="sub">What the panel could not assess</h3>
                <ul className="points muted">{s.limitations.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul>
              </section>
            )}
          </details>
        </>
      )}

      {legacy && <LegacySummary s={s} />}
    </div>
  );
}

function ExplanationCard({ card, rank, names, active, faded, onFocus, onRef }: {
  card: Result; rank: number; names: Record<string, string>; active: boolean; faded: boolean;
  onFocus?: (card: Result | null, pin?: boolean) => void; onRef?: (ref: string) => void;
}) {
  return (
    <article className={`ex-card strength-${card.strength} ${active ? "on" : ""} ${faded ? "faded" : ""}`} tabIndex={0}
      onMouseEnter={() => onFocus?.(card)} onMouseLeave={() => onFocus?.(null)}
      onClick={() => onFocus?.(card, true)} onKeyDown={(e) => { if (e.key === "Enter") onFocus?.(card, true); }}
      aria-label={`Possible explanation ${rank}: ${card.title}`}>
      <div className="ex-top">
        <span className="ex-rank">{card.id}</span>
        <span className={`ex-strength s-${card.strength}`}>{STRENGTH_LABEL[card.strength] ?? card.strength}</span>
        {card.regions.length > 0 && <span className="ex-regions">{card.regions.map((r: string) => REGION_LABELS[r] ?? r).join(" · ")}</span>}
      </div>
      <h3>{card.title}</h3>
      <p className="ex-label">ⓘ {card.label}</p>
      <div className="ex-cols">
        <div>
          <h4>Why it could fit</h4>
          <ul>{card.why_it_fits.map((w: Result, i: number) => (
            <li key={i}>{w.text} {w.finding_refs.map((r: string) => (
              <button key={r} className="ref-chip" onClick={(e) => { e.stopPropagation(); onRef?.(r); }} title="Show this post on the case board">{r}</button>))}</li>
          ))}</ul>
        </div>
        <div className="ex-against">
          <h4>What argues against it</h4>
          <ul>{card.argues_against.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
        </div>
      </div>
      {card.would_help_tell.length > 0 && (
        <div className="ex-tell"><h4>What could help tell</h4><ul>{card.would_help_tell.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul></div>
      )}
      <div className="ex-foot">
        <span className="ex-who">{card.specialists.map((m: Result) => <span key={m.id} className="who-chip" style={{ ["--c" as string]: colorOf(m.id) }}>{names[m.id] ?? m.name}</span>)}</span>
        {card.pattern && <a href={card.pattern.source} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>Learn about this pattern (MedlinePlus)</a>}
      </div>
      {card.debate?.skeptic_verdict && (
        <p className="ex-debate muted small">Debate: the skeptic said <em>{card.debate.skeptic_verdict}</em>
          {card.debate.supports ? ` · ${card.debate.supports} support` : ""}{card.debate.challenges ? ` · ${card.debate.challenges} challenge` : ""}
          {card.debate.conceded_by?.length ? ` · conceded by ${card.debate.conceded_by.length}` : ""}</p>
      )}
    </article>
  );
}

function LegacySummary({ s }: { s: Result }) {
  return (
    <>
      <section className="card summary-lead">
        <p className="eyebrow">Case summary · prepared by AI specialist agents for you to discuss with your doctors</p>
        <p className="lead">{s.plain_language_summary}</p>
      </section>
      <section className="card">
        <h2>Connections worth asking about</h2>
        {(s.connections ?? []).length === 0 ? <p className="muted">No cross-specialty connections were found.</p> :
          <ul className="points">{s.connections.map((k: Result, i: number) => <li key={i}>{k.text} <Refs refs={k.finding_refs} /></li>)}</ul>}
        <p className="muted small">This case was reviewed before the panel's four-round conference. Convene the panel again for explanation cards.</p>
      </section>
      <section className="card">
        <h2>Questions to bring to each doctor</h2>
        <div className="doctor-grid">
          {s.questions_for_doctors.map((d: Result, i: number) => (
            <div key={i} className="doctor-card"><h3>{d.doctor}</h3><ol>{d.questions.map((q: string, j: number) => <li key={j}>{q}</li>)}</ol></div>
          ))}
        </div>
      </section>
    </>
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
        {result.pharmacist ? " and a clinical pharmacist agent" : ""} reviewed the records and posted their findings on a shared case board;
        they proposed connections, a skeptic challenged them in a debate, a lifestyle agent suggested safe self-care steps, and a
        coordinator wrote this summary, which a safety reviewer then checked. Model calls: {result.usage?.totals?.model_calls} · cost $
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
