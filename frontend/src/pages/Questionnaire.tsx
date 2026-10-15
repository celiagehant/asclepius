import { useEffect, useMemo, useState } from "react";
import { api, type Emergency, type Profile, type ProfileData } from "../api/client";
import { Choice, EmergencyBanner, ProgressBar } from "../components/Common";
import { go } from "../lib/router";
import { ageOf, CONDITIONS, emptyProfile, FAMILY, LABELS, pregnancyApplies, STEP_INFO, stepsFor, type StepId } from "../lib/questionnaire";

const PREFER = "prefer_not_to_say" as const;

function Why({ step }: { step: StepId }) {
  return <p className="why"><span aria-hidden>?</span> Why we ask: {STEP_INFO[step].why}</p>;
}

function answered(step: StepId, p: ProfileData): boolean {
  switch (step) {
    case "who": return p.name.trim().length > 0 && (p.for_whom === "self" || !!p.relationship);
    case "age": return ageOf(p) !== null;
    case "sex": return !!p.sex_at_birth;
    case "pregnancy": return !!p.pregnancy;
    case "medications": return p.medications_status !== "listed" || p.medications.some((m) => m.name.trim());
    case "allergies": return p.allergies_status !== "listed" || p.allergies.length > 0;
    case "conditions": return p.conditions_status !== "listed" || p.conditions.length > 0 || !!p.conditions_other.trim() || !!p.surgeries.trim();
    case "family": return p.family_status !== "listed" || p.family_history.length > 0 || !!p.family_other.trim();
    case "habits": return !!p.tobacco && !!p.alcohol;
    case "concern": return p.main_concern_withheld || p.main_concern.trim().length > 0;
    default: return true;
  }
}

function ageProblem(p: ProfileData): string | null {
  const age = ageOf(p);
  if (age === null) return null;
  if (age < 0 || age > 120) return "Please check the date or age.";
  if (p.for_whom === "self" && age < 18)
    return "People under 18 can't create their own profile. A parent or guardian can add one from their account: go back and choose \"Someone in my care\".";
  return null;
}

export default function Questionnaire({ profileId, forWhom, firstTime, onSaved }: {
  profileId?: number; forWhom?: "self" | "care"; firstTime?: boolean; onSaved?: () => Promise<void>;
}) {
  const [p, setP] = useState<ProfileData>(() => emptyProfile(forWhom ?? "self"));
  const [stepIndex, setStepIndex] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [emergency, setEmergency] = useState<Emergency | null>(null);
  const [allergyDraft, setAllergyDraft] = useState("");
  const editing = profileId !== undefined;

  useEffect(() => {
    if (editing) {
      api.profile(profileId!).then((prof) => {
        setP({ ...emptyProfile(), ...prof.data, gender_identity: prof.data.gender_identity ?? "" });
        setStepIndex(stepsFor(prof.data).indexOf("review"));
      }).catch((e) => setError(String(e.message ?? e)));
    }
  }, [editing, profileId]);

  const steps = useMemo(() => stepsFor(p), [p]);
  const step = steps[Math.min(stepIndex, steps.length - 1)];
  const set = (patch: Partial<ProfileData>) => setP((cur) => ({ ...cur, ...patch }));
  const canNext = answered(step, p) && !(step === "age" && ageProblem(p));

  const next = async () => {
    setError(null);
    if (step === "concern" && !p.main_concern_withheld) {
      try {
        const e = await api.emergencyCheck(p.main_concern);
        setEmergency(e.emergency ? e : null);
      } catch { /* the server checks again on save */ }
    }
    setStepIndex((i) => Math.min(i + 1, steps.length - 1));
  };
  const back = () => setStepIndex((i) => Math.max(i - 1, 0));
  const jump = (s: StepId) => setStepIndex(steps.indexOf(s));

  const save = async () => {
    setSaving(true);
    setError(null);
    const body: ProfileData = { ...p, pregnancy: pregnancyApplies(p) ? p.pregnancy : null, gender_identity: p.gender_identity || null,
      medications: p.medications.filter((m) => m.name.trim()), doctors: p.doctors.map((d) => d.trim()).filter(Boolean).slice(0, 20) };
    try {
      const saved: Profile = editing ? await api.updateProfile(profileId!, body) : await api.createProfile(body);
      if (saved.emergency?.emergency) setEmergency(saved.emergency);
      sessionStorage.setItem("cc_emergency", saved.emergency?.emergency ? JSON.stringify(saved.emergency) : "");
      await onSaved?.();
      go("/");
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setSaving(false);
    }
  };

  const who = p.for_whom === "self" ? "you" : p.name.trim() || "this person";
  const age = ageOf(p);

  return (
    <div className="wizard">
      {emergency && <EmergencyBanner emergency={emergency} reasons={emergency.matches.map((m) => `You mentioned: ${m}.`)} onDismiss={() => setEmergency(null)} />}
      <div className="wizard-head">
        <p className="eyebrow">{editing ? "Health profile" : firstTime ? "Before you upload anything · about 2 minutes" : "New health profile"}</p>
        <ProgressBar value={(stepIndex + 1) / steps.length} label={`Step ${stepIndex + 1} of ${steps.length}`} />
      </div>

      <section className="card wizard-card">
        <h1>{STEP_INFO[step].title}</h1>
        {step !== "review" && <Why step={step} />}

        {step === "who" && (
          <>
            <Choice name="for_whom" value={p.for_whom} options={["self", "care"] as const} labels={LABELS}
              onChange={(v) => set({ for_whom: v, relationship: v === "self" ? null : p.relationship })} />
            <label className="field">
              <span>{p.for_whom === "self" ? "Your first name or a nickname" : "Their first name or a nickname"}</span>
              <input value={p.name} maxLength={60} onChange={(e) => set({ name: e.target.value })} placeholder="e.g. Dana" />
              <small className="muted">Used only to check that uploaded records belong to this person.</small>
            </label>
            {p.for_whom === "care" && (
              <label className="field">
                <span>They are my…</span>
                <select value={p.relationship ?? ""} onChange={(e) => set({ relationship: e.target.value || null })}>
                  <option value="">Choose</option>
                  {["child", "parent", "partner", "relative", "person I care for"].map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
            )}
          </>
        )}

        {step === "age" && (
          <>
            <div className="row-2">
              <label className="field">
                <span>Date of birth</span>
                <input type="date" value={p.date_of_birth ?? ""} max={new Date().toISOString().slice(0, 10)}
                  onChange={(e) => set({ date_of_birth: e.target.value || null, age_years: null })} />
              </label>
              <label className="field">
                <span>…or age in years</span>
                <input type="number" min={0} max={120} value={p.date_of_birth ? "" : (p.age_years ?? "")} disabled={!!p.date_of_birth}
                  onChange={(e) => set({ age_years: e.target.value === "" ? null : Number(e.target.value) })} />
              </label>
            </div>
            <p className="muted small">Required. This is the only question without a "prefer not to say" option.</p>
            {ageProblem(p) && <p className="error-text">{ageProblem(p)}</p>}
            {age !== null && age < 18 && !ageProblem(p) && <p className="note-info">Pediatric mode: the panel will use children's reference ranges.</p>}
          </>
        )}

        {step === "sex" && (
          <>
            <Choice name="sex" value={p.sex_at_birth} options={["female", "male", "intersex", PREFER] as const} labels={LABELS} onChange={(v) => set({ sex_at_birth: v })} />
            <label className="field">
              <span>Gender identity <em className="muted">(optional)</em></span>
              <input value={p.gender_identity ?? ""} maxLength={60} onChange={(e) => set({ gender_identity: e.target.value })} placeholder="e.g. woman, man, non-binary" />
              <small className="muted">Separate from sex at birth. It is never used for lab ranges.</small>
            </label>
          </>
        )}

        {step === "pregnancy" && (
          <Choice name="pregnancy" value={p.pregnancy} options={["pregnant", "breastfeeding", "neither", "not_sure", PREFER] as const} labels={LABELS}
            onChange={(v) => set({ pregnancy: v })} />
        )}

        {step === "medications" && (
          <>
            <Choice name="meds" value={p.medications_status} options={["listed", "none", PREFER] as const}
              labels={{ ...LABELS, listed: `${who === "you" ? "I take" : "They take"} medicines or supplements`, none: "None" }}
              onChange={(v) => set({ medications_status: v, medications: v === "listed" && p.medications.length === 0 ? [{ name: "" }] : p.medications })} />
            {p.medications_status === "listed" && (
              <div className="med-list">
                {p.medications.map((m, i) => (
                  <div className="med-row" key={i}>
                    <input aria-label="Medicine" placeholder="Name (e.g. lisinopril, vitamin D)" value={m.name}
                      onChange={(e) => set({ medications: p.medications.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                    <input aria-label="Dose" placeholder="Dose (e.g. 10 mg)" value={m.dose ?? ""}
                      onChange={(e) => set({ medications: p.medications.map((x, j) => (j === i ? { ...x, dose: e.target.value } : x)) })} />
                    <input aria-label="How often" placeholder="How often" value={m.how_often ?? ""}
                      onChange={(e) => set({ medications: p.medications.map((x, j) => (j === i ? { ...x, how_often: e.target.value } : x)) })} />
                    <button className="btn btn-ghost icon" aria-label="Remove" onClick={() => set({ medications: p.medications.filter((_, j) => j !== i) })}>×</button>
                  </div>
                ))}
                <button className="btn btn-ghost" onClick={() => set({ medications: [...p.medications, { name: "" }] })}>+ Add another</button>
                <p className="muted small">Include over-the-counter medicines, vitamins and supplements. Doses are optional.</p>
              </div>
            )}
          </>
        )}

        {step === "allergies" && (
          <>
            <Choice name="allergies" value={p.allergies_status} options={["listed", "none", PREFER] as const}
              labels={{ ...LABELS, listed: "Yes, allergies", none: "No known allergies" }} onChange={(v) => set({ allergies_status: v })} />
            {p.allergies_status === "listed" && (
              <div className="tags">
                {p.allergies.map((a) => (
                  <span className="tag" key={a}>{a}<button aria-label={`Remove ${a}`} onClick={() => set({ allergies: p.allergies.filter((x) => x !== a) })}>×</button></span>
                ))}
                <input placeholder="Type an allergy and press Enter (e.g. penicillin - hives)" value={allergyDraft}
                  onChange={(e) => setAllergyDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === ",") && allergyDraft.trim()) {
                      e.preventDefault();
                      if (!p.allergies.includes(allergyDraft.trim())) set({ allergies: [...p.allergies, allergyDraft.trim()] });
                      setAllergyDraft("");
                    }
                  }}
                  onBlur={() => { if (allergyDraft.trim()) { set({ allergies: [...p.allergies, allergyDraft.trim()] }); setAllergyDraft(""); } }} />
              </div>
            )}
          </>
        )}

        {step === "conditions" && (
          <>
            <Choice name="conditions" value={p.conditions_status} options={["listed", "none", PREFER] as const}
              labels={{ ...LABELS, listed: "Yes", none: "None" }} onChange={(v) => set({ conditions_status: v })} />
            {p.conditions_status === "listed" && (
              <>
                <div className="checks">
                  {CONDITIONS.map((c) => (
                    <label key={c} className={`check ${p.conditions.includes(c) ? "selected" : ""}`}>
                      <input type="checkbox" checked={p.conditions.includes(c)}
                        onChange={(e) => set({ conditions: e.target.checked ? [...p.conditions, c] : p.conditions.filter((x) => x !== c) })} />
                      {c}
                    </label>
                  ))}
                </div>
                <label className="field"><span>Other conditions</span>
                  <textarea rows={2} value={p.conditions_other} maxLength={600} onChange={(e) => set({ conditions_other: e.target.value })} /></label>
                <label className="field"><span>Past surgeries (and roughly when)</span>
                  <textarea rows={2} value={p.surgeries} maxLength={600} onChange={(e) => set({ surgeries: e.target.value })} /></label>
              </>
            )}
          </>
        )}

        {step === "family" && (
          <>
            <Choice name="family" value={p.family_status} options={["listed", "none_known", PREFER] as const}
              labels={{ ...LABELS, listed: "Yes, in close family" }} onChange={(v) => set({ family_status: v })} />
            {p.family_status === "listed" && (
              <>
                <div className="checks">
                  {FAMILY.map((c) => (
                    <label key={c} className={`check ${p.family_history.includes(c) ? "selected" : ""}`}>
                      <input type="checkbox" checked={p.family_history.includes(c)}
                        onChange={(e) => set({ family_history: e.target.checked ? [...p.family_history, c] : p.family_history.filter((x) => x !== c) })} />
                      {c}
                    </label>
                  ))}
                </div>
                <label className="field"><span>Other (who, and what)</span>
                  <input value={p.family_other} maxLength={400} onChange={(e) => set({ family_other: e.target.value })} placeholder="e.g. mother: thyroid problems" /></label>
              </>
            )}
          </>
        )}

        {step === "habits" && (
          <>
            <h3 className="sub">Tobacco or vaping</h3>
            <Choice name="tobacco" value={p.tobacco} options={["never", "former", "current", PREFER] as const} labels={LABELS} onChange={(v) => set({ tobacco: v })} />
            <h3 className="sub">Alcohol</h3>
            <Choice name="alcohol" value={p.alcohol} options={["none", "occasionally", "weekly", "most_days", PREFER] as const} labels={LABELS} onChange={(v) => set({ alcohol: v })} />
            <label className="field">
              <span>Daily habits (optional): activity, sleep, eating pattern, coffee or energy drinks</span>
              <textarea rows={2} maxLength={500} value={p.habits ?? ""} onChange={(e) => set({ habits: e.target.value })}
                placeholder="e.g. sleep about 5 hours; 4 coffees a day; walk 20 minutes most days" /></label>
          </>
        )}

        {step === "concern" && (
          <>
            <label className="field">
              <span>In your own words: symptoms, how long, what you most want to understand</span>
              <textarea rows={6} maxLength={3000} disabled={p.main_concern_withheld} value={p.main_concern}
                onChange={(e) => set({ main_concern: e.target.value })}
                placeholder="e.g. I've been exhausted for months, my heart races on stairs, and each doctor looks at one thing." />
            </label>
            <label className="check-inline">
              <input type="checkbox" checked={p.main_concern_withheld} onChange={(e) => set({ main_concern_withheld: e.target.checked })} /> Prefer not to say
            </label>
            <p className="muted small">If something feels like an emergency right now, call 911 instead of using this app.</p>
          </>
        )}

        {step === "review" && <Review p={p} steps={steps} jump={jump} onDoctors={(doctors) => set({ doctors })} />}

        {error && <p className="error-text">{error}</p>}
        <div className="wizard-nav">
          {stepIndex > 0 && step !== "review" && <button className="btn btn-ghost" onClick={back}>Back</button>}
          {step === "review" && editing && <button className="btn btn-ghost" onClick={() => go("/")}>Cancel</button>}
          <span className="spacer" />
          {step !== "review" ? (
            <button className="btn" disabled={!canNext} onClick={next}>Continue</button>
          ) : (
            <button className="btn" disabled={saving || steps.slice(0, -1).some((s) => !answered(s, p))} onClick={save}>
              {saving ? "Saving…" : editing ? "Save changes" : "Save profile"}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

function Review({ p, steps, jump, onDoctors }: { p: ProfileData; steps: StepId[]; jump: (s: StepId) => void; onDoctors: (d: string[]) => void }) {
  const show = (v: string | null | undefined) => (v ? LABELS[v] ?? v : "—");
  const rows: [StepId, string, string][] = [
    ["who", "For", `${show(p.for_whom)} · ${p.name || "—"}${p.relationship ? ` (${p.relationship})` : ""}`],
    ["age", "Age", p.date_of_birth ? `${ageOf(p)} (born ${p.date_of_birth})` : `${p.age_years ?? "—"}`],
    ["sex", "Sex at birth", show(p.sex_at_birth) + (p.gender_identity ? ` · gender identity: ${p.gender_identity}` : "")],
    ["pregnancy", "Pregnancy / breastfeeding", show(p.pregnancy)],
    ["medications", "Medications", p.medications_status === "listed" ? p.medications.filter((m) => m.name).map((m) => [m.name, m.dose, m.how_often].filter(Boolean).join(" ")).join("; ") : show(p.medications_status)],
    ["allergies", "Allergies", p.allergies_status === "listed" ? p.allergies.join(", ") : show(p.allergies_status === "none" ? "No known allergies" : p.allergies_status)],
    ["conditions", "Conditions & surgeries", p.conditions_status === "listed" ? [...p.conditions, p.conditions_other, p.surgeries && `Surgeries: ${p.surgeries}`].filter(Boolean).join("; ") : show(p.conditions_status)],
    ["family", "Family history", p.family_status === "listed" ? [...p.family_history, p.family_other].filter(Boolean).join("; ") : show(p.family_status)],
    ["habits", "Tobacco · alcohol · habits", `${show(p.tobacco)} · ${show(p.alcohol)}${p.habits ? ` · ${p.habits}` : ""}`],
    ["concern", "What worries you", p.main_concern_withheld ? "Prefer not to say" : p.main_concern],
  ];
  return (
    <dl className="review">
      {rows.filter(([s]) => steps.includes(s)).map(([s, label, value]) => (
        <div key={s} className="review-row">
          <dt>{label}</dt>
          <dd>{value || "—"}</dd>
          <button className="btn btn-ghost small-btn" onClick={() => jump(s)}>Edit</button>
        </div>
      ))}
      <div className="review-row">
        <dt>Doctors you see <em className="muted">(optional)</em></dt>
        <dd>
          <textarea rows={3} aria-label="Doctors you see" value={p.doctors.join("\n")}
            onChange={(e) => onDoctors(e.target.value.split("\n"))}
            placeholder={"One per line, e.g.\nCardiology - Dr. Rhodes\nPrimary care - Dr. Chen"} />
          <small className="muted">The panel groups its questions by the doctors you actually see.</small>
        </dd>
      </div>
    </dl>
  );
}
