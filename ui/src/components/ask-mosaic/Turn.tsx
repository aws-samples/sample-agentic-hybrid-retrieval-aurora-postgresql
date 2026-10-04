import { CircleStop, PencilLine, RotateCcw } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import type { AgentCitation, AgentPlanStep, AgentResponse, ProductSummary, ToolTraceStep } from "../../types";
import { DeclinedAnswer } from "../DeclinedAnswer";
import { MemoryReceipt } from "../AskMosaicMemory";
import { AgentSetupCard } from "./AgentSetupCard";
import { BuilderView } from "./BuilderView";
import { comparisonRows, unknowns, type ComparisonRow } from "./comparison";
import { boldRecommendationNames } from "./emphasis";
import type { RunData } from "./findings";
import { HowAnswered } from "./HowAnswered";
import { PickRow, TopPick } from "./Picks";
import { FollowUps } from "./ResultCards";
import { RunProgress } from "./RunProgress";
import { isSetupCardMessage } from "./setupMessage";
import { SourceList, StillUnknown } from "./SourceList";
import { useSoftReveal } from "./softReveal";
import { StreamedAnswer } from "./StreamedAnswer";
import { stagesFor, type AskMosaicTurn } from "./types";
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
  rows: ComparisonRow[];
  answerId: string;
  /** The first pick leads in a card, unless the last answer already led with it. */
  leadsWithCard: boolean;
  text: string;
  reveal: number;
  settled: boolean;
  declined: boolean;
}

function Picks({ picks, leadsWithCard, props }: { picks: ProductSummary[]; leadsWithCard: boolean; props: AnswerBodyProps }) {
  const shared = (product: ProductSummary) => ({
    product,
    index: picks.indexOf(product),
    rows: props.rows,
    citations: props.response.citations,
    answerId: props.answerId,
    imageSrc: props.imageByProductId.get(product.product_id),
    builder: props.builder,
    highlighted: props.highlightedProductId === product.product_id,
    onHighlight: props.onHighlight,
    onSelectProduct: props.onSelectProduct,
  });
  const rest = leadsWithCard ? picks.slice(1) : picks;
  return (
    <>
      {leadsWithCard && picks[0] ? <TopPick {...shared(picks[0])} /> : null}
      {props.settled && rest.length ? (
        <section className="ask-picks" aria-label="Other picks">
          <h4>{leadsWithCard ? "Other picks" : "Picks"}</h4>
          <ul>{rest.map((product) => <PickRow key={product.product_id} {...shared(product)} />)}</ul>
        </section>
      ) : null}
    </>
  );
}

function AnswerBody(props: AnswerBodyProps) {
  const { turn, response, run, declined, settled, builder, answerId, text, reveal } = props;
  const picks = declined ? [] : response.recommendations.slice(0, 3);
  return (
    <>
      {builder
        ? <BuilderView response={response} run={run} durationMs={turn.durationMs} />
        : <HowAnswered run={run} durationMs={turn.durationMs} />}
      {declined ? (
        <DeclinedAnswer answer={turn.streamed || response.answer} reason={response.decline_reason} className="ask-mosaic-declined" />
      ) : (
        <>
          {settled ? <h3 className="sr-only">Final recommendation</h3> : null}
          <Picks picks={picks} leadsWithCard={props.leadsWithCard} props={props} />
          <StreamedAnswer text={text} reveal={reveal} citations={response.citations} answerId={answerId} />
          {settled && response.citations.length ? (
            <>
              <SourceList citations={response.citations} products={response.recommendations} answerId={answerId} builder={builder} />
              <StillUnknown items={unknowns(picks, props.rows)} />
            </>
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
  const label = stagesFor(turn.executionPath).find((stage) => stage.id === presentedStage)?.running ?? "Working";

  return (
    <article className="ask-mosaic-turn">
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {turn.error ? "Ask Mosaic could not finish this request." : settled ? "Ask Mosaic recommendation complete." : `${label}. In progress.`}
      </p>
      <TurnQuestion turn={turn} isLatest={isLatest} onEdit={props.onEdit} onRun={props.onRun} />

      {!answerVisible && !needsSetup && (turn.loading || turn.stage || turn.cancelled || turn.error) ? (
        <RunProgress run={run} presentedStage={presentedStage} state={runState} stageStartedAt={turn.stageStartedAt} />
      ) : null}

      {turn.cancelled ? (
        <div className="ask-mosaic-cancelled" role="status">
          <span className="ask-mosaic-cancelled-heading">
            <CircleStop size={15} aria-hidden="true" />
            You stopped this request.
          </span>
          {turn.streamed
            ? <small>The partial answer and steps above are what Mosaic had found so far.</small>
            : <small>Ask again, or send a new request.</small>}
        </div>
      ) : null}

      {needsSetup ? (
        <AgentSetupCard detail={turn.error} />
      ) : turn.error ? (
        <div className="ask-mosaic-error" role="alert">
          <strong>Mosaic could not finish this request.</strong>
          <span>{turn.error}</span>
          <small>Press Ask again to retry. If it keeps failing, share this message with your facilitator.</small>
        </div>
      ) : null}

      <AnimatePresence initial={false}>
        {response && answerVisible && !turn.error ? (
          <motion.div
            className="ask-mosaic-answer"
            initial={{ opacity: 0, transform: "translateY(7px)" }}
            animate={{ opacity: 1, transform: "translateY(0)" }}
            exit={{ opacity: 0, transform: "translateY(4px)" }}
            transition={{ duration: reduceMotion ? 0 : 0.22, ease: [0.23, 1, 0.32, 1] }}
          >
            <AnswerBody
              {...props}
              response={response}
              run={run}
              rows={rows}
              answerId={answerId}
              leadsWithCard={Boolean(picks[0]) && picks[0].product_id !== previousBestPickId}
              text={declined ? "" : reveal.text}
              reveal={reveal.reveal}
              settled={settled}
              declined={declined}
            />
            {settled ? <MemoryReceipt memory={response.memory} /> : null}
            {settled && !declined && isLatest && !turn.loading ? (
              <FollowUps response={response} onRun={props.onRun} />
            ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </article>
  );
}
