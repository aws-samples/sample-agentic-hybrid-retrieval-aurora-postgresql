import { describe, expect, it } from "vitest";
import { isLabRepaired, labNextStep, labStateCopy } from "./labStateCopy";
import { APPLY_SQL, DEPLOY_AGENT } from "./participantCommands";
import type { LabStateRecord } from "./types";

function state(
  sourceState: LabStateRecord["source_state"],
  databaseState: LabStateRecord["database_state"],
  entryState: LabStateRecord["entry_state"] = "started",
): Pick<LabStateRecord, "source_state" | "database_state" | "entry_state"> {
  return { source_state: sourceState, database_state: databaseState, entry_state: entryState };
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

describe("a lab that has not started", () => {
  // Labs 2 and 3 ship repaired and applied. Before their start that is the
  // workshop's reference, not the participant's repair.
  it("is not repaired, however its shipped code reads", () => {
    expect(isLabRepaired(state("solved", "applied", "not_started"))).toBe(false);
    expect(isLabRepaired(state("solved", "applied", "incomplete"))).toBe(false);
    expect(isLabRepaired(state("solved", "applied", null))).toBe(true);
  });

  it("reports one entry fact instead of the shipped code and SQL state", () => {
    expect(labStateCopy(state("solved", "applied", "not_started")).map((copy) => copy.label))
      .toEqual(["Not started"]);
    expect(labStateCopy(state("solved", "applied", "incomplete")).map((copy) => copy.label))
      .toEqual(["Start interrupted"]);
    expect(labStateCopy(state("solved", "applied")).map((copy) => copy.label))
      .toEqual(["Code repaired", "SQL repair applied"]);
  });
});

describe("a lab whose file still has the fault", () => {
  // "SQL repair applied" beside "Code needs repair" read as though the fix
  // were already in Aurora; it is the fault that is applied.
  it("says Aurora runs the unrepaired SQL, never that a repair is applied", () => {
    // A fresh account: the file and Aurora both hold the fault, which the
    // service reports as `stale` (no repair found in Aurora).
    expect(labStateCopy(state("broken", "stale")).map((copy) => copy.label))
      .toEqual(["Code needs repair", "Aurora runs the unrepaired SQL"]);
    // A reset that was not applied: Aurora kept the repair the file lost.
    expect(labStateCopy(state("broken", "applied")).map((copy) => copy.label))
      .toEqual(["Code needs repair", "Aurora differs from your file"]);
    expect(labStateCopy(state("solved", "stale")).map((copy) => copy.label))
      .toEqual(["Code repaired", "SQL repair not applied"]);
  });
});

describe("labNextStep", () => {
  it("never guesses before a state has been read", () => {
    expect(labNextStep(null)).toBeNull();
  });

  it("tells an unstarted or interrupted lab to run its start command", () => {
    expect(labNextStep(state("solved", "applied", "not_started"))).toMatch(/start command/);
    expect(labNextStep(state("solved", "applied", "incomplete"))).toMatch(/again/);
  });

  it("names the apply command for a SQL lab and the deploy command for Lab 3", () => {
    expect(labNextStep(state("broken", "applied"))).toContain(APPLY_SQL);
    expect(labNextStep(state("broken", "not_applicable"))).toContain(DEPLOY_AGENT);
  });

  it("points a repaired file at Aurora before proof", () => {
    expect(labNextStep(state("solved", "stale"))).toContain(APPLY_SQL);
    expect(labNextStep(state("solved", "applied"))).toMatch(/completion proof/);
  });

  it("does not tell a deployed Lab 3 to deploy it again", () => {
    const next = labNextStep(state("solved", "not_applicable"));
    expect(next).toContain(DEPLOY_AGENT);
    expect(next).toMatch(/if you have not since your last edit/i);
    expect(next).not.toMatch(/^Next: deploy it/);
  });
});
