import { useEffect, useState } from "react";
import { api, type CaseDetail } from "../api/client";
import { regionsFromSummary, type ChatOverlay, type RosterEntry } from "../lib/panel";
import ChatPanel from "./ChatPanel";
import BodyMap from "./BodyMap";
import { EmergencyBanner } from "./Common";
import PanelTable from "./PanelTable";
import RunDetails from "./RunDetails";
import { PanelActivity, useRunEvents, waitForResult } from "./RunTimeline";
import SummaryView, { RunMeta, SpecialistReports } from "./SummaryView";

let rosterCache: RosterEntry[] | null = null;

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

  return (
    <div className="case-room">
      {em?.active && <EmergencyBanner emergency={{ kind: em.crisis ? "crisis" : "medical", message: em.message }} reasons={em.reasons} actions={em.actions} />}

      <PanelTable events={events} roster={roster} patientName={patientName} live={live}
        medicationFallback={result?.pharmacist?.combined_list?.length} overlay={overlay} />

      <div className="room-middle">
        <div className="room-body">
          <BodyMap regions={regions} waiting={live || !result?.summary} />
        </div>
        <div className="room-summary">
          {live || !result ? (
            <PanelActivity events={events} live waiting={waiting} compact />
          ) : (
            <SummaryView result={result} />
          )}
        </div>
      </div>

      {live ? (
        <section className="card chat-slot" aria-label="Ask the panel">
          <h2>Ask the panel</h2>
          <p className="muted small">You can ask the panel questions as soon as the summary is ready.</p>
        </section>
      ) : (
        <ChatPanel caseId={c.id} roster={roster} coordinatorId={result?.modes?.coordinator ?? "internal_medicine"} onOverlay={setOverlay} />
      )}

      {!live && result && (
        <>
          <SpecialistReports result={result} />
          <details className="card conference-log">
            <summary><strong>Full conference log</strong> <span className="muted small">· every routing step, tool call and comment</span></summary>
            <PanelActivity events={events} />
          </details>
          <RunDetails caseId={c.id} roster={roster} />
          <RunMeta result={result} />
        </>
      )}
    </div>
  );
}
