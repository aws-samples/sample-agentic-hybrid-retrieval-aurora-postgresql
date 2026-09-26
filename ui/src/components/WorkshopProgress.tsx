import { ArrowRight } from "lucide-react";
import { Link } from "wouter";
import { isLabRepaired } from "../labStateCopy";
import { coreMosaicLabs, retrievalExampleHref, type MosaicLabMission } from "../labMissions";
import { useLabStates } from "../useLabStates";
import type { LabStateRecord } from "../types";

export type WorkshopLabStatus = "not_checked" | "needs_repair" | "repaired";

/**
 * Collapse one lab's raw state into the three statuses this panel shows.
 *
 * `isLabRepaired` is the single, shared repaired/not-repaired boolean
 * (`../labStateCopy`); this only adds the third case a bare boolean cannot
 * express -- no record for this lab has come back yet, which must read as
 * "not checked" rather than as either a pass or a fault.
 */
export function workshopLabStatus(record: LabStateRecord | null): WorkshopLabStatus {
  if (!record) return "not_checked";
  return isLabRepaired(record) ? "repaired" : "needs_repair";
}

const STATUS_LABEL: Record<WorkshopLabStatus, string> = {
  not_checked: "Not checked",
  needs_repair: "Needs repair",
  repaired: "Repaired",
};

/** The first lab this build cannot confirm is repaired, or none once all three are. */
function nextLab(
  statuses: WorkshopLabStatus[],
): { lab: MosaicLabMission; index: number } | null {
  const index = statuses.findIndex((status) => status !== "repaired");
  return index < 0 ? null : { lab: coreMosaicLabs[index], index };
}

/**
 * The action label for the lab named by `next`, or the all-done case.
 *
 * There is no API fact that tells "never attempted" from "attempted and
 * still broken" apart -- a fresh account and a mid-repair one both report
 * `source_state: "broken"` -- so the wording cannot promise to know which one
 * this is. "Open Lab 1" is the honest word for "the first lab, nothing in the
 * sequence is repaired yet"; once any lab is repaired the participant has
 * plainly started, and every later lab reads "Continue".
 */
function ctaLabel(next: { lab: MosaicLabMission; index: number } | null, anyRepaired: boolean): string {
  if (!next) return "Review your labs";
  if (next.index === 0 && !anyRepaired) return `Open ${next.lab.title}`;
  return `Continue ${next.lab.title}`;
}

/**
 * The one place the required sequence is named as a sequence, with a single
 * action into it.
 *
 * Everything else this page shows is either Alex's ungraded requests or a
 * link to optional material (Scale & HNSW, Session & Memory, product
 * comparisons); nothing said which three labs are the actual session, in
 * what order, or where to start. This is that entry.
 *
 * It reads `GET /api/labs/state` through the shared `useLabStates` hook --
 * the same cheap, side-effect-free call `LabRail` already polls while a
 * participant works -- rather than `POST /api/labs/{id}/proof`, because a
 * landing page must not spend a live Aurora search just from being opened.
 * Per house standard 3 (probes run the production path) the *lab* pages
 * still grade completion against the proof endpoint; this panel only ever
 * claims what the cheap read supports. A request that has not returned yet
 * reports every lab "Not checked" the same way a failed one does, but a
 * failed read also says so directly, since the two are not the same thing to
 * a participant deciding whether to reload.
 */
export function WorkshopProgress() {
  const { labStates, failed } = useLabStates();

  const statuses = coreMosaicLabs.map((lab, index) =>
    workshopLabStatus(labStates?.find((record) => record.lab_id === index + 1) ?? null),
  );
  const next = nextLab(statuses);
  const anyRepaired = statuses.some((status) => status === "repaired");
  const ctaTarget = next ? next.lab : coreMosaicLabs[0];

  return (
    <section className="workshop-entry" aria-labelledby="workshop-entry-title">
      <div className="workshop-entry-copy">
        <span className="workshop-entry-kicker">Required workshop path</span>
        <h2 id="workshop-entry-title">Retrieve &rarr; Rank &rarr; Reason</h2>
        <p>
          Three labs, in order, are the session. Alex&rsquo;s other requests below,
          Scale &amp; HNSW, and Session &amp; Memory are all optional and are not
          needed to finish it.
        </p>
        {failed ? (
          <p className="workshop-entry-status" role="status">
            Lab state unavailable; reload to retry.
          </p>
        ) : null}
      </div>
      <ol className="workshop-entry-labs">
        {coreMosaicLabs.map((lab, index) => (
          <li key={lab.id} data-status={statuses[index]}>
            <Link
              href={retrievalExampleHref(lab)}
              aria-current={next?.index === index ? "step" : undefined}
            >
              <span className="workshop-entry-lab-number" aria-hidden="true">
                {index + 1}
              </span>
              <span className="workshop-entry-lab-copy">
                <strong>{lab.title}</strong>
                <small>{STATUS_LABEL[statuses[index]]}</small>
              </span>
            </Link>
          </li>
        ))}
      </ol>
      <Link className="workshop-entry-cta primary-button" href={retrievalExampleHref(ctaTarget)}>
        {ctaLabel(next, anyRepaired)}
        <ArrowRight size={16} aria-hidden="true" />
      </Link>
    </section>
  );
}
