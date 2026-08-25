import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { RetrievalExample, SearchFilters } from "../types";
import type { AskMosaicTurn } from "./AskMosaic";

function lastAnswered(turns: AskMosaicTurn[]): AskMosaicTurn | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    if (turns[index].response) return turns[index];
  }
  return null;
}

/**
 * Owns the conversation shared by every Ask Mosaic drawer.
 *
 * The drawer is presentational. Keeping examples, streaming events, follow-up
 * context, and cancellation here prevents Discover and Shop from drifting into
 * different assistants behind matching controls.
 */
export function useAskMosaicConversation(filters: SearchFilters) {
  const [turns, setTurns] = useState<AskMosaicTurn[]>([]);
  const [examples, setExamples] = useState<RetrievalExample[]>([]);
  const requestVersion = useRef(0);
  const pending = turns.some((turn) => turn.loading);
  const answeredTurn = lastAnswered(turns);

  useEffect(() => {
    let active = true;
    api
      .examples()
      .then((nextExamples) => {
        if (active) setExamples(nextExamples);
      })
      .catch(() => {
        if (active) setExamples([]);
      });
    return () => {
      active = false;
    };
  }, []);

  function clear() {
    requestVersion.current += 1;
    setTurns([]);
  }

  async function run(question: string) {
    const trimmed = question.trim();
    if (trimmed.length < 2 || pending) return;
    const context = answeredTurn?.response
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
    setTurns((current) => [
      ...current,
      {
        id: version,
        question: trimmed,
        response: null,
        partial: null,
        streamed: "",
        stage: "understand",
        stageStartedAt: Date.now(),
        executionPath: context ? "focused_follow_up" : "full_retrieval",
        stageDetail:
          "Working out what you need and which catalog constraints that implies.",
        error: "",
        loading: true,
      },
    ]);
    const patch = (change: Partial<AskMosaicTurn>) => {
      setTurns((current) => current.map(
        (turn) => (turn.id === version ? { ...turn, ...change } : turn),
      ));
    };
    try {
      await api.agentStream(trimmed, filters, (event) => {
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
          patch({
            response: event.response,
            streamed: event.response.answer,
            stage: null,
            stageDetail: "",
          });
        }
      }, context);
    } catch (cause) {
      if (version !== requestVersion.current) return;
      patch({
        stage: null,
        stageDetail: "",
        error: cause instanceof Error ? cause.message : "Ask Mosaic is unavailable",
      });
    } finally {
      if (version === requestVersion.current) patch({ loading: false });
    }
  }

  return {
    answeredTurn,
    clear,
    examples,
    pending,
    run,
    turns,
  };
}
