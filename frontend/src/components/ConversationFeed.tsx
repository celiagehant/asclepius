import { useEffect, useRef } from "react";
import { colorOf, shortName, SPECIALTY_ICONS, type RosterEntry, type TalkEntry } from "../lib/panel";

// The conference conversation as a readable transcript, like a chat between the doctors:
// who spoke, to whom, what kind of remark it was, and what they said. The speech bubbles at the
// table are only short previews; this is where people can actually follow the discussion.

const KIND: Record<string, { label: string; cls: string }> = {
  connects: { label: "connects", cls: "k-connect" }, supports: { label: "supports", cls: "k-support" },
  challenges: { label: "challenges", cls: "k-challenge" }, keeps: { label: "keeps", cls: "k-support" },
  defends: { label: "defends", cls: "k-defend" }, concedes: { label: "concedes", cls: "k-concede" },
  answers: { label: "answers", cls: "k-answer" }, note: { label: "says", cls: "k-answer" },
};

export default function ConversationFeed({ talk, roster, coordinatorId, live, focus, onFocus }: {
  talk: TalkEntry[]; roster: RosterEntry[]; coordinatorId: string; live?: boolean; focus: Set<string>;
  onFocus?: (members: string[] | null) => void;
}) {
  const names = Object.fromEntries(roster.map((r) => [r.id, r.name]));
  const name = (id?: string) => (id ? shortName(names[id] ?? id.replace(/_/g, " ")) : "");
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => { if (live) end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [talk.length, live]);
  const spoken = talk.filter((t) => t.kind !== "round" && t.kind !== "lookup").length;

  return (
    <div className="convo">
      {talk.length === 0 && <p className="muted small convo-empty">{live ? "The doctors are opening their case files…" : "No conversation was recorded for this case."}</p>}
      {talk.length > 0 && spoken === 0 && !live && <p className="muted small convo-empty">This case was reviewed before the doctors' conversation was recorded.</p>}
      <ul className="convo-list">
        {talk.map((t) => {
          if (t.kind === "round") return <li key={t.seq} className="convo-round"><span>{t.text}</span></li>;
          if (t.kind === "lookup") return (
            <li key={t.seq} className="convo-lookup"><span aria-hidden>📚</span> <strong>{name(t.from)}</strong> {t.text}</li>
          );
          const k = KIND[t.kind] ?? KIND.note;
          const who = t.from ?? coordinatorId;
          const members = [who, ...(t.to ?? [])];
          const on = focus.size > 0 && members.some((x) => focus.has(x));
          return (
            <li key={t.seq} className={`convo-msg ${on ? "on" : ""}`} tabIndex={0}
              onClick={() => onFocus?.(on ? null : members)} onKeyDown={(e) => { if (e.key === "Enter") onFocus?.(members); }}>
              <span className="convo-avatar" style={{ ["--c" as string]: colorOf(who) }} aria-hidden>{SPECIALTY_ICONS[who] ?? "•"}</span>
              <div className="convo-body">
                <div className="convo-head">
                  <strong style={{ color: colorOf(who) }}>{name(who)}{who === coordinatorId ? " (coordinator)" : ""}</strong>
                  <span className={`convo-kind ${k.cls}`}>{k.label}</span>
                  {(t.to?.length ?? 0) > 0 && <span className="convo-to">→ {t.to!.map(name).join(", ")}</span>}
                </div>
                <p>{t.candidate && <span className="convo-cand">{t.candidate}</span>} {t.text}</p>
              </div>
            </li>
          );
        })}
        <li ref={end} aria-hidden className="convo-end" />
      </ul>
    </div>
  );
}
