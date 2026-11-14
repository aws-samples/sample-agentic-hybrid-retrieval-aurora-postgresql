// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { coreMosaicLabs, labThreeRequiredQuestion } from "../../labMissions";
import { GRADE_SETUP_RUN } from "../../participantCommands";
import { Turn } from "./Turn";
import type { AskMosaicTurn } from "./types";

afterEach(cleanup);

const reason = coreMosaicLabs.find((mission) => mission.stage === "reason")!;
const SETUP = reason.query;
const FOLLOW_UP = reason.changed_requirement!.query;
const RUN_ID = "0349001c-9614-46e0-bbf7-0da60286c821";

function failed(question: string, errorCode = "stream_interrupted"): AskMosaicTurn {
  return {
    id: 1, question, response: null, completed: false, partial: null, streamed: "", stage: null,
    stageStartedAt: 0, executionPath: "full_retrieval", stageDetail: "",
    error: "The connection to the Retrieval agent closed before its answer arrived.",
    errorCode, errorRunId: RUN_ID, cancelled: false, loading: false, startedAt: 0,
  } as AskMosaicTurn;
}

function renderTurn(turn: AskMosaicTurn, onRun = vi.fn()) {
  render(<Turn
    turn={turn} isLatest imageByProductId={new Map()} highlightedProductId={null} builder={false}
    onRun={onRun} onEdit={() => {}} onHighlight={() => {}} onSelectProduct={() => {}}
    priorQuestions={[]} previousBestPickId={null}
  />);
  return onRun;
}

describe("labThreeRequiredQuestion", () => {
  it("knows both required questions as the server's same_request does", () => {
    expect(labThreeRequiredQuestion(SETUP)).toBe("setup");
    expect(labThreeRequiredQuestion(`  ${FOLLOW_UP.toUpperCase()} `)).toBe("follow_up");
    expect(labThreeRequiredQuestion(FOLLOW_UP.replace(/'/g, "’"))).toBe("follow_up");
    expect(labThreeRequiredQuestion("Which headphones are best for long calls?")).toBeNull();
    expect(labThreeRequiredQuestion("")).toBeNull();
  });
});

describe("a broken answer stream", () => {
  it.each([["setup", SETUP], ["100W", FOLLOW_UP]])(
    "on the %s question points to the saved runs, not a second turn",
    (_label, question) => {
      const onRun = renderTurn(failed(question));
      const card = screen.getByRole("status", { name: "Check your saved answers" });
      expect(card.textContent).toContain(GRADE_SETUP_RUN);
      expect(card.textContent).toContain(RUN_ID);
      expect(screen.queryByRole("button", { name: /Ask again/ })).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();
      expect(onRun).not.toHaveBeenCalled();
    },
  );

  it("on any other question keeps Ask again", () => {
    renderTurn(failed("Which headphones are best for long calls?"));
    expect(screen.queryByRole("status", { name: "Check your saved answers" })).toBeNull();
    expect(screen.getByRole("alert").textContent).toContain("Press Ask again to retry");
    expect(screen.getByRole("button", { name: /Ask again/ })).toBeTruthy();
  });

  it("on a required question that failed for another reason keeps the usual error", () => {
    renderTurn(failed(FOLLOW_UP, "agent_failed"));
    expect(screen.queryByRole("status", { name: "Check your saved answers" })).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});
