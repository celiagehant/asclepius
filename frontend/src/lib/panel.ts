// Panel styling and state. One color per specialty; state is derived from the run's event stream,
// so the live view and a replay of a finished case use the same code.

export interface RosterEntry { id: string; name: string; tier: "coordinator" | "always" | "frequent" | "on_demand"; scope: string }

export const SPECIALTY_COLORS: Record<string, string> = {
  internal_medicine: "#0f3d4c", pediatrics: "#6b3fa0", clinical_pharmacist: "#2e7d32", cardiology: "#d0384a",
  endocrinology: "#d97a00", gastroenterology: "#8a6232", neurology: "#4f56c9", hematology: "#a8174b", nephrology: "#1c6fb0",
  rheumatology: "#b8337a", pulmonology: "#00838f", orthopedics: "#5d6b78", ophthalmology: "#3949ab",
  obstetrics_gynecology: "#c2477e", urology: "#b88a00", dermatology: "#9a6b4f", otolaryngology: "#00897b",
  infectious_disease: "#5f8a2f", psychiatry: "#7e57c2", lifestyle: "#139a74", skeptic: "#5b6770",
};
export const SPECIALTY_ICONS: Record<string, string> = {
  internal_medicine: "⚕", pediatrics: "☺", clinical_pharmacist: "💊", cardiology: "♥", endocrinology: "⚖", gastroenterology: "◒",
  neurology: "✺", hematology: "●", nephrology: "◗", rheumatology: "⟡", pulmonology: "≋", orthopedics: "⟂", ophthalmology: "◉",
  obstetrics_gynecology: "♀", urology: "◖", dermatology: "◍", otolaryngology: "◔", infectious_disease: "✣", psychiatry: "☁",
  lifestyle: "❀", skeptic: "?",
};
export function colorOf(id: string): string {
  if (SPECIALTY_COLORS[id]) return SPECIALTY_COLORS[id];
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 360;  // new roster entries still get a stable color
  return `hsl(${h} 55% 42%)`;
}
export function shortName(name: string): string {
  return name.replace(" and traumatology", "").replace("Obstetrics and gynecology", "OB/GYN").replace("Otolaryngology (ENT)", "ENT");
}

// Body systems on the shared case board (same fixed list as backend/board.py).
export const SYSTEM_LABELS: Record<string, string> = {
  cardiovascular: "Heart & circulation", respiratory: "Lungs & breathing", digestive: "Digestive", liver: "Liver",
  kidney_urinary: "Kidneys & urinary", endocrine_metabolic: "Hormones & metabolism", blood: "Blood", immune_joints: "Immune & joints",
  nervous_system: "Nervous system", mental_health: "Mental health", skin: "Skin", musculoskeletal: "Bones & muscles",
  reproductive: "Reproductive", eyes: "Eyes", ear_nose_throat: "Ear, nose & throat", medication: "Medicines", lifestyle: "Lifestyle",
  general: "General",
};
export const SYSTEM_COLORS: Record<string, string> = {
  cardiovascular: "#d0384a", respiratory: "#00838f", digestive: "#8a6232", liver: "#a0522d", kidney_urinary: "#1c6fb0",
  endocrine_metabolic: "#d97a00", blood: "#a8174b", immune_joints: "#b8337a", nervous_system: "#4f56c9", mental_health: "#7e57c2",
  skin: "#9a6b4f", musculoskeletal: "#5d6b78", reproductive: "#c2477e", eyes: "#3949ab", ear_nose_throat: "#00897b",
  medication: "#2e7d32", lifestyle: "#139a74", general: "#607d8b",
};

export interface BoardPost { id: string; by: string; by_name: string; system: string; symptoms: string[]; line: string; significance: string; region: string | null; seq?: number }
export interface Thread { from: string; to: string[]; kind: "connection" | "challenge" | "support"; seq: number; text: string; candidate?: string }

export const SEVERITY_COLORS = { urgent: "#ff4d5e", discuss: "#ffb627", watch: "#4fa8ff" } as const;
export type Severity = keyof typeof SEVERITY_COLORS;
export const REGION_LABELS: Record<string, string> = {
  brain: "Brain", eyes: "Eyes", ent: "Ear, nose & throat", thyroid: "Thyroid", heart: "Heart", lungs: "Lungs", stomach: "Stomach",
  liver: "Liver", intestines: "Intestines", kidneys: "Kidneys", bladder_prostate: "Bladder & prostate", reproductive: "Reproductive organs",
  blood: "Blood", bones_joints: "Bones & joints", skin: "Skin", mind: "Mind",
};

export interface RegionView { region: string; severity: Severity; reason: string; specialists: string[] }

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function regionsFromSummary(summary: any, roster: RosterEntry[]): RegionView[] {
  if (!summary?.body_regions) return [];
  const names = Object.fromEntries(roster.map((r) => [r.id, r.name]));
  return summary.body_regions.map((b: { region: string; severity: Severity; reason: string; finding_refs: string[] }) => ({
    region: b.region, severity: b.severity, reason: b.reason,
    specialists: Array.from(new Set(b.finding_refs.map((r) => r.split(".")[0]))).map((id) => names[id] ?? (id === "pharmacist" ? "Clinical pharmacist" : id)),
  }));
}

// ---- panel state from events ------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Ev = Record<string, any> & { seq: number; type: string; t: number };

export interface MemberState {
  status: "idle" | "lit" | "working" | "done" | "failed";
  activity: string;
  docs: string[];
  bubble?: { text: string; kind: string; seq: number };
  round2: "none" | "working" | "done";   // kept for old saved runs
  roundLine?: string;                    // "Round 2: 2 connections", "Round 3: defends C1"…
}

export interface PanelState {
  coordinatorId: string;
  active: Set<string>;
  consults: Set<string>;
  selected: boolean;
  medications: number | null;
  members: Record<string, MemberState>;
  coordinator: { activity: string; done: boolean; safety: string | null };
  lastSeq: number;
  stage: "intake" | "round1" | "round2" | "round3" | "synthesis" | "safety" | "done";
  spend: { total: number; limit: number | null; byMember: Record<string, number> };
  board: BoardPost[];
  threads: Thread[];
}

/** Same mapping as backend/panel.py member_of, for event logs saved before it existed. */
export function memberOf(agent: string, label: string): string {
  if (agent.startsWith("intake")) return "intake";
  if (agent === "chat_router" || agent === "chat_wrapup" || label.startsWith("coordinator")) return "coordinator";
  if (agent === "safety_reviewer" || agent === "chat_safety") return "safety_reviewer";
  const head = label.split(" (retry")[0];
  const [prefix, rest] = head.split(/\.(.+)/);
  return rest && ["r1", "r2", "r3", "r4", "consult", "chat"].includes(prefix) ? rest : agent;
}

const blank = (): MemberState => ({ status: "idle", activity: "", docs: [], round2: "none" });

export function derivePanel(events: Ev[], fallbackCoordinator = "internal_medicine"): PanelState {
  const s: PanelState = {
    coordinatorId: fallbackCoordinator, active: new Set(), consults: new Set(), selected: false, medications: null, members: {},
    coordinator: { activity: "Waiting for records", done: false, safety: null }, lastSeq: 0, stage: "intake",
    spend: { total: 0, limit: null, byMember: {} }, board: [], threads: [],
  };
  const ROUND_NAMES: Record<number, string> = { 2: "Round 2", 3: "Round 3", 4: "Round 4" };
  const m = (id: string) => (s.members[id] ??= blank());
  for (const e of events) {
    s.lastSeq = e.seq;
    switch (e.type) {
      case "spend": {
        if (e.from_cache) break;
        const who = e.member ?? memberOf(e.agent ?? "", e.label ?? "");
        s.spend.byMember[who] = (s.spend.byMember[who] ?? 0) + (e.call_usd ?? 0);
        s.spend.total = e.total_usd ?? s.spend.total;
        if (e.limit_usd) s.spend.limit = e.limit_usd;
        break;
      }
      case "run_started":
        if (e.budget?.limit_usd) s.spend.limit = e.budget.limit_usd;
        s.coordinator.activity = `Opening the case: ${e.documents?.length ?? 0} records`;
        break;
      case "document_routed":
        for (const sp of e.specialties ?? []) {
          const x = m(sp);
          if (x.status === "idle") x.status = "lit";
          if (!x.docs.includes(e.document)) x.docs.push(e.document);
          x.activity = `Reviewing ${e.document}`;
        }
        s.coordinator.activity = "Routing each record to the right specialists";
        break;
      case "panel_selected":
        s.selected = true;
        s.coordinatorId = e.coordinator_id ?? s.coordinatorId;
        s.medications = e.medications ?? null;
        s.active = new Set((e.active ?? []).map((a: { specialty: string }) => a.specialty));
        if (e.pharmacist) s.active.add("clinical_pharmacist");
        for (const [id, x] of Object.entries(s.members)) if (!s.active.has(id) && id !== s.coordinatorId) { x.status = "idle"; x.activity = ""; }
        s.coordinator.activity = `Convened ${s.active.size} panel members`;
        break;
      case "specialist_started": {
        const x = m(e.specialty);
        if (e.consult) { s.consults.add(e.specialty); s.active.add(e.specialty); }
        if (e.specialty === "lifestyle") s.active.add("lifestyle");
        if (e.round === 1) {
          x.status = "working";
          const docs: string[] = e.documents ?? [];
          x.activity = e.specialty === "clinical_pharmacist" ? "Building one combined medication list"
            : e.specialty === "lifestyle" ? "Noting lifestyle facts from your answers"
            : docs.length ? `Reviewing ${docs.length === 1 ? docs[0] : `${docs.length} records`}` : "Reviewing the symptoms you described";
          s.stage = "round1";
        } else if (e.peers) {  // runs saved before the four-round conference
          x.round2 = "working";
          x.activity = `Discussing with ${(e.peers ?? []).length} colleague(s)`;
          s.stage = "round2";
        } else {
          x.status = "working";
          x.roundLine = `${ROUND_NAMES[e.round] ?? "Round"}: working…`;
          x.activity = e.round === 2 ? "Reading the case board for connections" : e.round === 3 ? "Answering the skeptic"
            : "Writing self-care steps";
          if (e.round === 2) s.stage = "round2";
          if (e.round === 3) s.stage = "round3";
        }
        break;
      }
      case "tool_call": {
        const src = ({ search_pubmed: "PubMed", search_medlineplus: "MedlinePlus", fda_label_search: "FDA label" } as Record<string, string>)[e.tool] ?? e.tool;
        m(e.specialty).activity = `Checking ${src}: "${e.args?.query ?? e.args?.drug ?? ""}"`;
        break;
      }
      case "specialist_done": {
        const x = m(e.specialty);
        x.status = "done";
        if (e.round === 1) {
          x.activity = e.specialty === "clinical_pharmacist" ? `${e.findings} item(s) to discuss`
            : e.specialty === "lifestyle" ? `${e.findings} lifestyle fact(s) posted` : `${e.findings} findings · confidence ${e.confidence}`;
        } else if (e.round === 2 && e.disagreements) {  // old saved runs
          x.round2 = "done";
          x.activity = `${e.connections} connection(s), ${e.disagreements} disagreement(s)`;
        } else if (e.round === 2) {
          x.roundLine = `Round 2: ${e.connections} connection(s) proposed`;
          x.activity = x.roundLine;
        } else if (e.round === 3) {
          x.roundLine = `Round 3: ${e.stances} stance(s) in the debate`;
          x.activity = x.roundLine;
        } else if (e.round === 4) {
          x.roundLine = `Round 4: ${e.findings} self-care step(s)`;
          x.activity = x.roundLine;
        }
        break;
      }
      case "board_post":
        if (!s.board.some((p) => p.id === e.id)) {
          s.board.push({ id: e.id, by: e.by, by_name: e.by_name, system: e.system, symptoms: e.symptoms ?? [], line: e.line,
            significance: e.significance, region: e.region ?? null, seq: e.seq });
        }
        break;
      case "connection":
        s.threads.push({ from: e.from_, to: e.members ?? [], kind: "connection", seq: e.seq, text: e.title });
        m(e.from_).bubble = { text: e.title, kind: "connection", seq: e.seq };
        break;
      case "challenge":
        s.active.add("skeptic");
        s.threads.push({ from: "skeptic", to: e.to ?? [], kind: "challenge", seq: e.seq, text: e.text, candidate: e.candidate });
        m("skeptic").status = "done";
        m("skeptic").bubble = { text: `${e.candidate}: ${e.verdict}. ${e.text}`, kind: e.verdict === "keep" ? "agrees" : "challenge", seq: e.seq };
        m("skeptic").activity = "Challenged every candidate";
        break;
      case "stance":
        if (e.stance === "support" || e.stance === "challenge") {
          s.threads.push({ from: e.from_, to: e.to ?? [], kind: e.stance, seq: e.seq, text: e.text, candidate: e.candidate });
        }
        m(e.from_).bubble = { text: `${e.candidate}: ${e.text}`, kind: e.stance === "challenge" || e.stance === "concede" ? "challenge" : e.stance, seq: e.seq };
        break;
      case "comment":
        m(e.from_).bubble = { text: e.text, kind: e.kind, seq: e.seq };
        break;
      case "conference_round":
        if (e.round === 2 && e.status === "started" && e.name) { s.stage = "round2"; s.coordinator.activity = "Round 2: looking for connections across the board"; }
        if (e.round === 2 && e.status === "done") s.coordinator.activity = e.candidates ? `${e.candidates.length} candidate explanation(s) for the debate` : "Conference closed after round 2";
        if (e.round === 3 && e.status === "started") { s.stage = "round3"; s.active.add("skeptic"); m("skeptic").status = "working"; m("skeptic").activity = "Looking for simpler explanations"; s.coordinator.activity = "Round 3: the skeptic challenges each candidate"; }
        if (e.round === 3 && e.status === "done") s.coordinator.activity = "Debate closed (hard stop)";
        break;
      case "coordinator_thinking":
        if (e.stage === "synthesis") { s.coordinator.activity = "Writing the case summary"; s.stage = "synthesis"; }
        else if (e.stage === "consult") s.coordinator.activity = "Considering one extra consult";
        else if (e.stage === "consult_decision") s.coordinator.activity = e.consult ? `Called in ${e.consult.replace(/_/g, " ")}` : "No extra consult needed";
        break;
      case "safety_check":
        s.stage = "safety";
        s.coordinator.safety = e.stage === "done" ? (e.emergency ? "Safety review: urgent items flagged" : "Safety review passed")
          : e.stage === "model" ? `Safety reviewer: ${e.edits} edit(s)` : e.stage === "code" ? `Code checks: ${e.blocked} blocked` : "Safety reviewer checking";
        s.coordinator.activity = "Safety review of the summary";
        break;
      case "error":
        if (e.specialty && !e.retrying && s.members[e.specialty]) { s.members[e.specialty].status = "failed"; s.members[e.specialty].activity = "Could not finish"; }
        break;
      case "final":
        s.stage = "done";
        s.coordinator.done = true;
        s.coordinator.activity = e.status === "complete" ? "Case summary ready" : `Finished: ${e.status}`;
        break;
    }
  }
  return s;
}

// ---- chat overlay: the same doctors light up while answering a chat question -------------

export interface ChatOverlay {
  members: Record<string, { status: "working" | "done" | "failed"; bubble?: string }>;
  coordinator?: string;
}
