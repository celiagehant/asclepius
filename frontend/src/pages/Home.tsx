import { useEffect, useState } from "react";
import { api, type CaseRow, type DemoCase, type Emergency, type Profile } from "../api/client";
import { EmergencyBanner, PublicDemoNotice, StatusBadge } from "../components/Common";
import { go } from "../lib/router";
import { LABELS } from "../lib/questionnaire";

export default function Home({ onDataDeleted, publicDemo }: { onDataDeleted: () => void; publicDemo?: boolean }) {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [demos, setDemos] = useState<DemoCase[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDelete, setShowDelete] = useState(false);
  const [emergency, setEmergency] = useState<Emergency | null>(() => {
    const saved = sessionStorage.getItem("cc_emergency");
    return saved ? (JSON.parse(saved) as Emergency) : null;
  });

  const load = () => {
    api.profiles().then(setProfiles).catch((e) => setError(e.message));
    api.cases().then(setCases).catch(() => undefined);
  };
  useEffect(() => {
    load();
    api.demoCases().then(setDemos).catch(() => undefined);
  }, []);

  const newCase = async (profileId: number) => {
    setBusy(`case-${profileId}`);
    try {
      const c = await api.createCase(profileId);
      go(`/cases/${c.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };
  const loadDemo = async (id: string) => {
    setBusy(id);
    try {
      const r = await api.loadDemo(id);
      go(`/cases/${r.case_id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };
  const nameOf = (pid: number) => profiles?.find((p) => p.id === pid)?.data.name ?? "—";

  if (profiles === null) return <p className="muted">Loading…</p>;
  return (
    <div className="home">
      {emergency && (
        <EmergencyBanner emergency={emergency} reasons={emergency.matches.map((m) => `You mentioned: ${m}.`)}
          onDismiss={() => { sessionStorage.removeItem("cc_emergency"); setEmergency(null); }} />
      )}
      {error && <p className="error-text">{error}</p>}
      {publicDemo && <PublicDemoNotice where="home" />}

      <div className="section-head">
        <div>
          <h1>Health profiles</h1>
          <p className="muted">The panel uses these answers in every case, so it remembers each person between visits.</p>
        </div>
        <button className="btn btn-ghost" onClick={() => go("/profiles/new?for=care")}>+ Add someone in my care</button>
      </div>
      <div className="grid">
        {profiles.map((p) => (
          <article className="card profile-card" key={p.id}>
            <div className="case-head">
              <h3>{p.data.name}</h3>
              <span className={`pill ${p.pediatric ? "pill-peds" : ""}`}>{p.pediatric ? "Pediatric" : "Adult"} · {p.age} y</span>
            </div>
            <p className="muted small">{p.data.for_whom === "self" ? "Myself" : `In my care${p.data.relationship ? ` · ${p.data.relationship}` : ""}`}
              {" · "}{LABELS[p.data.sex_at_birth] ?? p.data.sex_at_birth}{" · "}updated {new Date(p.updated_at).toLocaleDateString()}</p>
            <p className="small">{p.data.medications_status === "listed" ? `${p.data.medications.length} medication(s)` : "No medications listed"}
              {" · "}{p.data.conditions_status === "listed" ? `${p.data.conditions.length + (p.data.conditions_other ? 1 : 0)} condition(s)` : "No conditions listed"}</p>
            <div className="card-actions">
              <button className="btn" disabled={busy !== null} onClick={() => newCase(p.id)}>{busy === `case-${p.id}` ? "Opening…" : "Start a new case"}</button>
              <button className="btn btn-ghost" onClick={() => go(`/profiles/${p.id}`)}>Review profile</button>
            </div>
          </article>
        ))}
      </div>

      <h2>Cases</h2>
      {cases.length === 0 ? (
        <p className="muted">No cases yet. Start one from a profile above, or try a demo patient below.</p>
      ) : (
        <div className="case-list">
          {cases.map((c) => (
            <a className="case-row card" key={c.id} href={`#/cases/${c.id}`}>
              <div>
                <strong>{c.title}</strong>
                <div className="muted small">{nameOf(c.profile_id)} · {c.file_count ?? 0} document(s) · {new Date(c.created_at).toLocaleDateString()}</div>
              </div>
              <StatusBadge status={c.status} />
            </a>
          ))}
        </div>
      )}

      <h2>Try a demo patient</h2>
      <p className="muted">Fictional patients with synthetic records. Loading one adds its profile and a ready-to-review case to your account.</p>
      <div className="grid">
        {demos.map((d) => (
          <article className="card demo-card" key={d.id}>
            <div className="case-head">
              <h3>{d.title}</h3>
              <span className={`pill ${d.age_years < 18 ? "pill-peds" : ""}`}>{d.age_years} y · {d.sex}</span>
            </div>
            <p className="case-patient">{d.patient}</p>
            <p className="muted small">{d.summary}</p>
            <button className="btn btn-ghost" disabled={busy !== null} onClick={() => loadDemo(d.id)}>
              {busy === d.id ? "Loading…" : `Load demo (${d.documents.length} documents)`}
            </button>
          </article>
        ))}
      </div>

      <section className="danger-zone card">
        <div>
          <h3>Your data</h3>
          <p className="muted small">Profiles, questionnaire answers, cases, uploaded files, reports and chat are stored only for your
            account. Records are sent to the AI model (gpt-6-luna via Portkey) only while the panel reviews a case.</p>
        </div>
        <button className="btn btn-danger-outline" onClick={() => setShowDelete(true)}>Delete all my data</button>
      </section>
      {showDelete && <DeleteDialog onClose={() => setShowDelete(false)} onDeleted={(account) => { setShowDelete(false); if (account) onDataDeleted(); else { load(); go("/profiles/new?first=1"); } }} />}
    </div>
  );
}

function DeleteDialog({ onClose, onDeleted }: { onClose: () => void; onDeleted: (accountDeleted: boolean) => void }) {
  const [text, setText] = useState("");
  const [account, setAccount] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      await api.deleteAllData(account);
      onDeleted(account);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="del-title">
      <div className="card modal">
        <h2 id="del-title">Delete all my data?</h2>
        <p>This permanently removes every health profile, questionnaire answer, case, uploaded file, report and chat in your
          account. It cannot be undone.</p>
        <label className="check-inline"><input type="checkbox" checked={account} onChange={(e) => setAccount(e.target.checked)} /> Also delete my account (email and password)</label>
        <label className="field"><span>Type DELETE to confirm</span><input value={text} onChange={(e) => setText(e.target.value)} autoFocus /></label>
        {error && <p className="error-text">{error}</p>}
        <div className="wizard-nav">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <span className="spacer" />
          <button className="btn btn-danger" disabled={text.trim().toUpperCase() !== "DELETE" || busy} onClick={run}>{busy ? "Deleting…" : "Delete everything"}</button>
        </div>
      </div>
    </div>
  );
}
