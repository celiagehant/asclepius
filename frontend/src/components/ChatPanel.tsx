import { useEffect, useRef, useState } from "react";
import { api, type ChatEvent, type ChatMessage } from "../api/client";
import { colorOf, shortName, SPECIALTY_ICONS, type ChatOverlay, type RosterEntry } from "../lib/panel";
import { EmergencyBanner } from "./Common";

const STARTERS = [
  "What should I ask my doctors first?",
  "Could any of my medicines be related to my symptoms?",
  "Which result matters most, and why?",
];

function firstSentence(text: string): string {
  const m = text.match(/^.{20,160}?[.!?](\s|$)/);
  return (m ? m[0] : text.slice(0, 140)).trim();
}

export default function ChatPanel({ caseId, roster, coordinatorId, onOverlay, onAnswer, docked }: {
  caseId: number; roster: RosterEntry[]; coordinatorId: string; onOverlay: (o: ChatOverlay | null) => void;
  onAnswer?: () => void; docked?: boolean;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [available, setAvailable] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [answering, setAnswering] = useState<Record<string, "working" | "done" | "failed">>({});
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const questionRef = useRef(0);  // so an old question's timer never clears a newer question's lights
  const names = Object.fromEntries(roster.map((r) => [r.id, r.name]));

  useEffect(() => {
    api.chatHistory(caseId).then((h) => { setMessages(h.messages); setAvailable(h.available); setBusy(h.busy); }).catch(() => undefined);
  }, [caseId]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [messages, status]);

  const ask = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    const token = ++questionRef.current;
    setBusy(true);
    setError(null);
    setDraft("");
    setAnswering({});
    setStatus("The coordinator is choosing who should answer…");
    setMessages((m) => [...m, { id: -Date.now(), role: "user", content: question, meta: {} }]);
    const lit: ChatOverlay = { members: {}, coordinator: "Routing your question" };
    onOverlay({ ...lit });
    try {
      await api.askChat(caseId, question, (e: ChatEvent) => {
        if (e.type === "chat_routed") {
          setStatus(`${e.names.join(" and ")} ${e.names.length > 1 ? "are" : "is"} answering…`);
          lit.coordinator = `Asked ${e.names.map(shortName).join(" and ")} to answer`;
        } else if (e.type === "specialist_started") {
          lit.members[e.specialty] = { status: "working" };
          setAnswering((a) => ({ ...a, [e.specialty]: "working" }));
        } else if (e.type === "specialist_done") {
          lit.members[e.specialty] = { status: "done" };
          setAnswering((a) => ({ ...a, [e.specialty]: "done" }));
        } else if (e.type === "error" && e.specialty) {
          lit.members[e.specialty] = { status: "failed" };
          setAnswering((a) => ({ ...a, [e.specialty]: "failed" }));
        } else if (e.type === "coordinator_thinking" && e.stage === "wrap_up") {
          setStatus("The coordinator is writing a short wrap-up…");
          lit.coordinator = "Writing a wrap-up";
        } else if (e.type === "safety_check" && e.stage === "started") {
          setStatus("The safety reviewer is checking every answer…");
          lit.coordinator = "Safety reviewer checking the answers";
        } else if (e.type === "final") {
          if (e.message) {
            const msg = e.message as ChatMessage;
            setMessages((m) => [...m, msg]);
            onAnswer?.();
            for (const a of msg.meta.answers ?? []) lit.members[a.specialty] = { status: "done", bubble: firstSentence(a.text) };
            lit.coordinator = msg.role === "safety" ? "Emergency guidance shown" : "Answer checked and shared";
          } else if (e.error) {
            setError(e.error);
          }
        }
        onOverlay({ members: { ...lit.members }, coordinator: lit.coordinator });
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      setStatus(null);
      window.setTimeout(() => { if (token === questionRef.current) onOverlay(null); }, 12000);  // back to the conference view
    }
  };

  return (
    <section className={docked ? "chat docked" : "card chat"} aria-label="Ask the panel">
      {docked ? (
        <p className="muted small chat-intro">Your question goes to the most relevant AI specialists (or the pharmacist for medicines); ask how two
          things are related and the coordinator adds what else could explain it. A safety reviewer checks every answer.</p>
      ) : (
        <div className="chat-head">
          <div>
            <h2>Ask the panel</h2>
            <p className="muted small">The coordinator sends your question to the one or two most relevant AI specialists (or the pharmacist for
              medicines). A safety reviewer checks every answer. Answers use only your records and profile.</p>
          </div>
        </div>
      )}

      <div className="chat-log" aria-live="polite">
        {messages.length === 0 && available && (
          <div className="starters">
            {STARTERS.map((s) => <button key={s} className="chip-btn" onClick={() => ask(s)} disabled={busy}>{s}</button>)}
          </div>
        )}
        {!available && <p className="muted small">The panel can answer questions once it has reviewed this case.</p>}
        {messages.map((m) => <Message key={m.id} m={m} names={names} coordinatorId={coordinatorId} />)}
        {busy && (
          <div className="chat-pending">
            <div className="answering">
              {Object.entries(answering).map(([id, st]) => (
                <span key={id} className={`mini-doc mini-${st}`} style={{ ["--c" as string]: colorOf(id) }} title={names[id]}>
                  <span className="avatar">{SPECIALTY_ICONS[id] ?? "•"}</span>{shortName(names[id] ?? id)}
                </span>
              ))}
            </div>
            <span className="muted small"><span className="typing" aria-hidden><i /><i /><i /></span> {status}</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && <p className="error-text small">{error}</p>}
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(draft); }}>
        <textarea rows={2} maxLength={1500} value={draft} disabled={!available} placeholder={available ? "Ask about your case…" : "Available after the review"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(draft); } }} />
        <button className="btn" disabled={!available || busy || !draft.trim()}>{busy ? "Answering…" : "Ask"}</button>
      </form>
      <p className="muted small chat-foot">Not a diagnosis or medical advice. In an emergency call 911 (or 988 for a mental health crisis).</p>
    </section>
  );
}

export function Message({ m, names, coordinatorId }: { m: ChatMessage; names: Record<string, string>; coordinatorId: string }) {
  if (m.role === "user") return <div className="msg-user"><div className="msg-bubble">{m.content}</div></div>;
  if (m.role === "safety") {
    const em = m.meta.emergency;
    return <EmergencyBanner emergency={{ kind: em?.kind ?? "medical", message: m.content }} reasons={em?.matches?.map((x) => `You mentioned: ${x}.`)} />;
  }
  const edits = (m.meta.safety?.edits?.length ?? 0) + (m.meta.safety?.blocked?.length ?? 0);
  return (
    <div className="msg-panel">
      {m.meta.emergency && <EmergencyBanner emergency={{ kind: "medical", message: m.meta.emergency.message }} />}
      {m.meta.connection && (
        <div className={`connection-note link-${m.meta.connection.status}`}>
          <strong>How are “{m.meta.connection.topic_a}” and “{m.meta.connection.topic_b}” related?</strong>{" "}
          {m.meta.connection.status === "linked" ? `The panel linked them in ${m.meta.connection.cards.join(", ")}. The coordinator adds what else could explain it.`
            : m.meta.connection.status === "both_on_board_no_card" ? "Both are in your records, but the panel did not find a supported link between them."
            : "The panel did not find a link between these in your records."}
        </div>
      )}
      {(m.meta.answers ?? []).map((a) => (
        <div key={a.specialty} className="answer" style={{ ["--c" as string]: colorOf(a.specialty) }}>
          <span className="avatar">{SPECIALTY_ICONS[a.specialty] ?? "•"}</span>
          <div>
            <div className="answer-who"><strong>{names[a.specialty] ?? a.name}</strong> <span className="ai-tag">AI specialist</span></div>
            <p>{a.text}</p>
            {a.ask_your_doctor && <p className="ask-doc"><strong>Ask your doctor:</strong> {a.ask_your_doctor}</p>}
            {a.sources.length > 0 && (
              <p className="small">Sources: {a.sources.map((s, i) => <span key={s.url}>{i > 0 && " · "}<a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></span>)}</p>
            )}
            {a.source_note && <p className="muted small">{a.source_note}</p>}
          </div>
        </div>
      ))}
      {m.meta.wrap_up && (
        <div className="answer wrap" style={{ ["--c" as string]: colorOf(coordinatorId) }}>
          <span className="avatar">{SPECIALTY_ICONS[coordinatorId] ?? "⚕"}</span>
          <div>
            <div className="answer-who"><strong>{shortName(names[coordinatorId] ?? "Coordinator")}</strong> <span className="ai-tag">Coordinator</span></div>
            <p>{m.meta.wrap_up}</p>
          </div>
        </div>
      )}
      <div className="reviewed small">🛡 Checked by the safety reviewer{edits ? ` · ${edits} part${edits > 1 ? "s" : ""} adjusted for safety` : ""}</div>
    </div>
  );
}
