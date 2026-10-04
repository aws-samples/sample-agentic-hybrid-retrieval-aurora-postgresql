import { useLayoutEffect, useRef, useState } from "react";

/**
 * The question an Ask Mosaic shortlist answers, set as a quiet line under the
 * headline. A lab request runs to several sentences, so it clamps to two lines
 * and offers the rest only when the clamp actually hides something.
 */
export function ShortlistQuestion({ question }: { question: string }) {
  const line = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);

  useLayoutEffect(() => {
    const element = line.current;
    if (!element || expanded) return undefined;
    const measure = () => setOverflowing(element.scrollHeight > element.clientHeight + 1);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, [question, expanded]);

  if (!question) return null;
  return (
    <div className="shop-shortlist-question">
      <p ref={line} className={expanded ? undefined : "is-clamped"}>{question}</p>
      {overflowing || expanded ? (
        <button type="button" aria-expanded={expanded} onClick={() => setExpanded((open) => !open)}>
          {expanded ? "Show less" : "Show all"}
        </button>
      ) : null}
    </div>
  );
}
