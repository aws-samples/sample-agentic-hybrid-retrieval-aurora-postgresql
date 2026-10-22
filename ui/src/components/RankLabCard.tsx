import { forwardRef, useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import type { MosaicLabMission } from "../labMissions";
import { wantedProduct, type LabOutcome } from "../labOutcome";
import type { SearchResponse } from "../types";
import { useLabStates } from "../useLabStates";
import { useWantedName } from "../useWantedName";

/** A good reference result is not a participant repair. Check entry and run age. */
export const RankLabCard = forwardRef<HTMLElement, {
  mission: MosaicLabMission;
  response: SearchResponse;
  outcome: LabOutcome;
  playgroundHref: string;
  onSearchAgain: () => void;
}>(function RankLabCard({ mission, response, outcome, playgroundHref, onSearchAgain }, ref) {
  const eventId = response.search_event_id;
  const { labStates, failed, retry } = useLabStates(eventId);
  const lab = labStates?.find((item) => item.lab_id === 2);
  const [event, setEvent] = useState<{ id: string; at: string | null } | null>(null);
  useEffect(() => {
    let active = true;
    api.retrievalEvent(eventId).then((saved) => {
      if (active) setEvent({ id: eventId, at: saved.run.occurred_at });
    }).catch(() => {
      if (active) setEvent({ id: eventId, at: null });
    });
    return () => { active = false; };
  }, [eventId]);

  const name = useWantedName(mission, response) ?? "wanted product";
  const wanted = wantedProduct(mission, response);

  let status = "Lab 2 / Not checked";
  let title = "Checking the exercise state";
  let detail = "Checking whether Lab 2 has started.";
  let tone = "neutral";
  const occurred = event?.id === eventId && event.at ? Date.parse(event.at) : NaN;
  const started = lab?.started_at ? Date.parse(lab.started_at) : NaN;
  if (failed) {
    title = "Exercise state unavailable";
    detail = "Retry the state check before treating this search as a repair.";
  } else if (lab?.entry_state === "not_started") {
    status = "Lab 2 / Not started";
    title = "The ranking exercise is next";
    detail = "Finish Lab 1 and prepare Lab 2 in the guide. This request shows its results once Lab 2 has started.";
  } else if (lab?.entry_state === "incomplete") {
    status = "Lab 2 / Preparation incomplete";
    title = "Finish preparing the ranking exercise";
    detail = "Run the guide’s preparation command again. It resumes where it stopped and keeps your edits.";
  } else if (lab?.entry_state === "started") {
    status = "Lab 2 / Send Alex’s monitor request";
    if (!Number.isFinite(occurred) || !Number.isFinite(started)) {
      title = "Search timing not verified";
      detail = "Search again to record a result for this exercise. This saved result cannot verify your repair yet.";
    } else if (occurred < started) {
      title = "This search predates Lab 2";
      detail = "Search again with the same request and filters to inspect the exercise you started.";
    } else if (outcome.tone === "unhealthy") {
      title = outcome.title;
      detail = outcome.detail;
      tone = "unhealthy";
    } else if (outcome.tone === "fixed" && lab.source_state === "solved" && lab.database_state === "applied") {
      status = "Lab 2 / Verified in this search";
      title = outcome.title;
      detail = outcome.detail;
      tone = "fixed";
    } else {
      title = `Where is the ${name}?`;
      const where = wanted?.tier === "missing"
        ? `The ${name} is not in these results.`
        : wanted?.finalRank != null
          ? `The ${name} is at final #${wanted.finalRank}.`
          : "";
      detail = `${where} Open Why this match on a result for each search’s position and contribution, then Compare positions for the order before and after reranking.`.trim();
    }
  }

  return <section ref={ref} className={`shop-lab-callout shop-rank-card ${tone}`} aria-label="Lab 2 outcome">
    <span className="shop-lab-status">{status}</span>
    <h2>{title}</h2>
    <p>{detail}</p>
    <div className="shop-lab-callout-actions">
      <Link className="shop-lab-callout-playground" href={playgroundHref}>Inspect this run in the Playground</Link>
      <button type="button" onClick={failed ? retry : onSearchAgain}>{failed ? "Retry state check" : "Search again"}</button>
    </div>
  </section>;
});
