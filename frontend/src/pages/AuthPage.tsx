import { useState } from "react";
import { api } from "../api/client";
import { PublicDemoNotice } from "../components/Common";

export default function AuthPage({ mode, onAuthed, publicDemo }: { mode: "login" | "signup"; onAuthed: () => void; publicDemo?: boolean }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [adult, setAdult] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const signup = mode === "signup";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (signup) await api.signup(email, password, adult);
      else await api.login(email, password);
      onAuthed();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <section className="auth-intro">
        <h1>Your specialists, finally in one room.</h1>
        <p>Upload records from every doctor you see. A panel of AI specialist agents reviews them together, discusses what
          connects, and prepares a case summary with questions to bring to your own doctors.</p>
        <ul className="ticks">
          <li>Not a diagnosis and never a prescription: an organized summary for your real doctors.</li>
          <li>The panel is made of AI specialist agents, not licensed physicians.</li>
          <li>Your data is private to your account, and you can delete all of it at any time.</li>
        </ul>
      </section>
      <form className="card auth-card" onSubmit={submit}>
        <h2>{signup ? "Create your account" : "Log in"}</h2>
        {publicDemo && <PublicDemoNotice where="auth" />}
        <label className="field"><span>Email</span>
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="field"><span>Password</span>
          <input type="password" autoComplete={signup ? "new-password" : "current-password"} required minLength={signup ? 8 : 1}
            value={password} onChange={(e) => setPassword(e.target.value)} />
          {signup && <small className="muted">At least 8 characters.</small>}</label>
        {signup && (
          <label className="check-inline">
            <input type="checkbox" checked={adult} onChange={(e) => setAdult(e.target.checked)} />
            I am 18 or older. (Parents and guardians add their children's profiles from their own account.)
          </label>
        )}
        {error && <p className="error-text">{error}</p>}
        <button className="btn btn-wide" disabled={busy || (signup && !adult)}>{busy ? "Please wait…" : signup ? "Create account" : "Log in"}</button>
        <p className="muted small center">
          {signup ? <>Already have an account? <a href="#/login">Log in</a></> : <>New here? <a href="#/signup">Create an account</a></>}
        </p>
      </form>
    </div>
  );
}
