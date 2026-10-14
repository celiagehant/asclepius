import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Health } from "./api/client";
import { DisclaimerBar, TopBar } from "./components/Common";
import AuthPage from "./pages/AuthPage";
import CasePage from "./pages/CasePage";
import Home from "./pages/Home";
import Questionnaire from "./pages/Questionnaire";
import { go, useRoute } from "./lib/router";

type User = { id: number; email: string };

export default function App() {
  const route = useRoute();
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [profileCount, setProfileCount] = useState<number | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
      setProfileCount((await api.profiles()).length);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    api.health().then(setHealth).catch(() => undefined);
  }, [refresh]);
  useEffect(() => {
    if (user) api.profiles().then((p) => setProfileCount(p.length)).catch(() => undefined);
  }, [route, user]);

  const [path, query] = route.split("?");
  const params = new URLSearchParams(query ?? "");

  // A new account answers the health questionnaire before anything else.
  useEffect(() => {
    if (user && profileCount === 0 && path !== "/profiles/new") go("/profiles/new?first=1");
  }, [user, profileCount, path]);

  const profilesChanged = async () => setProfileCount((await api.profiles()).length);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setUser(null);
    setProfileCount(null);
    go("/login");
  };

  let page;
  if (user === undefined) page = <p className="muted">Loading…</p>;
  else if (user === null) page = <AuthPage mode={path === "/signup" ? "signup" : "login"} onAuthed={() => { refresh(); go("/"); }} publicDemo={health?.public_demo} />;
  else if (path === "/profiles/new") page = <Questionnaire key={route} forWhom={params.get("for") === "care" ? "care" : "self"} firstTime={params.get("first") === "1" || profileCount === 0} onSaved={profilesChanged} />;
  else if (/^\/profiles\/\d+$/.test(path)) page = <Questionnaire key={route} profileId={Number(path.split("/")[2])} onSaved={profilesChanged} />;
  else if (/^\/cases\/\d+$/.test(path)) page = <CasePage key={route} caseId={Number(path.split("/")[2])} publicDemo={health?.public_demo} />;
  else page = <Home onDataDeleted={() => { setUser(null); go("/signup"); }} publicDemo={health?.public_demo} />;

  return (
    <div className="app">
      <TopBar email={user?.email} onLogout={user ? logout : undefined}>
        {user && <a className="btn btn-ghost hide-sm" href="#/">My cases</a>}
      </TopBar>
      {health && !health.key_loaded && (
        <div className="error-banner">The server has no model key: {health.message}</div>
      )}
      <main className="page">{page}</main>
      <DisclaimerBar />
    </div>
  );
}
