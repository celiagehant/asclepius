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
      <section className="auth-intro auth-panel">
        <p className="hero-eyebrow light">ΛSCLEPIUS · AI case conference</p>
        <h1>{signup ? "Your specialists, finally in one room." : "Welcome back."}</h1>
        <p>A panel of AI specialist agents reviews the records from every doctor you see, connects what they find, and prepares
          questions for your own doctors.</p>
        <ul className="auth-trust">
          <li><span aria-hidden>🔒</span><div><strong>Private to your account.</strong> Only you can open your cases.</div></li>
          <li><span aria-hidden>🔑</span><div><strong>Your password is never stored.</strong> It is scrambled with a one-way method.</div></li>
          <li><span aria-hidden>🗑️</span><div><strong>Delete everything anytime,</strong> in one click.</div></li>
          <li><span aria-hidden>🩺</span><div><strong>Not a diagnosis.</strong> An organized summary for your real doctors, from AI agents, not physicians.</div></li>
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
