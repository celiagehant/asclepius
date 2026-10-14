import { useRef, useState } from "react";
import type { ChatMessage } from "../api/client";
import { Message } from "../components/ChatPanel";
import { colorOf, shortName, SPECIALTY_ICONS, type ChatOverlay, type RosterEntry } from "../lib/panel";
import type { DemoChatItem } from "./DemoApp";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const firstSentence = (t: string) => (t.match(/^.{20,160}?[.!?](\s|$)/)?.[0] ?? t.slice(0, 140)).trim();

/** Recorded chat questions: clicking one replays how the panel answered it, with the doctors lighting up. */
export default function DemoChat({ items, roster, coordinatorId, onOverlay }: {
  items: DemoChatItem[]; roster: RosterEntry[]; coordinatorId: string; onOverlay: (o: ChatOverlay | null) => void;
}) {
  const [log, setLog] = useState<ChatMessage[]>([]);
  const [asked, setAsked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [answering, setAnswering] = useState<string[]>([]);
  const token = useRef(0);
  const names = Object.fromEntries(roster.map((r) => [r.id, r.name]));

  const ask = async (i: number) => {
    if (busy) return;
    const item = items[i];
    const routed = item.message.meta.routed ?? (item.message.meta.answers ?? []).map((a) => a.specialty);
    const mine = ++token.current;
    setBusy(true);
    setAsked((s) => new Set(s).add(i));
    setLog((l) => [...l, { id: -i - 1, role: "user", content: item.question, meta: {} }]);
    setStatus("The coordinator is choosing who should answer…");
    onOverlay({ members: {}, coordinator: "Routing your question" });
    await wait(900);
    setAnswering(routed);
    setStatus(`${routed.map((r) => names[r] ?? r).join(" and ")} ${routed.length > 1 ? "are" : "is"} answering…`);
    onOverlay({ members: Object.fromEntries(routed.map((r) => [r, { status: "working" as const }])), coordinator: `Asked ${routed.map((r) => shortName(names[r] ?? r)).join(" and ")} to answer` });
    await wait(1900);
    setStatus("The coordinator is writing a short wrap-up…");
    onOverlay({ members: Object.fromEntries(routed.map((r) => [r, { status: "done" as const }])), coordinator: "Writing a wrap-up" });
    await wait(800);
    setStatus("The safety reviewer is checking every answer…");
    onOverlay({ members: Object.fromEntries(routed.map((r) => [r, { status: "done" as const }])), coordinator: "Safety reviewer checking the answers" });
    await wait(800);
    setLog((l) => [...l, item.message]);
    onOverlay({ members: Object.fromEntries((item.message.meta.answers ?? []).map((a) => [a.specialty, { status: "done" as const, bubble: firstSentence(a.text) }])),
                coordinator: item.message.role === "safety" ? "Emergency guidance shown" : "Answer checked and shared" });
    setBusy(false);
    setAnswering([]);
    setTimeout(() => { if (mine === token.current) onOverlay(null); }, 9000);
  };

  return (
    <section className="card chat" aria-label="Ask the panel">
      <div className="chat-head">
        <h2>Ask the panel</h2>
        <p className="muted small">In the app, the coordinator routes each question to the one or two most relevant AI specialists (the pharmacist for medicines), they
          answer in their own voice, and a safety reviewer checks every answer. Here you can replay questions asked during the recorded session; watch the panel above.</p>
      </div>
      <div className="starters">
        {items.map((it, i) => (
          <button key={i} className={`chip-btn ${asked.has(i) ? "asked" : ""}`} disabled={busy} onClick={() => ask(i)}>{it.question}</button>
        ))}
      </div>
      <div className="chat-log" aria-live="polite">
        {log.map((m) => <Message key={m.id} m={m} names={names} coordinatorId={coordinatorId} />)}
        {busy && (
          <div className="chat-pending">
            <div className="answering">
              {answering.map((id) => (
                <span key={id} className="mini-doc mini-working" style={{ ["--c" as string]: colorOf(id) }}>
                  <span className="avatar">{SPECIALTY_ICONS[id] ?? "•"}</span>{shortName(names[id] ?? id)}
                </span>
              ))}
            </div>
            <span className="muted small"><span className="typing" aria-hidden><i /><i /><i /></span> {status}</span>
          </div>
        )}
      </div>
      <p className="muted small chat-foot">Live questions need the full app, which calls the AI model. Not a diagnosis or medical advice; in an emergency call 911.</p>
    </section>
  );
}
