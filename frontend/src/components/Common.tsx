import type { ReactNode } from "react";
import type { Emergency } from "../api/client";

export const DISCLAIMER = "Educational case summary to discuss with your doctors. Not a diagnosis. In an emergency call 911.";

export function DisclaimerBar() {
  return (
    <div className="disclaimer-bar" role="note">
      <span aria-hidden>ⓘ</span> {DISCLAIMER}
    </div>
  );
}

export function EmergencyBanner({ emergency, reasons, actions, onDismiss }: {
  emergency: Pick<Emergency, "kind" | "message"> & { matches?: string[] };
  reasons?: string[];
  actions?: string[];
  onDismiss?: () => void;
}) {
  const crisis = emergency.kind === "crisis";
  return (
    <section className={`emergency ${crisis ? "crisis" : ""}`} role="alert" aria-live="assertive">
      <div className="emergency-head">
        <span className="emergency-icon" aria-hidden>!</span>
        <div>
          <h2>{crisis ? "You don't have to go through this alone" : "This may need urgent care now"}</h2>
          {(reasons ?? []).map((r) => <p key={r} className="emergency-reason">{r}</p>)}
          {(actions ?? []).map((a) => <p key={a}><strong>What to do:</strong> {a}</p>)}
          {emergency.message && <p className="emergency-msg">{emergency.message}</p>}
          <div className="emergency-actions">
            {crisis ? (
              <>
                <a className="btn btn-danger" href="tel:988">Call or text 988</a>
                <a className="btn btn-ghost-light" href="https://988lifeline.org/chat/" target="_blank" rel="noreferrer">Chat at 988lifeline.org</a>
              </>
            ) : (
              <a className="btn btn-danger" href="tel:911">Call 911</a>
            )}
            {onDismiss && <button className="btn btn-ghost-light" onClick={onDismiss}>I understand, continue</button>}
          </div>
        </div>
      </div>
    </section>
  );
}

export function PublicDemoNotice({ where }: { where: "auth" | "upload" | "home" }) {
  const text = {
    auth: "This is a public demo. Please don't use real medical records: after signing up, load one of the fictional demo patients. Accounts and data may be wiped when the server restarts.",
    upload: "Public demo: please don't upload real medical records. Use the demo patients' files, or documents you made up.",
    home: "Public demo: the quickest way to try it is a demo patient below. Each has synthetic records and is ready to review.",
  }[where];
  return <div className="public-notice" role="note"><strong>Demo</strong> {text}</div>;
}

export function TopBar({ email, onLogout, children }: { email?: string; onLogout?: () => void; children?: ReactNode }) {
  return (
    <header className="topbar">
      <a className="brand" href="#/">
        <img src="/favicon.svg" alt="" width={30} height={30} />
        <span>Case Conference</span>
      </a>
      <nav className="topnav">
        {children}
        {email && <span className="muted small hide-sm">{email}</span>}
        {onLogout && <button className="btn btn-ghost" onClick={onLogout}>Log out</button>}
      </nav>
    </header>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="progress" aria-label={label}>
      <div className="progress-track"><div className="progress-fill" style={{ width: `${Math.round(value * 100)}%` }} /></div>
      <span className="muted small">{label}</span>
    </div>
  );
}

export function Choice<T extends string>({ name, value, options, onChange, labels }: {
  name: string; value: T | null | undefined; options: readonly T[]; onChange: (v: T) => void; labels: Record<string, string>;
}) {
  return (
    <div className="choices" role="radiogroup" aria-label={name}>
      {options.map((o) => (
        <label key={o} className={`choice ${value === o ? "selected" : ""} ${o === "prefer_not_to_say" ? "choice-quiet" : ""}`}>
          <input type="radio" name={name} checked={value === o} onChange={() => onChange(o)} />
          {labels[o] ?? o}
        </label>
      ))}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = { draft: "Draft", running: "Panel in session", complete: "Summary ready", partial: "Partial summary",
    failed: "Failed", interrupted: "Interrupted" };
  return <span className={`badge badge-${status}`}>{label[status] ?? status}</span>;
}
