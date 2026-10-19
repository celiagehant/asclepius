import { useState, type ReactNode } from "react";

/** The chat as a floating window, like the help chats on many websites: a round button in the
 *  corner opens a panel that stays on screen while you scroll the case. Minimizing keeps the
 *  conversation (the chat stays mounted), and a dot on the button shows a new answer. */
export default function FloatingChat({ available, unread, onOpen, children }: {
  available: boolean; unread: boolean; onOpen: () => void; children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const show = () => { setOpen(true); onOpen(); };
  return (
    <>
      <div className={`chat-dock ${open ? "open" : ""}`} role="dialog" aria-label="Ask the panel" aria-hidden={!open}>
        <div className="dock-head">
          <div>
            <strong>Ask the panel</strong>
            <span className="dock-sub">AI specialist agents · answers use only your records</span>
          </div>
          <button className="dock-min" onClick={() => setOpen(false)} aria-label="Minimize the chat" title="Minimize">–</button>
        </div>
        <div className="dock-body">{children}</div>
      </div>
      {!open && (
        <button className={`chat-fab ${available ? "" : "waiting"}`} onClick={show} aria-label="Open the chat with the panel"
          title={available ? "Ask the panel about your case" : "The panel can answer once the summary is ready"}>
          <span className="fab-icon" aria-hidden>💬</span>
          <span className="fab-text">{available ? "Ask the panel" : "Chat opens after the review"}</span>
          {unread && <span className="fab-dot" aria-label="New answer" />}
        </button>
      )}
    </>
  );
}
