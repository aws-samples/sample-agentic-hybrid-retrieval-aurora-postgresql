import { CircleStop, PencilLine, RotateCcw } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type RefObject } from "react";
import type { AgentCitation, AgentPlanStep, AgentResponse, ProductSummary, ToolTraceStep } from "../../types";
import { AgentNoticeNote } from "../AgentNoticeNote";
import { DeclinedAnswer } from "../DeclinedAnswer";
import { MemoryReceipt } from "../AskMosaicMemory";
import { AgentSetupCard } from "./AgentSetupCard";
import { BuilderView } from "./BuilderView";
import { comparisonRows, type ComparisonRow } from "./comparison";
import { boldRecommendationNames } from "./emphasis";
import { reportedDuration, type RunData } from "./findings";
import { HowAnswered } from "./HowAnswered";
import { PickRow, TopPick } from "./Picks";
import { FollowUps } from "./ResultCards";
import { RunProgress } from "./RunProgress";
import { isSetupCardMessage } from "./setupMessage";
import { SourceList } from "./SourceList";
import { useSoftReveal } from "./softReveal";
import { StreamedAnswer } from "./StreamedAnswer";
import type { AskMosaicTurn } from "./types";
import { useProgressiveStage } from "./useProgressiveStage";

export interface TurnProps {
  turn: AskMosaicTurn;
  isLatest: boolean;
  imageByProductId: Map<number, string>;
  highlightedProductId: number | null;
  /** Builder view is page-wide, so every turn reads the one switch. */
  builder: boolean;
  onRun: (query: string) => void;
  onEdit: (query: string) => void;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
  /** Earlier questions, oldest first: a follow-up's requirements build on them. */
  priorQuestions: string[];
  /** The previous answer's first pick; the same pick is not shown twice in a row. */
  previousBestPickId: number | null;
  /** Keeps a newly presented phase in view inside the scrolling panel. */
  onStageProgress?: () => void;
  /** Fires as the reveal advances so the thread can keep the writing line in view. */
  onRevealProgress?: () => void;
}

/**
 * The answer appears once the run has reached its last phase, after a short
 * beat when the stream outruns the progress, and at once when nothing is paced.
 */
function useAnswerVisible(
  response: AgentResponse | null,
  turn: AskMosaicTurn,
  atAnswerStage: boolean,
  instant: boolean,
) {
  const [visible, setVisible] = useState(() => Boolean(response && turn.completed && !turn.error));
  useEffect(() => {
    if (!response || !atAnswerStage || turn.error) {
      setVisible(false);
      return undefined;
    }
    if (instant) {
      setVisible(true);
      return undefined;
    }
    const timer = window.setTimeout(() => setVisible(true), 180);
    return () => window.clearTimeout(timer);
  }, [atAnswerStage, instant, response, turn.error]);
  return visible;
}

/**
 * What the single status line says once the run is no longer working. Empty
 * while it works, because the progress line owns the phase announcements and a
 * second live region would read the same phase twice.
 */
function finishedAnnouncement(error: string, settled: boolean, declined: boolean): string {
  if (error) return "The Retrieval agent could not finish this request.";
  if (!settled) return "";
  return declined
    ? "The Retrieval agent declined to recommend a product."
    : "The Retrieval agent finished its recommendation.";
}

/**
 * Keeps citation chips from leading nowhere. Until the source list is on
 * screen (still streaming, or stopped part way) a chip would link to a source
 * that is not there, so it stops being a link: the click is swallowed and the
 * chip leaves the tab order. The shared `StreamedAnswer` still draws it.
 */
function useInertCitations(ref: RefObject<HTMLElement | null>, inert: boolean, revealed: string) {
  useEffect(() => {
    const chips = ref.current?.querySelectorAll<HTMLAnchorElement>("a.ask-answer-cite") ?? [];
    for (const chip of chips) {
      if (inert) {
        chip.setAttribute("aria-disabled", "true");
        chip.tabIndex = -1;
      } else {
        chip.removeAttribute("aria-disabled");
        chip.removeAttribute("tabindex");
      }
    }
  }, [ref, inert, revealed]);
}

/** The nth block to arrive once the reveal has finished, staggered by the stylesheet. */
const arrival = (order: number) => ({ "--i": order }) as CSSProperties;

/** A request longer than this is shown in five lines until the reader opens it. */
const LONG_QUESTION = 280;

function TurnQuestion({ turn, isLatest, onEdit, onRun }: Pick<TurnProps, "turn" | "isLatest" | "onEdit" | "onRun">) {
  const long = turn.question.length > LONG_QUESTION;
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="ask-mosaic-ask">
      <p className="ask-mosaic-bubble">
        <span className="sr-only">You asked</span>
        <span data-clamped={long && !expanded ? "" : undefined}>{turn.question}</span>
      </p>
      <span className="ask-mosaic-request-actions">
        {long ? (
          <button type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
            {expanded ? "Show less" : "Show all"}
          </button>
        ) : null}
        {isLatest && !turn.loading ? (
          <>
            <button className="ask-mosaic-edit-request" type="button" onClick={() => onEdit(turn.question)}>
              <PencilLine size={13} aria-hidden="true" />
              Edit request
            </button>
            <button className="ask-mosaic-ask-again" type="button" onClick={() => onRun(turn.question)}>
              <RotateCcw size={13} aria-hidden="true" />
              Ask again
            </button>
          </>
        ) : null}
      </span>
    </div>
  );
}

interface AnswerBodyProps extends Pick<
  TurnProps,
  "turn" | "isLatest" | "imageByProductId" | "highlightedProductId" | "builder" | "onRun" | "onHighlight" | "onSelectProduct"
> {
  response: AgentResponse;
  run: RunData;
  /** Measured send-to-finish time, absent when the turn was restored or replayed. */
  durationMs?: number;
  rows: ComparisonRow[];
  answerId: string;
  /** The first pick leads in a card, unless the last answer already led with it. */
  leadsWithCard: boolean;
  text: string;
  /** The whole answer so far, unrevealed, which citations are matched against. */
  answerText: string;
  /** Where each revealed chunk of `text` starts; empty when the answer was never paced. */
  chunks: readonly number[];
  settled: boolean;
  declined: boolean;
}

function pickProps(product: ProductSummary, picks: ProductSummary[], props: AnswerBodyProps) {
  return {
    product,
    index: picks.indexOf(product),
    rows: props.rows,
    citations: props.response.citations,
    answer: props.answerText,
    answerId: props.answerId,
    imageSrc: props.imageByProductId.get(product.product_id),
    builder: props.builder,
    highlighted: props.highlightedProductId === product.product_id,
    onHighlight: props.onHighlight,
    onSelectProduct: props.onSelectProduct,
  };
}

/**
 * The picks after the lead card. They wait below the prose until it has been
 * read out, so their arrival never pushes the sentence being read down the panel.
 */
function OtherPicks({ picks, props }: { picks: ProductSummary[]; props: AnswerBodyProps }) {
  const rest = props.leadsWithCard ? picks.slice(1) : picks;
  if (!props.settled || !rest.length) return null;
  return (
    <section className="ask-picks ask-arrive" style={arrival(0)} aria-label="Other picks">
      <h4>{props.leadsWithCard ? "Other picks" : "Picks"}</h4>
      <ul>{rest.map((product) => <PickRow key={product.product_id} {...pickProps(product, picks, props)} />)}</ul>
    </section>
  );
}

function AnswerBody(props: AnswerBodyProps) {
  const { turn, response, run, declined, settled, builder, answerId, text, chunks } = props;
  const picks = declined ? [] : response.recommendations.slice(0, 3);
  return (
    <>
      {declined ? (
        <DeclinedAnswer answer={turn.streamed || response.answer} reason={response.decline_reason} className="ask-mosaic-declined" />
      ) : (
        <>
          {settled ? <h3 className="sr-only">Final recommendation</h3> : null}
          {props.leadsWithCard && picks[0] ? <TopPick {...pickProps(picks[0], picks, props)} /> : null}
          <StreamedAnswer text={text} chunks={chunks} citations={response.citations} answerId={answerId} />
          <OtherPicks picks={picks} props={props} />
          {settled && response.citations.length ? (
            <div className="ask-arrive" style={arrival(1)}>
              <SourceList citations={response.citations} products={response.recommendations} answer={props.answerText} answerId={answerId} builder={builder} />
            </div>
          ) : null}
          {settled && !response.citations.length ? (
            <p className="ask-mosaic-uncited-note">
              No product record backs this answer, so read it as a
              suggestion rather than a checked recommendation. Ask again,
              or add a detail such as a budget or a category.
            </p>
          ) : null}
        </>
      )}
      {settled ? (
        <div className="ask-arrive" style={arrival(2)}>
        <HowAnswered run={run} durationMs={props.durationMs} declined={declined} builder={builder}>
          {builder ? <BuilderView response={response} run={run} durationMs={props.durationMs} /> : undefined}
        </HowAnswered>
        </div>
      ) : null}
    </>
  );
}

/**
 * One exchange, end to end: the question, the run's progress, and the cited
 * answer once it arrives.
 *
 * This owns the state transitions between a run in progress, an answer being
 * written, a settled answer, and a declined, stopped or failed turn. The pieces
 * it composes each take only the props they draw.
 */
export function Turn(props: TurnProps) {
  const { turn, isLatest, priorQuestions, previousBestPickId, onStageProgress, onRevealProgress } = props;
  const response = turn.response;
  const reduceMotion = useReducedMotion();
  const [startedLive] = useState(turn.loading);
  const instant = Boolean(reduceMotion || !startedLive || turn.error);
  const actualStage = response ? "answer" : turn.stage;
  const presentedStage = useProgressiveStage(turn.executionPath, actualStage, instant);
  const answerVisible = useAnswerVisible(response, turn, presentedStage === "answer", instant);
  const declined = response?.outcome === "declined";
  const emphasized = boldRecommendationNames(turn.streamed || response?.answer || "", response?.recommendations ?? []);
  const reveal = useSoftReveal(emphasized, turn.loading, answerVisible && !declined, reduceMotion ?? false);
  const settled = turn.completed && (declined || reveal.done);

  useEffect(() => { onRevealProgress?.(); }, [reveal.text.length, onRevealProgress]);
  useEffect(() => { onStageProgress?.(); }, [answerVisible, onStageProgress, presentedStage]);

  // Whichever retrieval has landed: the finished response supersedes the partial.
  const plan: AgentPlanStep[] = response?.plan ?? turn.partial?.plan ?? [];
  const trace: ToolTraceStep[] = response?.trace ?? turn.partial?.trace ?? [];
  const citations: AgentCitation[] = response?.citations ?? [];
  const run: RunData = { path: turn.executionPath, plan, trace, citations };
  const questions = useMemo(() => [...priorQuestions, turn.question], [priorQuestions, turn.question]);
  const picks = useMemo(
    () => (response && !declined ? response.recommendations.slice(0, 3) : []),
    [response, declined],
  );
  const rows = useMemo(() => comparisonRows(picks, citations, questions), [picks, citations, questions]);
  const answerId = `ask-answer-${turn.id}`;
  const needsSetup = Boolean(turn.error && turn.errorCode === "agent_setup" && isSetupCardMessage(turn.error));
  const runState = turn.error ? "failed" : turn.cancelled ? "stopped" : "working";
  const sourcesReady = settled && !declined && citations.length > 0;
  const answerRef = useRef<HTMLDivElement | null>(null);
  useInertCitations(answerRef, !sourcesReady, reveal.text);

  return (
    <article className="ask-mosaic-turn">
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {finishedAnnouncement(turn.error, settled, declined)}
      </p>
      <TurnQuestion turn={turn} isLatest={isLatest} onEdit={props.onEdit} onRun={props.onRun} />

      {turn.notice ? <AgentNoticeNote notice={turn.notice} /> : null}

      {!needsSetup && (answerVisible || turn.loading || turn.stage || turn.cancelled || turn.error) ? (
        <RunProgress
          run={run}
          presentedStage={presentedStage}
          state={answerVisible && !turn.error ? "done" : runState}
        />
      ) : null}

      {turn.cancelled ? (
        <div className="ask-mosaic-cancelled" role="status">
          <span className="ask-mosaic-cancelled-heading">
            <CircleStop size={15} aria-hidden="true" />
            You stopped this request.
          </span>
          {turn.streamed
            ? <small>The partial answer and steps above are what the Retrieval agent had found so far.</small>
            : <small>Ask again, or send a new request.</small>}
        </div>
      ) : null}

      {needsSetup ? (
        <AgentSetupCard detail={turn.error} />
      ) : turn.error ? (
        <div className="ask-mosaic-error" role="alert">
          <strong>The Retrieval agent could not finish this request.</strong>
          <span>{turn.error}</span>
          <small>Press Ask again to retry. If it keeps failing, share this message with your facilitator.</small>
        </div>
      ) : null}

      <AnimatePresence initial={false}>
        {response && answerVisible && !turn.error ? (
          <motion.div
            ref={answerRef}
            className="ask-mosaic-answer"
            data-sources={sourcesReady ? "ready" : "pending"}
            onClickCapture={(event) => {
              if (sourcesReady || !(event.target instanceof Element)) return;
              if (!event.target.closest("a.ask-answer-cite")) return;
              event.preventDefault();
              event.stopPropagation();
            }}
            initial={{ opacity: 0, transform: "translateY(7px)" }}
            animate={{ opacity: 1, transform: "translateY(0)" }}
            exit={{ opacity: 0, transform: "translateY(4px)" }}
            transition={{ duration: reduceMotion ? 0 : 0.22, ease: [0.23, 1, 0.32, 1] }}
          >
            <AnswerBody
              {...props}
              response={response}
              run={run}
              durationMs={reportedDuration(turn.durationMs, trace)}
              rows={rows}
              answerId={answerId}
              leadsWithCard={Boolean(picks[0]) && picks[0].product_id !== previousBestPickId}
              text={declined ? "" : reveal.text}
              answerText={turn.streamed || response.answer}
              chunks={reveal.chunks}
              settled={settled}
              declined={declined}
            />
            {settled ? <MemoryReceipt memory={response.memory} /> : null}
            {settled && !declined && isLatest && !turn.loading ? (
              <div className="ask-arrive" style={arrival(3)}>
                <FollowUps response={response} onRun={props.onRun} />
              </div>
            ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </article>
  );
}
