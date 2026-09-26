import { describe, expect, it } from "vitest";
import { isLabRepaired } from "./labStateCopy";
import type { LabStateRecord } from "./types";

function state(
  sourceState: LabStateRecord["source_state"],
  databaseState: LabStateRecord["database_state"],
): Pick<LabStateRecord, "source_state" | "database_state"> {
  return { source_state: sourceState, database_state: databaseState };
}

describe("isLabRepaired", () => {
  it("requires both a repaired file and an applied database", () => {
    expect(isLabRepaired(state("solved", "applied"))).toBe(true);
    // Lab 3's seam lives in the API process; there is no SQL to apply.
    expect(isLabRepaired(state("solved", "not_applicable"))).toBe(true);
  });

  it("is not repaired while the file still holds the intentional fault", () => {
    expect(isLabRepaired(state("broken", "applied"))).toBe(false);
    expect(isLabRepaired(state("broken", "not_applicable"))).toBe(false);
  });

  it("is not repaired when the file is fixed but Aurora still holds the old function", () => {
    // The taught failure mode: editing a file without re-applying it to Aurora.
    // A bare `source_state === "solved"` check would read this as done.
    expect(isLabRepaired(state("solved", "stale"))).toBe(false);
  });

  it("never guesses when no state has been read", () => {
    expect(isLabRepaired(null)).toBe(false);
  });
});
