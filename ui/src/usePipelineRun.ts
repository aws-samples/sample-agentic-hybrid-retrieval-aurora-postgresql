import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { AgentPartial, AgentResponse, SearchFilters, SearchResponse, ToolTraceStep } from "./types";

export interface PipelineReceipt {
  id: string;
  response?: SearchResponse;
  error?: string;
}

export type PipelinePhase = "retrieve" | "rank" | "reason";

/** Follow only the search receipts emitted by this agent turn. */
export function usePipelineRun(requestKey: string, carriedEvent: string | null) {
  const [receipts, setReceipts] = useState<PipelineReceipt[]>([]);
  const [trace, setTrace] = useState<ToolTraceStep[]>([]);
  const [answer, setAnswer] = useState<AgentResponse | null>(null);
  const [partial, setPartial] = useState<AgentPartial | null>(null);
  const [streamed, setStreamed] = useState("");
  const [completed, setCompleted] = useState(false);
  const [running, setRunning] = useState(false);
  const [reading, setReading] = useState(false);
  const [status, setStatus] = useState("");
  const [phase, setPhase] = useState<PipelinePhase | null>(null);
  const [error, setError] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [savedResponse, setSavedResponse] = useState<SearchResponse | null>(null);
  const [started, setStarted] = useState(false);
  const [replay, setReplay] = useState(0);
  const version = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    const current = ++version.current;
    controller.current?.abort();
    inFlight.current = false;
    setReceipts([]);
    setTrace([]);
    setAnswer(null);
    setPartial(null);
    setStreamed("");
    setCompleted(false);
    setRunId(null);
    setSavedResponse(null);
    setStarted(false);
    setError("");
    setStatus("");
    setPhase(null);
    setRunning(false);
    setReading(Boolean(carriedEvent));
    if (carriedEvent) {
      setReceipts([{ id: carriedEvent }]);
      void api.retrievalEventResponse(carriedEvent).then((response) => {
        if (current === version.current) {
          setReceipts([{ id: carriedEvent, response }]);
          setSavedResponse(response);
        }
      }).catch((cause: unknown) => {
        if (current === version.current) setReceipts([{
          id: carriedEvent,
          error: cause instanceof Error ? cause.message : "Could not read this search record.",
        }]);
      }).finally(() => {
        if (current === version.current) setReading(false);
      });
    }
    return () => {
      version.current += 1;
      controller.current?.abort();
    };
  }, [requestKey, carriedEvent, replay]);

  async function play(question: string, filters: SearchFilters) {
    if (inFlight.current) return;
    inFlight.current = true;
    const current = ++version.current;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setReading(false);
    setRunning(true);
    setStarted(true);
    setError("");
    setAnswer(null);
    setPartial(null);
    setStreamed("");
    setCompleted(false);
    setTrace([]);
    setReceipts([]);
    setRunId(null);
    setStatus("Starting Alex’s request…");
    setPhase("retrieve");
    const reads = new Map<string, Promise<void>>();

    function followTrace(steps: ToolTraceStep[]) {
      setTrace(steps);
      for (const step of steps) {
        const id = step.retrieval_run_id;
        if (step.tool !== "search_products" || !id || reads.has(id)) continue;
        setReceipts((items) => [...items, { id }]);
        const read = api.retrievalEventResponse(id).then((response) => {
          if (current !== version.current) return;
          setReceipts((items) => items.map((item) => item.id === id ? { id, response } : item));
        }).catch((cause: unknown) => {
          if (current !== version.current) return;
          const message = cause instanceof Error ? cause.message : "Could not read this search record.";
          setReceipts((items) => items.map((item) => item.id === id ? { id, error: message } : item));
        });
        reads.set(id, read);
      }
    }

    try {
      await api.agentStream(question, filters, (event) => {
        if (current !== version.current) return;
        if (event.type === "stage") {
          const next = event.id === "answer" ? "reason" : event.id === "rank" ? "rank" : "retrieve";
          setPhase(next);
          setStatus(next === "retrieve" ? "Finding matching products…" : next === "rank" ? "Checking the ranked matches…" : "Preparing Mosaic’s recommendation…");
        }
        if (event.type === "partial") {
          setPartial(event.partial);
          followTrace(event.partial.trace);
        }
        if (event.type === "answer_start") {
          setPhase("reason");
          followTrace(event.response.trace);
          setAnswer(event.response);
          setRunId(event.response.agent_run_id);
          setStatus("Revealing Mosaic’s answer…");
        }
        if (event.type === "answer_delta") setStreamed((text) => text + event.delta);
        if (event.type === "complete") {
          setPhase("reason");
          followTrace(event.response.trace);
          setAnswer(event.response);
          setRunId(event.response.agent_run_id);
          setStreamed(event.response.answer);
          setCompleted(true);
          setStatus(event.response.outcome === "declined" ? "Finished without a recommendation." : "Pipeline complete.");
        }
      }, undefined, { signal: abort.signal });
    } catch (cause: unknown) {
      if (current !== version.current) return;
      setAnswer(null);
      setStreamed("");
      setCompleted(false);
      setError(cause instanceof Error ? cause.message : "The pipeline could not finish. Try Play pipeline again.");
      if (cause instanceof ApiError) setRunId(cause.agentRunId ?? null);
      setStatus("Pipeline stopped. The available records are shown below.");
    } finally {
      await Promise.all(reads.values());
      if (current === version.current) {
        setRunning(false);
        inFlight.current = false;
      }
    }
  }

  function restoreSavedSearch() {
    if (carriedEvent && !inFlight.current) setReplay((value) => value + 1);
  }

  return { receipts, trace, answer, partial, streamed, completed, running, reading, status, phase, error, runId, savedResponse, started, play, restoreSavedSearch };
}
