import { useEffect, useMemo, useState } from "react";
import { api, type CaseDetail } from "../api/client";
import { regionsFromSummary, type BoardPost, type ChatOverlay, type RosterEntry } from "../lib/panel";
import ChatPanel from "./ChatPanel";
import BodyMap from "./BodyMap";
import { EmergencyBanner } from "./Common";
import PanelTable from "./PanelTable";
import { PanelActivity, useRunEvents, waitForResult } from "./RunTimeline";
import ConferenceDiagram from "./ConferenceDiagram";
import FloatingChat from "./FloatingChat";
import SummaryView, { SpecialistReports } from "./SummaryView";

let rosterCache: RosterEntry[] | null = null;

/** What is lit up across the room: an explanation card, a board post or a body region, and
 *  everything linked to it (posts, doctors, regions). Hover previews; click pins. */
interface Focus { cards: string[]; refs: string[]; members: string[]; regions: string[]; label: string | null; pinned: boolean; key: string }
const NO_FOCUS: Focus = { cards: [], refs: [], members: [], regions: [], label: null, pinned: false, key: "" };

/** The case room: panel on top, body and summary in the middle, chat below, details last. */
export default function CaseRoom({ c, patientName, onFinished }: {
  c: CaseDetail; patientName: string; onFinished: () => Promise<CaseDetail>;
}) {
  const live = c.running || c.status === "running";
  const [roster, setRoster] = useState<RosterEntry[]>(rosterCache ?? []);
  const [waiting, setWaiting] = useState(false);
  const [overlay, setOverlay] = useState<ChatOverlay | null>(null);
  const events = useRunEvents(c.id, live ? async () => { setWaiting(true); await waitForResult(onFinished); } : undefined);

  useEffect(() => {
    if (!rosterCache) api.roster().then((r) => { rosterCache = r; setRoster(r); }).catch(() => undefined);
  }, []);

  const result = c.result;
  const em = result?.emergency;
  const regions = regionsFromSummary(result?.summary, roster);
  const [focus, setFocus] = useState<Focus>(NO_FOCUS);
  const [unread, setUnread] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cards: any[] = useMemo(() => result?.summary?.explanations ?? [], [result]);
  const board: BoardPost[] = useMemo(() => result?.board ?? [], [result]);
  const names = useMemo(() => Object.fromEntries(roster.map((r) => [r.id, r.name])), [roster]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fromCards = (list: any[], extra: Partial<Focus>): Focus => ({
    cards: list.map((x) => x.id), refs: [...new Set(list.flatMap((x) => x.refs))],
    members: [...new Set(list.flatMap((x) => x.specialists.map((m: { id: string }) => m.id)))],
    regions: [...new Set(list.flatMap((x) => x.regions))], label: list.length === 1 ? `${list[0].id} · ${list[0].title}` : null,
    pinned: false, key: "", ...extra,
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const focusCard = (card: any | null, pin = false) => {
    if (!card) { if (!focus.pinned) setFocus(NO_FOCUS); return; }
    if (focus.pinned && !pin) return;                       // a pinned selection wins over hovering
    if (pin && focus.pinned && focus.key === `card:${card.id}`) { setFocus(NO_FOCUS); return; }
    setFocus(fromCards([card], { pinned: pin, key: `card:${card.id}` }));
  };
  const focusPost = (post: BoardPost | null) => {
    if (!post) { setFocus(NO_FOCUS); return; }
    const linked = cards.filter((x) => x.refs.includes(post.id));
    setFocus({ cards: linked.map((x) => x.id), refs: [post.id], members: [post.by], regions: post.region ? [post.region] : [],
      label: `${post.id} · ${post.line}`, pinned: true, key: `post:${post.id}` });
  };
  const focusRef = (ref: string) => {
    const post = board.find((p) => p.id === ref);
    if (post) focusPost(post);
  };
  const selectRegion = (region: string | null) => {
    if (!region || focus.key === `region:${region}`) { setFocus(NO_FOCUS); return; }
    const linked = cards.filter((x) => x.regions.includes(region));
    setFocus(linked.length ? fromCards(linked, { regions: [region], pinned: true, key: `region:${region}`,
      label: linked.length > 1 ? `${linked.length} explanations involve this area` : "1 explanation involves this area" })
      : { ...NO_FOCUS, regions: [region], pinned: true, key: `region:${region}`, label: "No explanation card involves this area" });
  };

  return (
    <div className="case-room">
      {em?.active && <EmergencyBanner emergency={{ kind: em.crisis ? "crisis" : "medical", message: em.message }} reasons={em.reasons} actions={em.actions} />}

      <PanelTable events={events} roster={roster} patientName={patientName} live={live}
        medicationFallback={result?.pharmacist?.combined_list?.length} overlay={overlay}
        focusMembers={focus.members} focusRefs={focus.refs} onFocusPost={focusPost} boardFallback={board} />

      <div className="room-middle">
        <div className="room-body">
          <BodyMap regions={regions} waiting={live || !result?.summary} focusRegions={focus.regions} focusLabel={focus.label}
            onSelectRegion={selectRegion} />
        </div>
        <div className="room-summary">
          {live || !result ? (
            <PanelActivity events={events} live waiting={waiting} compact />
          ) : (
            <SummaryView result={result} focus={focus} onFocusCard={focusCard} onFocusRef={focusRef} names={names} />
          )}
        </div>
      </div>

      <FloatingChat available={!live && !!result?.summary} unread={unread} onOpen={() => setUnread(false)}>
        {live || !result ? (
          <p className="muted small chat-intro">You can ask the panel questions as soon as the summary is ready.</p>
        ) : (
          <ChatPanel caseId={c.id} roster={roster} coordinatorId={result?.modes?.coordinator ?? "internal_medicine"} onOverlay={setOverlay}
            onAnswer={() => setUnread(true)} docked />
        )}
      </FloatingChat>

      {!live && result && (
        <>
          <SpecialistReports result={result} />
          <ConferenceDiagram result={result} names={names} />
        </>
      )}
    </div>
  );
}
