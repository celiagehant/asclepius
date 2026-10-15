// Same-origin API: the session cookie is sent automatically. Errors carry the server's message.

export interface Medication { name: string; dose?: string | null; how_often?: string | null }
export interface ProfileData {
  for_whom: "self" | "care";
  name: string;
  relationship?: string | null;
  date_of_birth?: string | null;
  age_years?: number | null;
  sex_at_birth: "female" | "male" | "intersex" | "prefer_not_to_say";
  gender_identity?: string | null;
  pregnancy?: "pregnant" | "breastfeeding" | "neither" | "not_sure" | "prefer_not_to_say" | null;
  medications_status: "listed" | "none" | "prefer_not_to_say";
  medications: Medication[];
  allergies_status: "listed" | "none" | "prefer_not_to_say";
  allergies: string[];
  conditions_status: "listed" | "none" | "prefer_not_to_say";
  conditions: string[];
  conditions_other: string;
  surgeries: string;
  family_status: "listed" | "none_known" | "prefer_not_to_say";
  family_history: string[];
  family_other: string;
  tobacco: "never" | "former" | "current" | "prefer_not_to_say";
  alcohol: "none" | "occasionally" | "weekly" | "most_days" | "prefer_not_to_say";
  habits?: string;
  main_concern: string;
  main_concern_withheld: boolean;
  doctors: string[];
}
export interface Emergency { emergency: boolean; kind: "crisis" | "medical" | null; matches: string[]; message: string | null }
export interface Profile { id: number; data: ProfileData; age: number; pediatric: boolean; updated_at: string; confirmed_at: string | null; emergency?: Emergency }
export interface FileInfo { read_by: string; pages: number; notes: string[]; hidden_text: { label: string; chars: number; page: number | null }[] }
export interface CaseFile { id: number; filename: string; size: number; kind: string; info: FileInfo; created_at: string }
export interface CaseRow { id: number; profile_id: number; title: string; main_concern: string; status: string; run_id: string | null; cost_usd: number | null; created_at: string; updated_at: string; file_count?: number }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Result = any;
export interface CaseDetail extends CaseRow { files: CaseFile[]; running: boolean; result: Result | null; profile_snapshot: ProfileData | null; emergency?: Emergency }
export interface DemoCase { id: string; title: string; patient: string; age_years: number; sex: string; summary: string; documents: string[] }
export interface Health { model: string; key_loaded: boolean; status: string; message: string; version: string; public_demo?: boolean }

export interface ChatAnswer { specialty: string; name: string; text: string; finding_refs: string[]; sources: { title: string; url: string }[];
  ask_your_doctor: string | null; confidence: string; source_note: string | null }
export interface ChatMessage { id: number; role: "user" | "panel" | "safety"; content: string; created_at?: string;
  meta: { answers?: ChatAnswer[]; wrap_up?: string; routed?: string[]; emergency?: Emergency | null;
          safety?: { edits: unknown[]; blocked: unknown[] }; usage?: { cost_usd: number } } }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ChatEvent = Record<string, any> & { type: string };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const OFFLINE = "Can't reach the Case Conference server. Check your connection, wait a moment and try again. "
  + "If you are running it yourself, make sure `python run.py` is still running.";

/** fetch, but a dropped connection becomes a readable message instead of the browser's "Load failed" / "NetworkError". */
async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init);
  } catch {
    throw new ApiError(0, OFFLINE);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await send(path, init);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* an HTML error page from a proxy, e.g. while the host wakes up */ }
  if (!res.ok) {
    const fallback = res.status >= 502 ? "The server is starting up or busy. Please try again in a minute." : `Request failed (${res.status})`;
    throw new ApiError(res.status, (data && (data.detail || data.message)) || fallback);
  }
  return data as T;
}

export const api = {
  health: () => call<Health>("GET", "/api/health"),
  me: () => call<{ id: number; email: string }>("GET", "/api/auth/me"),
  signup: (email: string, password: string, adult_confirmed: boolean) => call("POST", "/api/auth/signup", { email, password, adult_confirmed }),
  login: (email: string, password: string) => call("POST", "/api/auth/login", { email, password }),
  logout: () => call("POST", "/api/auth/logout"),
  profiles: () => call<Profile[]>("GET", "/api/profiles"),
  profile: (id: number) => call<Profile>("GET", `/api/profiles/${id}`),
  createProfile: (data: ProfileData) => call<Profile>("POST", "/api/profiles", data),
  updateProfile: (id: number, data: ProfileData) => call<Profile>("PUT", `/api/profiles/${id}`, data),
  deleteProfile: (id: number) => call("DELETE", `/api/profiles/${id}`),
  emergencyCheck: (text: string) => call<Emergency>("POST", "/api/emergency-check", { text }),
  cases: () => call<CaseRow[]>("GET", "/api/cases"),
  case: (id: number) => call<CaseDetail>("GET", `/api/cases/${id}`),
  createCase: (profile_id: number) => call<CaseDetail>("POST", "/api/cases", { profile_id }),
  updateCase: (id: number, fields: { title?: string; main_concern?: string }) => call<CaseDetail>("PUT", `/api/cases/${id}`, fields),
  deleteCase: (id: number) => call("DELETE", `/api/cases/${id}`),
  upload: (id: number, files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    return call<{ accepted: CaseFile[]; rejected: { filename: string; reason: string }[]; files: CaseFile[] }>("POST", `/api/cases/${id}/files`, form);
  },
  deleteFile: (caseId: number, fileId: number) => call("DELETE", `/api/cases/${caseId}/files/${fileId}`),
  convene: (id: number, main_concern: string) => call<{ run_id: string; emergency: Emergency }>("POST", `/api/cases/${id}/convene`, { profile_confirmed: true, main_concern }),
  demoCases: () => call<DemoCase[]>("GET", "/api/demo-cases"),
  chatHistory: (caseId: number) => call<{ messages: ChatMessage[]; available: boolean; members: string[]; busy: boolean }>("GET", `/api/cases/${caseId}/chat`),
  /** Ask the panel; events stream in as the coordinator routes, specialists answer and the safety reviewer checks. */
  askChat: async (caseId: number, message: string, onEvent: (e: ChatEvent) => void): Promise<void> => {
    const res = await send(`/api/cases/${caseId}/chat`, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) });
    if (!res.ok || !res.body) {
      const data = await res.json().catch(() => null);
      throw new ApiError(res.status, (data && data.detail) || `Request failed (${res.status})`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const data = block.split("\n").find((l) => l.startsWith("data: "));
        if (data && data !== "data: {}") onEvent(JSON.parse(data.slice(6)) as ChatEvent);
      }
    }
  },
  roster: () => call<import("../lib/panel").RosterEntry[]>("GET", "/api/roster"),
  loadDemo: (demoId: string) => call<{ profile_id: number; case_id: number }>("POST", `/api/demo/${demoId}`),
  deleteAllData: (delete_account: boolean) => call<{ removed: Record<string, number> }>("POST", "/api/me/delete-data", { confirm: "DELETE", delete_account }),
};
