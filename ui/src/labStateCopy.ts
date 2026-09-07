import type { LabDatabaseState, LabSourceState, LabStateRecord } from "./types";

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

/** A file repair, its installed SQL, and a behavioral proof are separate facts. */
export function labStateCopy(
  state: Pick<LabStateRecord, "source_state" | "database_state"> | null,
): StateCopy[] {
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
