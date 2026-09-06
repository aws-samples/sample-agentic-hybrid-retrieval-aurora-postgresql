// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearPinnedBaseline,
  readPinnedBaseline,
  writePinnedBaseline,
} from "./baselineStore";

describe("baselineStore", () => {
  afterEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("returns the run pinned for one mission and nothing for the others", () => {
    writePinnedBaseline("lab-1", "event-one");

    expect(readPinnedBaseline("lab-1")).toBe("event-one");
    expect(readPinnedBaseline("lab-2")).toBeNull();
  });

  it("keeps each mission's pin when another mission pins its own", () => {
    // Switching missions must not evict the pin belonging to the one being
    // left: the participant returns to it, and its "before" is still the run
    // that mission is measured against. A single slot lost that on every
    // switch, which is why the store is keyed per mission.
    writePinnedBaseline("lab-1", "event-one");
    writePinnedBaseline("lab-2", "event-two");

    expect(readPinnedBaseline("lab-1")).toBe("event-one");
    expect(readPinnedBaseline("lab-2")).toBe("event-two");
  });

  it("replaces a mission's pin when that mission pins again", () => {
    writePinnedBaseline("lab-1", "event-one");
    writePinnedBaseline("lab-1", "event-two");

    expect(readPinnedBaseline("lab-1")).toBe("event-two");
  });

  it("clears one mission's pin without touching the rest", () => {
    writePinnedBaseline("lab-1", "event-one");
    writePinnedBaseline("lab-2", "event-two");

    clearPinnedBaseline("lab-1");

    expect(readPinnedBaseline("lab-1")).toBeNull();
    expect(readPinnedBaseline("lab-2")).toBe("event-two");
  });

  it("reports nothing pinned when the stored value is not a pin table", () => {
    // Anything but this module could have written the key -- an older build, a
    // hand-edited devtools value. Parsed defensively so a malformed entry reads
    // as "nothing pinned" rather than throwing on the way into the page.
    window.sessionStorage.setItem("mosaic.playground.baseline", "not json");
    expect(readPinnedBaseline("lab-1")).toBeNull();

    window.sessionStorage.setItem("mosaic.playground.baseline", '["lab-1"]');
    expect(readPinnedBaseline("lab-1")).toBeNull();

    window.sessionStorage.setItem("mosaic.playground.baseline", '{"lab-1":7}');
    expect(readPinnedBaseline("lab-1")).toBeNull();
  });

  it("degrades to no pin when the browser refuses to store anything", () => {
    // A browser with site data blocked throws on the access itself. The
    // Playground has to keep running searches without one: losing the pin
    // across a reload is the behaviour that existed before this module, and it
    // is not a reason to fail the page.
    const getItem = vi.spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new DOMException("denied");
      });
    const setItem = vi.spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("denied");
      });

    expect(() => writePinnedBaseline("lab-1", "event-one")).not.toThrow();
    expect(readPinnedBaseline("lab-1")).toBeNull();
    expect(() => clearPinnedBaseline("lab-1")).not.toThrow();
    expect(getItem).toHaveBeenCalled();
    expect(setItem).toHaveBeenCalled();
  });
});
