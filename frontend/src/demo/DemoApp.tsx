// The offline demo: one HTML file, no server, no login, no API key. It replays real recorded
// runs of the four synthetic demo patients using the same components as the app.
import { useEffect, useMemo, useState } from "react";
import type { ChatMessage, ProfileData } from "../api/client";
import BodyMap from "../components/BodyMap";
import { DisclaimerBar, EmergencyBanner } from "../components/Common";
import PanelTable from "../components/PanelTable";
import { RunDetailsView, type UsageData } from "../components/RunDetails";
import { PanelActivity } from "../components/RunTimeline";
import SummaryView, { RunMeta, SpecialistReports } from "../components/SummaryView";
import { regionsFromSummary, type ChatOverlay, type Ev, type RosterEntry } from "../lib/panel";
import { LABELS } from "../lib/questionnaire";
import DemoChat from "./DemoChat";

export interface DemoDoc { name: string; kind: string; read_by: string; text: string; image?: string | null; hidden_text: string[] }
export interface DemoChatItem { question: string; message: ChatMessage; seconds: number; events: Ev[] }
export interface DemoCase {
  case_id: string; case_title: string; case_summary: string; recorded_at: string; profile: ProfileData; age: number;
  main_concern: string; documents: DemoDoc[]; result: any; events: Ev[]; chat: DemoChatItem[]; usage: UsageData; // eslint-disable-line @typescript-eslint/no-explicit-any
}
export interface DemoData {
  generated_at: string; author: string; course: string; model: string; roster: RosterEntry[]; cases: DemoCase[];
  headline: { cost_per_case: number; caching_saving: number; monthly_per_user: number; monthly_10k: number;
              attacks_succeeded_on: string; influenced_off: string; influenced_on: string; clean_blocked: string; tests: number };
}

declare global { interface Window { __CC_DEMO__?: DemoData } }

export default function DemoApp() {
  const data = window.__CC_DEMO__;
  const [caseId, setCaseId] = useState<string>(() => {
    const h = window.location.hash.replace("#", "");
    return data?.cases.find((c) => c.case_id.startsWith(h) && h)?.case_id ?? data?.cases[0]?.case_id ?? "";
  });
  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.replace("#", "");
      const match = data?.cases.find((c) => h && c.case_id.startsWith(h));
      if (match) setCaseId(match.case_id);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [data]);
  if (!data) return <p className="page">The demo data is missing from this file.</p>;
  const c = data.cases.find((x) => x.case_id === caseId) ?? data.cases[0];
  const pick = (id: string) => { window.location.hash = id.split("_")[0]; setCaseId(id); document.getElementById("room")?.scrollIntoView({ behavior: "smooth" }); };

  return (
    <div className="app demo">
      <header className="topbar">
        <span className="brand"><Logo /><span>Asclepius</span></span>
        <span className="muted small">Interactive demo · runs offline · synthetic patients only</span>
      </header>
      <main className="page">
        <section className="demo-hero">
          <div>
            <p className="eyebrow">AI specialist panel for patients who see many doctors</p>
            <h1>Your specialists, finally in one room.</h1>
            <p className="lead-in">Upload records from every doctor you see. A panel of AI specialist agents reviews them, discusses what connects,
              and prepares a case summary with questions to bring to your own doctors. It never diagnoses and never prescribes.</p>
            <p className="muted small">This file replays real runs recorded with {data.model} on {new Date(data.generated_at).toLocaleDateString()}. Nothing you do here
              is sent anywhere. The full app adds accounts, uploads, a health questionnaire and live chat.</p>
          </div>
          <div className="stat-tiles">
            <Stat value={`$${data.headline.cost_per_case.toFixed(3)}`} label="model cost per case" />
            <Stat value={`${Math.round(data.headline.caching_saving * 100)}%`} label="saved by prompt caching" />
            <Stat value={data.headline.attacks_succeeded_on} label="prompt-injection attacks succeeded" />
            <Stat value={data.headline.clean_blocked} label="clean documents wrongly blocked" />
          </div>
        </section>

        <h2>Choose a demo patient</h2>
        <div className="grid demo-picker">
          {data.cases.map((x) => (
            <button key={x.case_id} className={`card demo-case ${x.case_id === c.case_id ? "selected" : ""}`} onClick={() => pick(x.case_id)}>
              <div className="case-head"><h3>{x.case_title}</h3><span className={`pill ${x.age < 18 ? "pill-peds" : ""}`}>{x.age} y</span></div>
              <p className="case-patient">{x.profile.name}</p>
              <p className="muted small">{x.case_summary}</p>
              <span className="muted small">{x.documents.length} records · {x.chat.length} chat questions</span>
            </button>
          ))}
        </div>

        <div id="room"><CaseView key={c.case_id} c={c} roster={data.roster} /></div>
        <HowItWorks data={data} />
      </main>
      <footer className="demo-footer muted small">
        Asclepius · {data.author} · {data.course} · educational project, not a medical device · all patients and records are fictional
      </footer>
      <DisclaimerBar />
    </div>
  );
}

function CaseView({ c, roster }: { c: DemoCase; roster: RosterEntry[] }) {
  const [overlay, setOverlay] = useState<ChatOverlay | null>(null);
  const [doc, setDoc] = useState<DemoDoc | null>(null);
  const result = c.result;
  const regions = useMemo(() => regionsFromSummary(result?.summary, roster), [result, roster]);
  const em = result?.emergency;
  const p = c.profile;
  return (
    <div className="case-room">
      <div className="section-head">
        <div>
          <p className="eyebrow">Demo case · recorded {new Date(c.recorded_at).toLocaleString()}</p>
          <h1>{c.case_title}</h1>
          <p className="muted">{p.name} · {c.age} y · {LABELS[p.sex_at_birth] ?? p.sex_at_birth} · {c.documents.length} records</p>
        </div>
      </div>
      <blockquote className="concern">“{c.main_concern.split("\n")[0]}”</blockquote>
      {em?.active && <EmergencyBanner emergency={{ kind: em.crisis ? "crisis" : "medical", message: em.message }} reasons={em.reasons} actions={em.actions} />}

      <PanelTable events={c.events} roster={roster} patientName={p.name} live={false} overlay={overlay}
        medicationFallback={result?.pharmacist?.combined_list?.length} autoReplay />

      <div className="room-middle">
        <div className="room-body"><BodyMap regions={regions} /></div>
        <div className="room-summary"><SummaryView result={result} /></div>
      </div>

      <DemoChat items={c.chat} roster={roster} coordinatorId={result?.modes?.coordinator ?? "internal_medicine"} onOverlay={setOverlay} />

      <section className="card">
        <h2>The records the panel read</h2>
        <p className="muted small">Synthetic documents in mixed formats. Text PDFs are read locally; photos and scans are transcribed by vision.</p>
        <ul className="file-list">
          {c.documents.map((d) => (
            <li key={d.name}>
              <div><strong>{d.name}</strong> <span className="doc-kind">{d.kind}{d.read_by === "vision" ? " · read by vision" : ""}</span></div>
              <button className="btn btn-ghost small-btn" onClick={() => setDoc(d)}>View</button>
            </li>
          ))}
        </ul>
      </section>

      <SpecialistReports result={result} />
      <details className="card conference-log">
        <summary><strong>Full conference log</strong> <span className="muted small">· every routing step, tool call and comment</span></summary>
        <PanelActivity events={c.events} />
      </details>
      <RunDetailsView data={c.usage} roster={roster} />
      <RunMeta result={result} />
      {doc && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={() => setDoc(null)}>
          <div className="card modal doc-modal" onClick={(e) => e.stopPropagation()}>
            <div className="section-head"><h2>{doc.name}</h2><button className="btn btn-ghost" onClick={() => setDoc(null)}>Close</button></div>
            {doc.image ? <img src={doc.image} alt={doc.name} className="doc-image" /> : <pre className="doc-text">{doc.text}</pre>}
          </div>
        </div>
      )}
    </div>
  );
}

function HowItWorks({ data }: { data: DemoData }) {
  const h = data.headline;
  return (
    <section className="how">
      <h2>How Asclepius works</h2>
      <ol className="pipeline">
        <li><strong>Intake</strong> reads each record, keeping only text a person can see, routes it to the right specialties and extracts labs and medicines.</li>
        <li><strong>Round 1:</strong> up to five AI specialists plus a clinical pharmacist review only their own records, in parallel, checking PubMed, MedlinePlus and FDA labels.</li>
        <li><strong>Round 2:</strong> a targeted conference. Each specialist reads the few colleagues it shares a finding or question with. Then a hard stop.</li>
        <li><strong>Coordinator</strong> (internal medicine, or pediatrics for children) writes the summary, citing only findings the specialists reported.</li>
        <li><strong>Safety reviewer</strong> and code checks remove diagnoses, medicine changes, unsourced claims and cancer speculation, and raise emergencies first.</li>
      </ol>
      <div className="how-grid">
        <div className="card"><h3>Cost</h3>
          <p>${h.cost_per_case.toFixed(4)} per case on average (four test cases). Prompt caching saves {Math.round(h.caching_saving * 100)}%.
            About ${h.monthly_per_user.toFixed(3)} per user per month (2 cases, 15 chat questions); ${Math.round(h.monthly_10k)} a month for 10,000 users.</p></div>
        <div className="card"><h3>Safety</h3>
          <p>Seven prompt-injection attacks (white text, tiny text, a fake doctor's note, faint text in an image, covered text, invisible Unicode, an attack typed
            into the questionnaire): {h.attacks_succeeded_on} succeeded with defenses on. Hidden fake facts influenced {h.influenced_off} summaries with defenses
            off, {h.influenced_on} with them on. Clean look-alike documents wrongly blocked: {h.clean_blocked}.</p></div>
        <div className="card"><h3>Never a doctor</h3>
          <p>Every agent is labelled an AI specialist. The panel never diagnoses or prescribes; it organizes your records into questions for your real doctors.
            {" "}{h.tests} automated offline tests check these guarantees in code.</p></div>
      </div>
    </section>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return <div className="stat"><span className="stat-value">{value}</span><span className="stat-label">{label}</span></div>;
}

function Logo() {
  return (
    <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="8" fill="#0f3d4c" />
      <circle cx="11" cy="13" r="4" fill="#7fd1c7" /><circle cx="21" cy="13" r="4" fill="#7fd1c7" /><circle cx="16" cy="21" r="4" fill="#fff" /></svg>
  );
}
