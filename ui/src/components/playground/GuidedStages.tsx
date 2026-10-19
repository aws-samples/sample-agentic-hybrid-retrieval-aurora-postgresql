import { ArrowLeft, ArrowRight, ChevronDown } from "lucide-react";
import { useRef, type KeyboardEvent, type ReactNode } from "react";

export type StageId = "retrieve" | "rank" | "rerank" | "reason";
export type StageState = "idle" | "pending" | "active" | "complete" | "failed" | "blocked";

export interface GuidedStage {
  id: StageId;
  /** The stage's name, as the guides use it: Retrieve, Rank, Re-rank, Reason. */
  title: string;
  state: StageState;
  /** What happened at this stage, in one sentence. */
  heading: string;
  lede: string;
  /** The one thing to look at. */
  body: ReactNode;
  detailsLabel: string;
  details: ReactNode;
}

const SPOKEN: Record<StageState, string> = {
  idle: "", pending: "waiting", active: "working", complete: "done", failed: "stopped", blocked: "not reached",
};

/**
 * The run's four stages, one at a time. A row of steps shows where the reader
 * is and how each stage ended; the open stage shows one sentence and one visual,
 * and keeps its depth behind a single button. Back and Next walk the pipeline in
 * order, so a presenter can take a room through it at the room's pace.
 */
export function GuidedStages({ stages, active, onActive, expanded, onToggleDetails }: {
  stages: GuidedStage[];
  active: StageId;
  onActive: (id: StageId) => void;
  expanded: Record<StageId, boolean>;
  onToggleDetails: (id: StageId) => void;
}) {
  const tabs = useRef<HTMLDivElement>(null);
  const index = Math.max(0, stages.findIndex((stage) => stage.id === active));
  const stage = stages[index];
  const previous = stages[index - 1];
  const next = stages[index + 1];
  const go = (id: StageId, focus = false) => {
    onActive(id);
    if (focus) window.requestAnimationFrame(() => tabs.current?.querySelector<HTMLButtonElement>(`[data-stage="${id}"]`)?.focus());
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    go(stages[(index + step + stages.length) % stages.length].id, true);
  };
  return <section className="pg-guide" aria-label="How this run worked">
    <div className="pg-guide-steps" role="tablist" aria-label="Pipeline stages" ref={tabs} onKeyDown={onKeyDown}>
      {stages.map((item, position) => <button
        key={item.id}
        type="button"
        role="tab"
        id={`stage-tab-${item.id}`}
        data-stage={item.id}
        data-state={item.state}
        aria-selected={item.id === stage.id}
        aria-controls={`inspect-${item.id}`}
        aria-label={`${item.title}${SPOKEN[item.state] ? `: ${SPOKEN[item.state]}` : ""}`}
        tabIndex={item.id === stage.id ? 0 : -1}
        onClick={() => go(item.id)}
      >
        <span className="pg-guide-n" aria-hidden="true">{position + 1}</span>{item.title}
      </button>)}
    </div>
    <div className="pg-guide-panel" role="tabpanel" id={`inspect-${stage.id}`} aria-labelledby={`stage-tab-${stage.id}`} data-stage={stage.id} data-state={stage.state} key={stage.id}>
      <header>
        <h2>{stage.heading}</h2>
        <p>{stage.lede}</p>
      </header>
      <div className="pg-guide-body">{stage.body}</div>
      <button id={`inspect-${stage.id}-button`} type="button" className="pg-inspect" aria-expanded={expanded[stage.id]} aria-controls={`inspect-${stage.id}-details`} onClick={() => onToggleDetails(stage.id)}>
        {stage.detailsLabel}<ChevronDown size={16} aria-hidden="true" />
      </button>
      <div id={`inspect-${stage.id}-details`} className="pg-section-details" role="region" aria-labelledby={`inspect-${stage.id}-button`} hidden={!expanded[stage.id]}>
        {expanded[stage.id] ? stage.details : null}
      </div>
      <footer className="pg-guide-nav">
        {previous ? <button type="button" onClick={() => go(previous.id, true)}><ArrowLeft size={16} aria-hidden="true" />{previous.title}</button> : <span />}
        <span className="pg-guide-count">{index + 1} of {stages.length}</span>
        {next ? <button type="button" className="pg-guide-next" onClick={() => go(next.id, true)}>Next: {next.title}<ArrowRight size={16} aria-hidden="true" /></button> : <span />}
      </footer>
    </div>
  </section>;
}
