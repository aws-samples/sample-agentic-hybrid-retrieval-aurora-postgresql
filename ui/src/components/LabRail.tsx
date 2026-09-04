import { ArrowRight, FileCode2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import {
  coreMosaicLabs,
  mosaicRetrievalExamples,
  retrievalExampleHref,
  type MosaicLabMission,
} from "../labMissions";
import type { LabStateRecord } from "../types";

/**
 * Where the participant is, what they are here to change, and what the room
 * currently holds.
 *
 * The Playground could say what a run did in seven ways and never say which lab
 * the reader was in. Three numbered stages describe the pipeline, not the
 * session: a participant halfway through Lab 2 saw the same masthead, the same
 * four stages and the same scenario picker they saw in Lab 1, with nothing on
 * screen naming the file they were supposed to be editing.
 *
 * So one rail, above the stages and sticky, carrying the four facts a lab needs
 * and nothing else: which lab, the three beats it runs in, the one bounded edit,
 * and where that edit currently stands in both places it can stand.
 */

/** What a lab is worth reporting on, in the order the session runs them. */
const BEATS = [
  {
    label: "Observe",
    href: "#labs-stage-retrieve",
    hint: "what the run actually did",
  },
  {
    label: "Repair",
    href: "#labs-repair-title",
    hint: "the two runs, side by side",
  },
  {
    label: "Prove",
    href: "#labs-stage-prove",
    hint: "the measured scorecard",
  },
] as const;

/**
 * The required lab a scenario belongs to.
 *
 * The picker offers supporting checks alongside the three labs, and those carry
 * a `placement` naming their parent rather than a lab of their own. Selecting
 * `exact-identity` must not read as having left Lab 1, and an id this build does
 * not know must not blank the rail, so both fall back to the lab in front.
 */
export function activeCoreLab(missionId: string | null): MosaicLabMission {
  const direct = coreMosaicLabs.find((lab) => lab.id === missionId);
  if (direct) return direct;
  const supporting = mosaicRetrievalExamples.find(
    (example) => example.id === missionId,
  );
  const placement = supporting?.placement ?? "";
  const placed = /^lab-([123])$/.exec(placement);
  if (placed) return coreMosaicLabs[Number(placed[1]) - 1] ?? coreMosaicLabs[0];
  return coreMosaicLabs[0];
}

/** `not_applicable` is a sentence, not an identifier, once it reaches a chip. */
function readableState(state: string): string {
  return state.replaceAll("_", " ");
}

export function LabRail({ missionId }: { missionId: string | null }) {
  const lab = activeCoreLab(missionId);
  const labNumber = coreMosaicLabs.indexOf(lab) + 1;
  const nextLab = coreMosaicLabs[labNumber];
  const [labStates, setLabStates] = useState<LabStateRecord[] | null>(null);

  /**
   * Read once per mount rather than polled. The route is side-effect free and
   * cheap, but a participant edits a file and re-applies it out of band, so a
   * chip that refreshed on its own would still be behind whatever they just did.
   * Reloading the page is the honest refresh, and it is the one they already
   * make after applying SQL.
   */
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

  const state = labStates?.find((record) => record.lab_id === labNumber) ?? null;
  const edit = lab.participant_edit;

  return (
    <nav aria-label="Lab rail" className="labs-rail">
      <div className="labs-rail-lab">
        <span className="labs-rail-kicker">
          Lab {labNumber} of {coreMosaicLabs.length}
        </span>
        <strong>{lab.title}</strong>
      </div>

      <ol aria-label="Lab beats" className="labs-rail-beats">
        {BEATS.map((beat) => (
          <li key={beat.label}>
            <a href={beat.href}>{beat.label}</a>
            <small>{beat.hint}</small>
          </li>
        ))}
      </ol>

      {edit ? (
        <p className="labs-rail-edit">
          <FileCode2 aria-hidden="true" size={15} />
          <code>{edit.file}</code>
          <small>{edit.task}</small>
        </p>
      ) : null}

      {/* Two chips, never one. Editing the file without re-applying it leaves a
          repaired file in front of an unrepaired cluster, and a single "lab
          state" would report that as solved. */}
      <ul aria-label="Lab state" className="labs-rail-state">
        <li>source: {state ? state.source_state : "not checked"}</li>
        <li>
          database: {state ? readableState(state.database_state) : "not checked"}
        </li>
      </ul>

      {nextLab ? (
        <Link className="labs-rail-next" href={retrievalExampleHref(nextLab)}>
          Next lab: {nextLab.title}
          <ArrowRight aria-hidden="true" size={15} />
        </Link>
      ) : null}
    </nav>
  );
}
