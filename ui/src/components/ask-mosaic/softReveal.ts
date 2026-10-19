import { useEffect, useRef, useState } from "react";

/**
 * Characters per millisecond when the reveal has caught up with the stream:
 * about 50 a second, so the answer never stalls on a slow delivery.
 */
const FLOOR_PER_MS = 0.05;

/**
 * A backlog this many characters long is revealed at one character per
 * millisecond. The pace rises with the backlog, so a burst from the network
 * is read out smoothly instead of landing at once.
 */
const CATCH_UP_MS = 1800;

/** A cut moves forward to the next space unless that is further than this. */
const WORD_REACH = 12;

/** A long frame (a background tab, a busy main thread) adds at most this much time. */
const LONGEST_FRAME_MS = 64;

/**
 * Where a chunk that takes `take` characters from `start` ends.
 *
 * It finishes the word it lands in, so a chunk is whole words and their
 * trailing space; a short tail with no space after it, such as a closing
 * `[2].`, goes whole. A word longer than `WORD_REACH` is cut where it was.
 */
export function chunkEnd(text: string, start: number, take: number): number {
  const end = start + take;
  if (end >= text.length) return text.length;
  const space = text.indexOf(" ", end);
  if (space === -1) return text.length - end <= WORD_REACH ? text.length : end;
  return space - end > WORD_REACH ? end : space + 1;
}

/** How many characters a frame of `elapsedMs` earns with `backlog` still to show. */
export function earned(elapsedMs: number, backlog: number): number {
  return Math.min(LONGEST_FRAME_MS, elapsedMs) * Math.max(FLOOR_PER_MS, backlog / CATCH_UP_MS);
}

/**
 * Cuts the reveal back to the last point that renders cleanly as Markdown.
 *
 * A slice that stops between a bold marker and its close would paint literal
 * asterisks for a few frames. Holding the reveal just before the opener means
 * an emphasized phrase appears whole once its closing marker has streamed in.
 */
function balancedMarkdownSlice(text: string, length: number): string {
  if (length >= text.length) return text;
  const slice = text.slice(0, length);
  const boldMarks = slice.split("**").length - 1;
  if (boldMarks % 2 === 0) return slice;
  return slice.slice(0, slice.lastIndexOf("**"));
}

export interface SoftReveal {
  /** The prose shown so far, cut at a clean Markdown boundary. */
  text: string;
  /**
   * Where each revealed chunk starts, in order. Each chunk fades in once as it
   * mounts; an answer that was never paced has none and renders as plain prose.
   */
  chunks: readonly number[];
  done: boolean;
}

const NO_CHUNKS: readonly number[] = [];

/**
 * Reads streamed prose onto the page a few words at a time.
 *
 * The clock is elapsed time, not frames, so a 120 Hz display reads at the same
 * pace as a 60 Hz one. Each frame earns characters at a rate that grows with
 * the backlog; once a whole character is earned, the next chunk runs to the end
 * of its word. A turn that mounts already answered, or any turn under reduced
 * motion, shows everything at once.
 */
export function useSoftReveal(
  text: string,
  streaming: boolean,
  enabled: boolean,
  instant: boolean,
): SoftReveal {
  const [startedStreaming] = useState(streaming);
  const [chunks, setChunks] = useState<readonly number[]>(NO_CHUNKS);
  const [shown, setShown] = useState(0);
  const latest = useRef(text);
  latest.current = text;
  const position = useRef(0);
  const pace = enabled && startedStreaming && !instant;
  const caughtUp = shown >= text.length;
  const done = !pace || (!streaming && caughtUp);

  useEffect(() => {
    if (!pace || caughtUp) return undefined;
    let last: number | null = null;
    let carry = 0;
    let frame = window.requestAnimationFrame(function step(now) {
      const from = position.current;
      const backlog = latest.current.length - from;
      carry += last == null ? 0 : earned(now - last, backlog);
      last = now;
      const take = Math.floor(carry);
      if (take > 0 && backlog > 0) {
        const to = chunkEnd(latest.current, from, take);
        carry = 0;
        position.current = to;
        setShown(to);
        setChunks((current) => [...current, from]);
      }
      if (position.current < latest.current.length) frame = window.requestAnimationFrame(step);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [pace, caughtUp]);

  if (!enabled) return { text: "", chunks: NO_CHUNKS, done: false };
  if (!pace) return { text, chunks: NO_CHUNKS, done: true };
  return { text: balancedMarkdownSlice(text, Math.min(shown, text.length)), chunks, done };
}
