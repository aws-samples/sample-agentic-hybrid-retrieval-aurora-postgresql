import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { coreMosaicLabs, retrievalExampleHref, type MosaicLabMission } from "../labMissions";
import type { LabStateRecord } from "../types";

export type WorkshopLabStatus = "not_checked" | "needs_repair" | "repaired";

/**
 * Whether one lab counts as repaired, collapsed from the same two-part
 * condition `labStateCopy` renders as two separate chips elsewhere: the
 * exercise file holds the fix, and Aurora holds the SQL that backs it.
 *
 * A lab whose file is repaired but whose database still holds the old
 * function is not repaired -- that gap is exactly what a single `solved`
 * flag would hide, and it is a state the workshop actually produces (editing
 * a file without re-applying it to Aurora).
 */
export function workshopLabStatus(record: LabStateRecord | null): WorkshopLabStatus {
  if (!record) return "not_checked";
  const repaired = record.source_state === "solved" && record.database_state !== "stale";
  return repaired ? "repaired" : "needs_repair";
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
 * The one place the required sequence is named as a sequence, with a single
 * action into it.
 *
 * Everything else this page shows is either Alex's ungraded requests or a
 * link to optional material (Scale & HNSW, Session & Memory, product
 * comparisons); nothing said which three labs are the actual session, in
 * what order, or where to start. This is that entry.
 *
 * It reads `GET /api/labs/state` -- the same cheap, side-effect-free call
 * `LabRail` already polls while a participant works -- rather than
 * `POST /api/labs/{id}/proof`, because a landing page must not spend a live
 * Aurora search just from being opened. Per house standard 3 (probes run the
 * production path) the *lab* pages still grade completion against the proof
 * endpoint; this panel only ever claims what the cheap read supports, and a
 * request that has not returned, or has failed, reports every lab "Not
 * checked" rather than guessing a status.
 */
export function WorkshopProgress() {
  const [labStates, setLabStates] = useState<LabStateRecord[] | null>(null);

  useEffect(() => {
    let active = true;
    api
      .labsState()
      .then((value) => {
        if (active) setLabStates(value.labs);
      })
      .catch(() => {
        if (active) setLabStates(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const statuses = coreMosaicLabs.map((lab, index) =>
    workshopLabStatus(labStates?.find((record) => record.lab_id === index + 1) ?? null),
  );
  const next = nextLab(statuses);
  const started = statuses.some((status) => status !== "not_checked");
  const ctaTarget = next ? next.lab : coreMosaicLabs[0];
  const ctaLabel = !next
    ? "Review your labs"
    : next.index === 0 && !started
      ? `Start ${next.lab.title}`
      : `Continue ${next.lab.title}`;

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
        {ctaLabel}
        <ArrowRight size={16} aria-hidden="true" />
      </Link>
    </section>
  );
}
