import { createPortal } from "react-dom";
import type { CaseDetail, Result } from "../api/client";

// The printable summary for the patient's doctor ("Print / save as PDF"). It is rendered outside
// the app (a portal on <body>), and the print stylesheet prints only this sheet: a clean document,
// no website around it, and no blank first page. On screen it is never shown.

const REGION: Record<string, string> = {
  brain: "Brain", eyes: "Eyes", ent: "Ear, nose & throat", thyroid: "Thyroid", heart: "Heart", lungs: "Lungs", stomach: "Stomach",
  liver: "Liver", intestines: "Intestines", kidneys: "Kidneys", bladder_prostate: "Bladder & prostate", reproductive: "Reproductive organs",
  blood: "Blood", bones_joints: "Bones & joints", skin: "Skin", mind: "Mind",
};
const STRENGTH: Record<string, string> = { stronger: "Stronger match", possible: "Possible match", weaker: "Weaker match" };

export default function PrintSummary({ c, patientLine }: { c: CaseDetail; patientLine: string }) {
  const r = c.result;
  const s = r?.summary;
  if (!r || !s || !s.explanations) return null;   // only for a finished four-round summary
  const p = c.profile_snapshot;
  const present = (s.red_flags ?? []).filter((x: Result) => x.present_now !== false);
  const safetyNet = (s.red_flags ?? []).filter((x: Result) => x.present_now === false);
  const meds = p?.medications_status === "listed" ? p.medications.map((m) => [m.name, m.dose, m.how_often].filter(Boolean).join(" · ")) : [];
  const reviewed = new Date(c.updated_at || c.created_at).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });

  return createPortal(
    <article className="print-sheet" aria-hidden>
      <header className="ps-head">
        <img src="/emblem.svg?v=4" alt="" width={46} height={46} />
        <div>
          <div className="ps-brand">ΛSCLEPIUS · AI case conference</div>
          <h1>Case summary to discuss with your doctor</h1>
          <p className="ps-meta">{patientLine} · {c.title} · reviewed {reviewed}</p>
        </div>
      </header>
      <p className="ps-disclaimer"><strong>Not a diagnosis or medical advice.</strong> Prepared by AI specialist agents (not licensed physicians)
        from the records the patient uploaded, as a starting point for a conversation with their own doctors. In an emergency call 911.</p>

      {r.emergency?.active && (
        <section className="ps-urgent">
          <h2>Needs attention today</h2>
          <ul>{(r.emergency.reasons ?? []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
        </section>
      )}

      {s.see_first?.length > 0 && (
        <section>
          <h2>Who to see first</h2>
          <ol>{s.see_first.map((x: Result, i: number) => (
            <li key={i}><strong>{x.who}</strong> <span className="ps-urg">({x.urgency === "urgent" ? "today" : x.urgency})</span>: {x.why}</li>))}</ol>
        </section>
      )}

      {present.length > 0 && (
        <section>
          <h2>Worth raising soon</h2>
          <ul>{present.map((x: Result, i: number) => <li key={i}><strong>{x.flag}</strong> {x.what_to_do}</li>)}</ul>
        </section>
      )}

      <section>
        <h2>Possible explanations the panel discussed</h2>
        <p className="ps-note">Each is a pattern to discuss, not a diagnosis. Strength comes from the panel's debate, not from a probability.</p>
        {s.explanations.length === 0 && <p>The panel did not find a connection across specialties that it could support.</p>}
        {s.explanations.map((e: Result) => (
          <div key={e.id} className="ps-card">
            <h3>{e.id} · {e.title} <span className="ps-strength">{STRENGTH[e.strength] ?? e.strength}</span></h3>
            <div className="ps-cols">
              <div><h4>Why it could fit</h4><ul>{e.why_it_fits.map((w: Result, i: number) => <li key={i}>{w.text}</li>)}</ul></div>
              <div><h4>What argues against it</h4><ul>{e.argues_against.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul></div>
            </div>
            {e.would_help_tell?.length > 0 && <p className="ps-tell"><strong>Could help tell:</strong> {e.would_help_tell.join(" · ")}</p>}
            <p className="ps-small">Areas: {e.regions.map((x: string) => REGION[x] ?? x).join(", ") || "—"} · Panel members: {e.specialists.map((x: Result) => x.name).join(", ")}</p>
          </div>
        ))}
      </section>

      {s.questions_for_doctors?.length > 0 && (
        <section>
          <h2>Questions to ask</h2>
          {s.questions_for_doctors.map((d: Result, i: number) => (
            <div key={i} className="ps-q"><h3>{d.doctor}</h3><ol>{d.questions.map((q: string, j: number) => <li key={j}>{q}</li>)}</ol></div>
          ))}
        </section>
      )}

      {s.medication_discussion?.length > 0 && (
        <section>
          <h2>Medicines to review with the prescribers</h2>
          <ul>{s.medication_discussion.map((m: Result, i: number) => <li key={i}>{m.text}</li>)}</ul>
          {meds.length > 0 && <p className="ps-small"><strong>Medicines the patient listed:</strong> {meds.join("; ")}</p>}
        </section>
      )}

      {s.key_findings?.length > 0 && (
        <section>
          <h2>What the records show</h2>
          <ul>{s.key_findings.map((k: Result, i: number) => <li key={i}>{k.text}</li>)}</ul>
        </section>
      )}

      {s.self_care?.steps?.length > 0 && !s.self_care.care_first && (
        <section>
          <h2>Self-care steps suggested meanwhile</h2>
          <ul>{s.self_care.steps.map((st: Result, i: number) => <li key={i}>{st.action} <span className="ps-small">(check first if: {st.check_first_if})</span></li>)}</ul>
        </section>
      )}

      {safetyNet.length > 0 && (
        <section>
          <h2>Seek care if</h2>
          <ul>{safetyNet.map((x: Result, i: number) => <li key={i}><strong>{x.flag}</strong> {x.what_to_do}</li>)}</ul>
        </section>
      )}

      {s.limitations?.length > 0 && (
        <section>
          <h2>What the panel could not assess</h2>
          <ul>{s.limitations.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul>
        </section>
      )}

      <footer className="ps-foot">Prepared with ΛSCLEPIUS, an educational AI case conference (not a medical device). Every finding is quoted from
        the patient's own records; the full reports, quotes and sources are in the app.</footer>
    </article>,
    document.body,
  );
}
