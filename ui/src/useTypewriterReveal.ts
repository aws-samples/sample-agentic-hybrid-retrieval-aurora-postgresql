import { useCallback, useEffect, useState } from "react";

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

interface TypewriterReveal {
  /** The prose typed so far; the full text once the reveal has caught up. */
  text: string;
  done: boolean;
  /** Abandon the pacing: show everything now, and everything that streams in after. */
  skip: () => void;
}

/**
 * Paces streamed prose into a left-to-right typewriter reveal.
 *
 * The service delivers the answer in three-word chunks, and painting each chunk
 * the moment it lands makes the paragraph pop and reflow rather than write.
 * This advances a few characters per animation frame instead, speeding up with
 * the backlog so it trails the live stream by well under a second, then types
 * the tail out after the stream closes. A turn that mounts already answered —
 * reopening the panel, revisiting history — renders whole, as does everything
 * under reduced motion.
 */
export function useTypewriterReveal(
  text: string,
  streaming: boolean,
  enabled: boolean,
  instant: boolean,
): TypewriterReveal {
  const [startedStreaming] = useState(streaming);
  const [revealedCount, setRevealedCount] = useState(0);
  // A reader who has already seen "Backed by evidence" should not wait a
  // minute for prose the service finished; one click or key ends the pacing
  // for the rest of the turn.
  const [skipped, setSkipped] = useState(false);
  const skip = useCallback(() => setSkipped(true), []);
  const pace = enabled && startedStreaming && !instant && !skipped;
  const done = !pace || revealedCount >= text.length;
  useEffect(() => {
    if (done) return undefined;
    let frame = window.requestAnimationFrame(function step() {
      setRevealedCount((current) => {
        const backlog = text.length - current;
        if (backlog <= 0) return current;
        if (backlog > 240) return current + 14;
        if (backlog > 60) return current + 8;
        return current + 3;
      });
      frame = window.requestAnimationFrame(step);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [done, text]);
  if (!enabled) return { text: "", done: false, skip };
  if (!pace) return { text, done: true, skip };
  return { text: balancedMarkdownSlice(text, revealedCount), done, skip };
}
