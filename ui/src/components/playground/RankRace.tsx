import { useReducedMotion } from "motion/react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { armLabel, armPoolKey } from "../../retrievalLanguage";
import type { ProductSummary, SearchResponse } from "../../types";
import { pickName } from "../ask-mosaic/comparison";

export type RaceStepKey = "fts" | "fuzzy" | "semantic" | "combined" | "final";

interface RaceStep {
  key: RaceStepKey;
  label: string;
  rank: (product: ProductSummary) => number | null;
  score: (product: ProductSummary) => number | null;
}

/** Each search on its own, then the order Aurora combined, then the reranked order. */
export const RACE_STEPS: RaceStep[] = [
  { key: "fts", label: armLabel.fts, rank: (p) => p.signals?.fts.rank ?? null, score: (p) => p.signals?.fts.raw_score ?? null },
  { key: "fuzzy", label: armLabel.fuzzy, rank: (p) => p.signals?.fuzzy.rank ?? null, score: (p) => p.signals?.fuzzy.raw_score ?? null },
  { key: "semantic", label: armLabel.semantic, rank: (p) => p.signals?.semantic.rank ?? null, score: (p) => p.signals?.semantic.raw_score ?? null },
  { key: "combined", label: "Combined (RRF)", rank: (p) => p.signals?.pre_rerank_rank ?? null, score: (p) => p.signals?.pre_rerank_score ?? null },
  { key: "final", label: "Reranked", rank: (p) => p.signals?.final_rank ?? null, score: (p) => p.signals?.rerank_score ?? null },
];

/** Rows on screen at once; a followed product beyond them is pinned underneath. */
export const RACE_ROWS = 8;
const ROWS = RACE_ROWS;
const ROW_HEIGHT = 56;
/** A pinned row sits a little apart, so it reads as "further down", not as the ninth. */
const PINNED_GAP = 18;
/** Entering rows rise from this far below their slot. */
const ENTER_OFFSET = 18;
/** Critically damped, settling in about 0.42 s. */
const OMEGA = (2 * Math.PI) / 0.42;
const REPLAY_MS = 1500;

interface Spring { value: number; velocity: number; target: number }
const spring = (value: number): Spring => ({ value, velocity: 0, target: value });

/** One step of a critically damped spring; false once it has come to rest. */
export function advance(state: Spring, seconds: number): boolean {
  const acceleration = -OMEGA * OMEGA * (state.value - state.target) - 2 * OMEGA * state.velocity;
  state.velocity += acceleration * seconds;
  state.value += state.velocity * seconds;
  if (Math.abs(state.value - state.target) < 0.001 && Math.abs(state.velocity) < 0.001) {
    state.value = state.target;
    state.velocity = 0;
    return false;
  }
  return true;
}

interface RowMotion { y: Spring; opacity: Spring; width: Spring }

interface RowContent {
  productId: number;
  name: string;
  rank: number;
  width: number;
  move: { text: string; direction: "up" | "down" | "same" } | null;
  /** The final order's first product. */
  top: boolean;
  /** Among the products the search returned; a shortlist product below them is shown faded. */
  onPage: boolean;
}

interface Slot { content: RowContent; slot: number }

/** The step's rows in its order, its window, and the followed product pinned when outside it. */
export function raceRows(
  products: ProductSummary[], step: RaceStep, followId: number | null, shownIds?: ReadonlySet<number>,
): Slot[] {
  const ranked = products
    .map((product) => ({ product, rank: step.rank(product), score: step.score(product) }))
    .filter((row): row is { product: ProductSummary; rank: number; score: number | null } => row.rank != null)
    .sort((a, b) => a.rank - b.rank);
  const shown = ranked.slice(0, ROWS);
  const followed = ranked.find((row) => row.product.product_id === followId);
  const pinned = followed && !shown.includes(followed) ? followed : null;
  const best = Math.max(0, ...[...shown, ...(pinned ? [pinned] : [])].map((row) => row.score ?? 0));
  const content = ({ product, rank, score }: (typeof ranked)[number]): RowContent => {
    const combined = product.signals?.pre_rerank_rank;
    const moved = step.key === "final" && combined != null ? combined - rank : null;
    return {
      productId: product.product_id,
      name: pickName(product),
      rank,
      width: best > 0 && score != null ? Math.max(0, score) / best : 0,
      top: step.key === "final" && rank === 1,
      onPage: shownIds?.has(product.product_id) ?? true,
      move: moved == null ? null
        : moved === 0 ? { text: "same", direction: "same" }
          : { text: `${moved > 0 ? "▲" : "▼"} ${Math.abs(moved)}`, direction: moved > 0 ? "up" : "down" },
    };
  };
  return [
    ...shown.map((row, index) => ({ content: content(row), slot: index })),
    ...(pinned ? [{ content: content(pinned), slot: shown.length }] : []),
  ];
}

const slotY = (slot: number, pinned: boolean) => slot * ROW_HEIGHT + (pinned ? PINNED_GAP : 0);

/** Searches are blue, Aurora's combined order orange, the reranked final order green. */
const stepAccent = (key: RaceStepKey) => key === "final" ? "done" : key === "combined" ? "rank" : "retrieve";

/**
 * The followed product's path through every step, as one line of positions:
 * where each search ranked it, where Aurora combined it, where it ended. The
 * step on screen is lit; choosing a node shows that step.
 */
function Journey({ steps, product, current, onPick }: {
  steps: RaceStep[];
  product: ProductSummary;
  current: RaceStepKey;
  onPick: (key: RaceStepKey) => void;
}) {
  return <>
    <p className="pg-journey-name">{pickName(product)}</p>
    <ol className="pg-journey" style={{ "--steps": steps.length } as CSSProperties} aria-label={`${pickName(product)} at each step`}>
      {steps.map((step, index) => {
        const rank = step.rank(product);
        // A step the race has not reached keeps its colour until it gets there.
        const ahead = index > steps.findIndex((item) => item.key === current);
        return <li key={step.key} data-current={step.key === current || undefined} data-ahead={ahead || undefined} data-found={rank != null || undefined} data-accent={stepAccent(step.key)}>
          <button type="button" onClick={() => onPick(step.key)} aria-label={`${step.label}: ${rank == null ? "not found" : `#${rank}`}`}>
            <b>{rank == null ? "—" : `#${rank}`}</b>
            <small>{step.label}</small>
          </button>
        </li>;
      })}
    </ol>
  </>;
}

/**
 * What this step is, in a sentence, then where the followed product stands. A
 * wanted product the search did not return is named as missing: the race only
 * holds the returned products, so it cannot say where else that product went.
 */
export function raceCaption(step: RaceStep, products: ProductSummary[], response: SearchResponse, follow: ProductSummary | undefined, missing?: string) {
  const k = response.diagnostics?.retrieval_profile?.rrf_k;
  const pool = response.diagnostics?.candidate_counts?.fused_pool;
  const what: Record<RaceStepKey, string> = {
    fts: "Full-text search ranks listings that contain the request’s words.",
    fuzzy: "Fuzzy matching ranks listings whose names and IDs share letter sequences with the request, so a typo still matches.",
    semantic: "Semantic search ranks listings by how close their meaning is to the request’s.",
    combined: `Aurora combines the three lists: each search adds 1 / (${k ?? "k"} + its rank), and a search that missed a product adds nothing.`,
    final: response.diagnostics?.rerank_status === "applied"
      ? `The reranker read the request with each of the ${pool ?? ""} combined candidates. It can reorder them, but cannot add one.`.replace("  ", " ")
      : "Reranking did not run for this search, so the final order is the combined order.",
  };
  const found = foundLine(step, response);
  const lead = found ? `${what[step.key]} ${found}` : what[step.key];
  if (missing) return `${lead} The ${missing} is not among the ${response.results.length} products this search returned.`;
  if (!follow) return lead;
  const name = pickName(follow);
  const rank = step.rank(follow);
  if (rank == null) return `${lead} ${name} was not found by ${step.label.toLowerCase()}.`;
  const combined = follow.signals?.pre_rerank_rank;
  const was = step.key === "final" && combined != null && combined !== rank ? ` (was #${combined} combined)` : "";
  return `${lead} ${name} is #${rank}${was}.`;
}

/**
 * How many candidates a search put on the shortlist, as the chips above count them,
 * and how many of those the search returned: the two numbers a reader compares.
 */
export function foundLine(step: RaceStep, response: SearchResponse): string | null {
  if (step.key !== "fts" && step.key !== "fuzzy" && step.key !== "semantic") return null;
  const count = response.diagnostics?.candidate_counts?.[armPoolKey[step.key]];
  if (count == null) return null;
  if (count === 0) return "It found no candidates for this request.";
  const shown = response.results.length;
  const returned = response.results.filter((product) => step.rank(product) != null).length;
  const among = returned === 0 ? "none of them" : returned === count ? "all of them" : `${returned} of them`;
  return `It found ${count} on the shortlist, ${among} among the ${shown} shown.`;
}

/**
 * The search's returned products racing through each step: every search on
 * its own, the combined order, then the reranked one. Rows glide on springs to
 * their new places, new ones rise in, and ones a step does not rank fade out.
 * It plays once through on arrival; choosing a step stops it there.
 */
export function RankRace({ response, pool, followId, wanted, missing, onFollow }: {
  response: SearchResponse;
  /**
   * The search's saved shortlist, each step's first products in it, as Shop's board
   * reads it. Null while it loads or when it cannot be read: the race then holds only
   * the returned products and says so.
   */
  pool?: ProductSummary[] | null;
  /** The product the caption and ring follow. */
  followId: number | null;
  /** Whether the followed product is the one the lab is looking for. */
  wanted: boolean;
  /** The lab's wanted product, by name, when this search did not return it. */
  missing?: string;
  onFollow: (productId: number) => void;
}) {
  const shownIds = useMemo(() => new Set(response.results.map((product) => product.product_id)), [response.results]);
  // The returned products keep the response's own copy; the shortlist adds what ranked below them.
  const products = useMemo(() => (pool
    ? [...response.results, ...pool.filter((product) => !shownIds.has(product.product_id))]
    : response.results), [pool, response.results, shownIds]);
  // Every step stays, even one with nothing to show: a search that found nothing, or
  // nothing on this page, is part of what happened, and the chips above count it.
  const steps = RACE_STEPS;
  const shortlist = response.diagnostics?.candidate_counts?.fused_pool;
  const reduceMotion = useReducedMotion() ?? false;
  const [stepKey, setStepKey] = useState<RaceStepKey>(() => (reduceMotion ? steps.at(-1) : steps[0])?.key ?? "final");
  const [playing, setPlaying] = useState(!reduceMotion && steps.length > 1);
  const step = steps.find((item) => item.key === stepKey) ?? steps.at(-1) ?? RACE_STEPS[4];
  const rows = useMemo(() => raceRows(products, step, followId, shownIds), [products, step, followId, shownIds]);
  const follow = products.find((product) => product.product_id === followId);

  // Rows that leave keep their last content while they fade out.
  const last = useRef(new Map<number, Slot>());
  const [leaving, setLeaving] = useState<number[]>([]);
  const visible = new Set(rows.map((row) => row.content.productId));
  const departing = [...last.current.keys()].filter((id) => !visible.has(id));
  const mounted: Slot[] = [...rows, ...departing.map((id) => last.current.get(id) as Slot)];

  const motions = useRef(new Map<number, RowMotion>());
  const elements = useRef(new Map<number, { row: HTMLLIElement | null; bar: HTMLSpanElement | null }>());
  const frame = useRef<number | null>(null);

  useLayoutEffect(() => {
    const pinnedSlot = rows.length > ROWS ? ROWS : -1;
    for (const { content, slot } of rows) {
      const y = slotY(slot, slot === pinnedSlot);
      let motion = motions.current.get(content.productId);
      if (!motion) {
        motion = { y: spring(y + ENTER_OFFSET), opacity: spring(0), width: spring(0) };
        motions.current.set(content.productId, motion);
      }
      motion.y.target = y;
      motion.opacity.target = 1;
      motion.width.target = content.width;
      last.current.set(content.productId, { content, slot });
    }
    for (const id of departing) {
      const motion = motions.current.get(id);
      if (motion) motion.opacity.target = 0;
    }
    setLeaving(departing);

    const paint = (id: number, motion: RowMotion) => {
      const element = elements.current.get(id);
      if (element?.row) {
        element.row.style.transform = `translate3d(0, ${motion.y.value}px, 0)`;
        element.row.style.opacity = String(Math.min(1, Math.max(0, motion.opacity.value)));
      }
      if (element?.bar) element.bar.style.transform = `scaleX(${Math.max(0, motion.width.value)})`;
    };
    const settleLeaving = () => {
      const gone = [...motions.current.entries()].filter(([id, motion]) => !visible.has(id) && motion.opacity.value < 0.02).map(([id]) => id);
      if (!gone.length) return;
      for (const id of gone) { motions.current.delete(id); last.current.delete(id); }
      setLeaving((current) => current.filter((id) => !gone.includes(id)));
    };

    if (reduceMotion) {
      for (const [id, motion] of motions.current) {
        for (const value of [motion.y, motion.opacity, motion.width]) { value.value = value.target; value.velocity = 0; }
        paint(id, motion);
      }
      settleLeaving();
      return undefined;
    }
    for (const [id, motion] of motions.current) paint(id, motion);
    let previous: number | null = null;
    const tick = (now: number) => {
      const seconds = previous == null ? 1 / 60 : Math.min(0.032, (now - previous) / 1000);
      previous = now;
      let moving = false;
      for (const [id, motion] of motions.current) {
        const settling = [motion.y, motion.opacity, motion.width].map((value) => advance(value, seconds));
        moving = settling.some(Boolean) || moving;
        paint(id, motion);
      }
      settleLeaving();
      frame.current = moving ? window.requestAnimationFrame(tick) : null;
    };
    if (frame.current != null) window.cancelAnimationFrame(frame.current);
    frame.current = window.requestAnimationFrame(tick);
    return () => {
      if (frame.current != null) window.cancelAnimationFrame(frame.current);
      frame.current = null;
    };
    // `rows` carries the step and the followed product; `departing` is derived from it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, reduceMotion]);

  // Play through every step once, then rest on the final order.
  useEffect(() => {
    if (!playing) return undefined;
    const index = steps.findIndex((item) => item.key === stepKey);
    if (index < 0 || index >= steps.length - 1) {
      setPlaying(false);
      return undefined;
    }
    const timer = window.setTimeout(() => setStepKey(steps[index + 1].key), REPLAY_MS);
    return () => window.clearTimeout(timer);
  }, [playing, stepKey, steps]);

  const choose = (key: RaceStepKey) => { setPlaying(false); setStepKey(key); };
  const replay = () => { setStepKey(steps[0]?.key ?? "final"); setPlaying(steps.length > 1); };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = steps.findIndex((item) => item.key === stepKey);
    const delta = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const next = steps[(index + delta + steps.length) % steps.length];
    choose(next.key);
    (event.currentTarget.querySelector(`[data-step="${next.key}"]`) as HTMLButtonElement | null)?.focus();
  };

  const cells = (content: RowContent) => <>
    <span className="pg-race-rank">#{content.rank}</span>
    <span className="pg-race-name">{content.name}</span>
    <span className="pg-race-track" aria-hidden="true">
      <span className="pg-race-bar" ref={(bar) => { elements.current.set(content.productId, { ...elements.current.get(content.productId) ?? { row: null }, bar }); }} />
    </span>
    <span className="pg-race-move" data-direction={content.move?.direction}>{content.move?.text ?? ""}</span>
  </>;

  const pinned = rows.length > ROWS;
  const height = Math.max(rows.length, 1) * ROW_HEIGHT + (pinned ? PINNED_GAP : 0);
  return <section className="pg-race" aria-labelledby="pg-race-title">
    <div className="pg-race-head">
      <div>
        <h3 id="pg-race-title">Watch the ranking change</h3>
        <p>{pool && shortlist
          ? `Each step’s first ${ROWS} on the shortlist of ${shortlist}. Faded rows are not among the ${response.results.length} shown.`
          : `The ${response.results.length} returned products, at each step’s own rank.`}</p>
      </div>
      <div className="pg-race-controls">
        <div className="pg-race-steps" role="radiogroup" aria-label="Ranking shown" onKeyDown={onKeyDown}>
          {steps.map((item) => <button key={item.key} type="button" role="radio" data-step={item.key} data-accent={stepAccent(item.key)} aria-checked={item.key === step.key} tabIndex={item.key === step.key ? 0 : -1} onClick={() => choose(item.key)}>{item.label}</button>)}
        </div>
        <button type="button" className="pg-race-replay" onClick={replay} disabled={steps.length < 2}>Replay</button>
      </div>
    </div>
    {follow ? <Journey steps={steps} product={follow} current={step.key} onPick={choose} /> : null}
    {rows.length ? null : <p className="pg-race-empty">{foundLine(step, response) ?? `${step.label} ranked none of these products.`}</p>}
    <ol className="pg-race-list" style={{ height: rows.length ? height : 0 }} aria-label={`${step.label} order`}>
      {mounted.map(({ content }) => {
        const gone = !visible.has(content.productId) || leaving.includes(content.productId) && !visible.has(content.productId);
        const followed = content.productId === followId;
        return <li
          key={content.productId}
          ref={(row) => { elements.current.set(content.productId, { ...elements.current.get(content.productId) ?? { bar: null }, row }); }}
          className="pg-race-row"
          data-step={step.key}
          data-followed={followed ? (wanted ? "wanted" : "chosen") : undefined}
          data-top={content.top || undefined}
          data-off-page={content.onPage ? undefined : true}
          aria-hidden={gone || undefined}
        >
          {content.onPage ? (
            <button type="button" onClick={() => onFollow(content.productId)} aria-label={`${content.name}: #${content.rank} in ${step.label.toLowerCase()}. Follow this product.`} tabIndex={gone ? -1 : 0}>
              {cells(content)}
            </button>
          ) : (
            <div className="pg-race-row-body" aria-label={`${content.name}: #${content.rank} in ${step.label.toLowerCase()}, not among the ${response.results.length} shown.`}>
              {cells(content)}
            </div>
          )}
        </li>;
      })}
    </ol>
    <p className="pg-race-caption" aria-live="polite">{raceCaption(step, products, response, follow, missing)}</p>
  </section>;
}
