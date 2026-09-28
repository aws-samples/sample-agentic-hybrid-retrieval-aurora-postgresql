import type { LabDatabaseState, LabEntryState, LabSourceState, LabStateRecord } from "./types";

interface StateCopy {
  label: string;
  description: string;
}

const codeCopy: Record<LabSourceState, StateCopy> = {
  solved: {
    label: "Code repaired",
    description: "The exercise file contains the repair. Run completion proof to verify its behavior.",
  },
  broken: {
    label: "Code needs repair",
    description: "The exercise file still contains the intentional fault. Repair the marked code for this lab.",
  },
};

const databaseCopy: Record<LabDatabaseState, StateCopy> = {
  applied: {
    label: "SQL repair applied",
    description: "The lab's SQL repair is installed in Aurora. Run completion proof to verify the full retrieval behavior.",
  },
  stale: {
    label: "SQL repair not applied",
    description: "Aurora's database check has not found the SQL repair. Apply the repaired SQL, then run completion proof.",
  },
  not_applicable: {
    label: "No SQL update required",
    description: "This lab changes Python code in the application; there is no SQL repair to apply to Aurora.",
  },
};

/**
 * A lab that has not started has no participant state to report. Labs 2 and 3
 * ship repaired, so "Code repaired" there would credit work nobody did.
 */
const entryCopy: Record<Exclude<LabEntryState, "started">, StateCopy> = {
  not_started: {
    label: "Not started",
    description: "This lab's code is still the repaired reference the workshop ships. Run its start command in Code Editor to install the fault you will repair.",
  },
  incomplete: {
    label: "Start interrupted",
    description: "This lab's start stopped before it finished. Run its start command again; it finishes the missing step and keeps your edits.",
  },
};

type LabStateFacts = Pick<LabStateRecord, "source_state" | "database_state" | "entry_state">;

function unentered(state: LabStateFacts): Exclude<LabEntryState, "started"> | null {
  return state.entry_state === "not_started" || state.entry_state === "incomplete"
    ? state.entry_state
    : null;
}

/**
 * Whether a lab counts as repaired: the exercise file holds the fix, and
 * Aurora holds the SQL that backs it.
 *
 * The one place this two-part condition is decided. `CompletionProof` needs
 * the plain boolean to decide whether a failing check still has a source- or
 * database-side cause to explain. A lab whose file is repaired but whose database still holds
 * the old function is not repaired; that gap is exactly what a bare
 * `source_state === "solved"` check would hide, and it is a state the
 * workshop actually produces (editing a file without re-applying it).
 */
export function isLabRepaired(state: LabStateFacts | null): boolean {
  if (!state || unentered(state)) return false;
  return state.source_state === "solved" && state.database_state !== "stale";
}

/** A file repair, its installed SQL, and a behavioral proof are separate facts. */
export function labStateCopy(state: LabStateFacts | null): StateCopy[] {
  const entry = state ? unentered(state) : null;
  if (entry) return [entryCopy[entry]];
  return [
    state ? codeCopy[state.source_state] : {
      label: "Code not checked",
      description: "The exercise-file status is unavailable. No repair verdict has been established.",
    },
    state ? databaseCopy[state.database_state] : {
      label: "Aurora not checked",
      description: "The installed-SQL status is unavailable. No database verdict has been established.",
    },
  ];
}
