import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { sourceFilters, useCatalogSource } from "../catalogSource";
import { coreMosaicLabs, workspaceRequests } from "../labMissions";
import type { SearchFilters } from "../types";
import { isSetupCardMessage } from "./ask-mosaic/setupMessage";
import type { AskMosaicTurn } from "./ask-mosaic/types";

function lastAnswered(turns: AskMosaicTurn[]): AskMosaicTurn | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    if (turns[index].completed && turns[index].response) return turns[index];
  }
  return null;
}

function failureCode(cause: unknown): string | undefined {
  const code = (cause as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : undefined;
}

/**
 * Owns the conversation shared by every Ask Mosaic drawer.
 *
 * The drawer is presentational. Keeping streaming events, follow-up
 * context, and cancellation here prevents drawers from drifting into
 * different assistants behind matching controls.
 */
// Lab 3 is the one starter a participant must run from this panel, so it leads;
// Array.prototype.sort is stable, so the others keep the manifest's order.
function isLabThreeRequest(request: { mission_id?: string }) {
  return coreMosaicLabs.some((mission) => mission.id === request.mission_id && mission.stage === "reason");
}

export function useAskMosaicConversation(
  filters: SearchFilters,
  /** Whether a request reads and writes memory; a function decides per question. */
  useMemory: boolean | ((question: string) => boolean) = false,
) {
  const { real } = useCatalogSource();
  const [turns, setTurns] = useState<AskMosaicTurn[]>([]);
  const requestVersion = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const sessionId = useRef<string | undefined>(undefined);
  const pending = turns.some((turn) => turn.loading);
  const answeredTurn = lastAnswered(turns);

  useEffect(() => () => {
    requestVersion.current += 1;
    requestController.current?.abort();
  }, []);

  function clear() {
    requestVersion.current += 1;
    requestController.current?.abort();
    requestController.current = null;
    sessionId.current = undefined;
    setTurns([]);
  }

  /**
   * Stop the turn in progress without discarding the conversation around it.
   *
   * Bumping the version first is what keeps this a clean stop rather than an
   * error: `run`'s own `.catch` and `.finally` already no-op once their version
   * is stale, so aborting after the bump can never overwrite the cancelled
   * state set here with an "AbortError" message. Whatever text, shortlist, or
   * trace had already arrived stays on screen; only the turn's own `loading`
   * and stage end.
   */
  function stop() {
    requestVersion.current += 1;
    requestController.current?.abort();
    requestController.current = null;
    setTurns((current) => {
      const last = current.length - 1;
      if (last < 0 || !current[last].loading) return current;
      return current.map((turn, index) => (
        index === last
          ? { ...turn, loading: false, cancelled: true, stage: null, stageDetail: "" }
          : turn
      ));
    });
  }

  async function run(question: string, requestFilters: SearchFilters = filters, contextKey?: string) {
    const trimmed = question.trim();
    if (trimmed.length < 2 || pending) return;
    const context = answeredTurn?.response?.recommendations.length && answeredTurn.response.outcome !== "declined"
      ? {
        previous_agent_run_id: answeredTurn.response.agent_run_id,
        previous_question: answeredTurn.question,
        recommendations: answeredTurn.response.recommendations
          .slice(0, 4)
          .map((product) => ({
            product_id: product.product_id,
            title: product.title,
            model: product.model,
          })),
      }
      : undefined;
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    const controller = new AbortController();
    requestController.current = controller;
    const startedAt = Date.now();
    setTurns((current) => [
      ...current,
      {
        id: version,
        question: trimmed,
        contextKey,
        response: null,
        completed: false,
        partial: null,
        streamed: "",
        stage: "understand",
        stageStartedAt: Date.now(),
        executionPath: context ? "focused_follow_up" : "full_retrieval",
        stageDetail:
          "Working out what you need and which catalog constraints that implies.",
        error: "",
        cancelled: false,
        loading: true,
        startedAt,
      },
    ]);
    const patch = (change: Partial<AskMosaicTurn>) => {
      setTurns((current) => current.map(
        (turn) => (turn.id === version ? { ...turn, ...change } : turn),
      ));
    };
    try {
      await api.agentStream(trimmed, sourceFilters(requestFilters, real), (event) => {
        if (version !== requestVersion.current) return;
        if (event.type === "stage") {
          setTurns((current) => current.map((turn) => (
            turn.id === version
              ? {
                ...turn,
                stage: event.id,
                stageStartedAt: turn.stage === event.id
                  ? turn.stageStartedAt
                  : Date.now(),
                executionPath: event.path,
                stageDetail: event.detail,
              }
              : turn
          )));
        } else if (event.type === "partial") {
          patch({ partial: event.partial });
        } else if (event.type === "answer_start") {
          patch({
            response: event.response,
            completed: false,
            stage: "answer",
            stageDetail:
              "Writing the recommendation from the products it found and the specs and reviews behind them.",
          });
        } else if (event.type === "answer_delta") {
          const { delta } = event;
          setTurns((current) => current.map(
            (turn) => (turn.id === version
              ? { ...turn, streamed: turn.streamed + delta }
              : turn),
          ));
        } else {
          sessionId.current = event.response.session_id ?? sessionId.current;
          patch({
            response: event.response,
            completed: true,
            durationMs: Date.now() - startedAt,
            streamed: event.response.answer,
            stage: null,
            stageDetail: "",
          });
        }
      }, context, {
        signal: controller.signal,
        useMemory: typeof useMemory === "function" ? useMemory(trimmed) : useMemory,
        sessionId: sessionId.current,
      });
    } catch (cause) {
      if (version !== requestVersion.current) return;
      // Cancellation is a normal terminal state, not a failure: `stop` and
      // `clear` bump the version before aborting, so this only fires for an
      // abort neither of them caused. Guarded anyway, so a signal aborted by
      // some future caller never surfaces as an "AbortError" toast.
      if (cause instanceof DOMException && cause.name === "AbortError") {
        patch({ completed: false, cancelled: true, stage: null, stageDetail: "" });
        return;
      }
      const message = cause instanceof Error ? cause.message : "Ask Mosaic is unavailable";
      const code = failureCode(cause);
      const needsSetup = code === "agent_setup" && isSetupCardMessage(message);
      patch({
        completed: false,
        stageDetail: needsSetup
          ? "This step needs your agent set up first. Follow the next step below."
          : "This step did not finish. Review the error below and retry.",
        error: message,
        errorCode: code,
      });
    } finally {
      if (version === requestVersion.current) patch({ loading: false });
      if (requestController.current === controller) {
        requestController.current = null;
      }
    }
  }

  // A brand or attribute gate would narrow every starter that merges with it.
  // Only a starter that names no filters of its own runs untouched by Shop.
  const narrowedByShop = Boolean(filters.brand) || Object.keys(filters.attributes ?? {}).length > 0;
  const starters = workspaceRequests(
    sourceFilters(filters, real),
    (value) => sourceFilters(value, real),
  ).filter((request) => !narrowedByShop || Object.keys(request.filters).length === 0)
    .sort((a, b) => Number(isLabThreeRequest(b)) - Number(isLabThreeRequest(a)));

  return {
    answeredTurn,
    clear,
    stop,
    suggestions: starters,
    pending,
    run,
    turns,
  };
}
