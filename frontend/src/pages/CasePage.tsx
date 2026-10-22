import { useCallback, useEffect, useRef, useState } from "react";
import { api, type CaseDetail, type Emergency, type Profile } from "../api/client";
import { EmergencyBanner, PublicDemoNotice, StatusBadge } from "../components/Common";
import PrintSummary from "../components/PrintSummary";
import CaseRoom from "../components/CaseRoom";
import { go } from "../lib/router";
import { LABELS } from "../lib/questionnaire";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.txt,.md";

function kindLabel(kind: string, readBy: string) {
  if (kind === "image") return "image · read by vision";
  if (kind === "pdf") return readBy.includes("vision") ? "scanned PDF · read by vision" : "PDF · text";
  return "text";
}

export default function CasePage({ caseId, publicDemo }: { caseId: number; publicDemo?: boolean }) {
  const [c, setC] = useState<CaseDetail | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [concern, setConcern] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [emergency, setEmergency] = useState<Emergency | null>(null);
  const [rejected, setRejected] = useState<{ filename: string; reason: string }[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"setup" | "live" | "result">("setup");
  const inputRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    const data = await api.case(caseId);
    setC(data);
    setConcern((cur) => cur || data.main_concern);
    setMode(data.running || data.status === "running" ? "live" : data.result ? "result" : "setup");
    return data;
  }, [caseId]);

  useEffect(() => {
    reload().then((data) => api.profile(data.profile_id).then(setProfile)).catch((e) => setError(e.message));
  }, [reload]);

  const upload = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    setError(null);
    try {
      const r = await api.upload(caseId, files);
      setRejected(r.rejected);
      setC((cur) => (cur ? { ...cur, files: r.files } : cur));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const checkConcern = async () => {
    if (!concern.trim()) return;
    try {
      const e = await api.emergencyCheck(concern);
      setEmergency(e.emergency ? e : null);
    } catch { /* checked again when convening */ }
  };

  const convene = async () => {
    setError(null);
    try {
      const r = await api.convene(caseId, concern);
      if (r.emergency.emergency) setEmergency(r.emergency);
      setMode("live");
      setC((cur) => (cur ? { ...cur, status: "running", running: true, run_id: r.run_id } : cur));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (error && !c) return <p className="error-text">{error}</p>;
  if (!c) return <p className="muted">Loading…</p>;
  const d = profile?.data;

  return (
    <div className="case-page">
      <PrintSummary c={c} patientLine={d ? `${d.name} · ${profile!.age} y · ${LABELS[d.sex_at_birth] ?? d.sex_at_birth}` : ""} />
      {emergency && <EmergencyBanner emergency={emergency} reasons={emergency.matches.map((m) => `You mentioned: ${m}.`)} onDismiss={() => setEmergency(null)} />}
      <div className="section-head">
        <div>
          <a href="#/" className="muted small">← All cases</a>
          <h1>{c.title}</h1>
          <p className="muted">{d ? `${d.name} · ${profile!.age} y · ${LABELS[d.sex_at_birth] ?? d.sex_at_birth}` : ""}</p>
        </div>
        <div className="head-actions">
          <StatusBadge status={c.status} />
          {mode === "result" && <button className="btn btn-ghost" onClick={() => setMode("setup")}>Add records & run again</button>}
          {mode === "result" && c.result?.summary?.explanations && (
            <button className="btn" onClick={() => window.print()} title="A clean summary for your doctor; choose “Save as PDF” in the print dialog to keep a file">
              🖨 Print or save as PDF for my doctor</button>)}
        </div>
      </div>

      {mode === "setup" && (
        <>
          <section className="card step-card">
            <h2><span className="step-num">1</span> Is {d?.for_whom === "self" ? "your" : `${d?.name ?? "the"}'s`} health profile still up to date?</h2>
            {d && (
              <ul className="profile-summary">
                <li><strong>Medications:</strong> {d.medications_status === "listed" ? d.medications.map((m) => [m.name, m.dose].filter(Boolean).join(" ")).join(", ") || "—" : LABELS[d.medications_status]}</li>
                <li><strong>Allergies:</strong> {d.allergies_status === "listed" ? d.allergies.join(", ") : d.allergies_status === "none" ? "No known allergies" : LABELS[d.allergies_status]}</li>
                <li><strong>Conditions:</strong> {d.conditions_status === "listed" ? [...d.conditions, d.conditions_other].filter(Boolean).join("; ") || "—" : LABELS[d.conditions_status]}</li>
                {d.pregnancy && <li><strong>Pregnancy / breastfeeding:</strong> {LABELS[d.pregnancy]}</li>}
                <li className="muted small">Last updated {profile && new Date(profile.updated_at).toLocaleDateString()}</li>
              </ul>
            )}
            <div className="card-actions">
              <label className={`check-inline confirm ${confirmed ? "selected" : ""}`}>
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> Yes, it's up to date
              </label>
              <button className="btn btn-ghost" onClick={() => go(`/profiles/${c.profile_id}`)}>Something changed: edit profile</button>
            </div>
          </section>

          <section className="card step-card">
            <h2><span className="step-num">2</span> What worries you today?</h2>
            <p className="why"><span aria-hidden>?</span> Why we ask: this tells the panel what to focus on for this case.</p>
            <textarea rows={4} maxLength={3000} value={concern} onChange={(e) => setConcern(e.target.value)} onBlur={checkConcern}
              placeholder="Symptoms, how long, what you most want to understand." />
          </section>

          <section className="card step-card">
            <h2><span className="step-num">3</span> Add medical records</h2>
            {publicDemo && <PublicDemoNotice where="upload" />}
            <div className={`dropzone ${dragging ? "dragging" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); upload(Array.from(e.dataTransfer.files)); }}
              onClick={() => inputRef.current?.click()} role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}>
              <input ref={inputRef} type="file" multiple accept={ACCEPT} hidden onChange={(e) => { upload(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
              <div className="drop-icon" aria-hidden>⇪</div>
              <strong>{uploading ? "Reading files…" : "Drag and drop files here, or click to choose"}</strong>
              <span className="muted small">Lab results, imaging and ECG reports, visit notes, medication lists · PDF, photos (JPG, PNG), text · up to 15 MB each, 12 per case</span>
            </div>
            {rejected.map((r) => <p key={r.filename} className="error-text small">Not added: {r.reason.startsWith(r.filename) ? r.reason : `${r.filename}: ${r.reason}`}</p>)}
            {c.files.length > 0 && (
              <ul className="file-list">
                {c.files.map((f) => (
                  <li key={f.id}>
                    <div>
                      <strong>{f.filename}</strong>
                      <span className="doc-kind">{kindLabel(f.kind, f.info.read_by)}</span>
                      {f.info.hidden_text.length > 0 && (
                        <div className="hidden-warn">Hidden text removed before review: {f.info.hidden_text.map((h) => `${h.label} (${h.chars} characters)`).join("; ")}</div>
                      )}
                    </div>
                    <button className="btn btn-ghost icon" aria-label={`Remove ${f.filename}`}
                      onClick={async () => { await api.deleteFile(caseId, f.id); reload(); }}>×</button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {error && <p className="error-text">{error}</p>}
          <div className="convene-bar">
            <p className="muted small">The panel reads only these records and the health profile. It takes about 1–3 minutes.</p>
            <button className="btn btn-big" disabled={!confirmed || c.files.length === 0 || uploading} onClick={convene}>Convene the panel</button>
          </div>
        </>
      )}

      {(mode === "live" || (mode === "result" && c.result)) && <CaseRoom key={`${c.run_id}-${mode}`} c={c} patientName={d?.name ?? "The patient"} onFinished={reload} />}
    </div>
  );
}
