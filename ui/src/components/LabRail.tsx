import { ArrowRight, FileCode2 } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import {
  coreMosaicLabs,
  mosaicRetrievalExamples,
  retrievalExampleHref,
  stageLabels,
  type MosaicLabMission,
  type MosaicLabStage,
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
 * and nothing else: which lab, the stages it moves through, the one bounded
 * edit, and where that edit currently stands in both places it can stand.
 */

/**
 * The stages this page renders, in the order it renders them.
 *
 * The rail used to name its links after a three-beat sequence of its own, which
 * is a fourth vocabulary: the workshop teaches Retrieve -> Rank -> Reason, the
 * page draws four numbered stages under exactly those names, and the scenario
 * picker groups by them. Naming each link after the stage it scrolls to means a
 * participant reads one set of words everywhere and every link says where it
 * lands. The ids are the ones `PlaygroundStage` derives from those same titles.
 */
const RAIL_STAGES: Array<{ stage: MosaicLabStage | "prove"; label: string }> = [
  { stage: "retrieve", label: stageLabels.retrieve },
  { stage: "rank", label: stageLabels.rank },
  { stage: "reason", label: stageLabels.reason },
  { stage: "prove", label: "Prove" },
];

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

  /**
   * Condensed while stuck. Sticky under the site header, the full rail costs
   * every later screen its whole height, and on a 768px laptop the two together
   * took a quarter of the viewport. Once it sticks, the edit line and the
   * next-lab link fold away and the rest shares one row; both come back the
   * moment it scrolls free.
   *
   * Stuck is read from the rail itself. Observed against a root shrunk by the
   * header's height, it stays fully visible until the header clips its top
   * edge. A long rail clipped at the bottom of a short screen is not stuck,
   * and the root-bounds check is what tells the two apart.
   */
  const railRef = useRef<HTMLElement>(null);
  const [stuck, setStuck] = useState(false);
  useEffect(() => {
    const rail = railRef.current;
    if (!rail || typeof IntersectionObserver === "undefined") return;
    const topbar = Number.parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue("--topbar-height"),
    );
    const headerClip = Math.ceil(Number.isFinite(topbar) ? topbar : 0) + 1;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries.at(-1);
        if (!entry) return;
        const clippedAtTop =
          !entry.rootBounds ||
          entry.boundingClientRect.top <= entry.rootBounds.top + 1;
        setStuck(entry.intersectionRatio < 1 && clippedAtTop);
      },
      { rootMargin: `-${headerClip}px 0px 0px 0px`, threshold: 1 },
    );
    observer.observe(rail);
    return () => observer.disconnect();
  }, []);

  /**
   * A condensed rail is shorter, and a shorter box in the flow would move
   * everything under it up by the difference at the exact moment the reader
   * scrolls past. A matching negative bottom margin keeps the footprint the
   * size it had while expanded, so condensing changes nothing but the rail.
   */
  const expandedHeight = useRef(0);
  const [footprintFix, setFootprintFix] = useState(0);
  useEffect(() => {
    const rail = railRef.current;
    if (!rail || stuck || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      expandedHeight.current = rail.offsetHeight;
    });
    observer.observe(rail);
    return () => observer.disconnect();
  }, [stuck]);
  useLayoutEffect(() => {
    const rail = railRef.current;
    if (!rail) return;
    if (!stuck) {
      expandedHeight.current = rail.offsetHeight;
      setFootprintFix(0);
      return;
    }
    setFootprintFix(Math.max(0, expandedHeight.current - rail.offsetHeight));
  }, [stuck]);

  return (
    <nav
      aria-label="Lab rail"
      className={stuck ? "labs-rail is-stuck" : "labs-rail"}
      ref={railRef}
      style={footprintFix ? { marginBottom: -footprintFix } : undefined}
    >
      <div className="labs-rail-lab">
        <span className="labs-rail-kicker">
          Lab {labNumber} of {coreMosaicLabs.length}
        </span>
        <strong>{lab.title}</strong>
      </div>

      {/* The lab's own stage is marked rather than merely listed. All four are
          reachable from every lab -- a participant in Lab 2 still reads the
          Retrieve stage above their work -- but only one of them is the stage
          this lab changes, and nothing else on the rail says which. */}
      <ol aria-label="Lab stages" className="labs-rail-stages">
        {RAIL_STAGES.map((entry) => (
          <li key={entry.stage}>
            <a
              aria-current={entry.stage === lab.stage ? "step" : undefined}
              href={`#labs-stage-${entry.stage}`}
            >
              {entry.label}
            </a>
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
