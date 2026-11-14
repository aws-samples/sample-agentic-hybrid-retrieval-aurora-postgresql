import type { ReactNode } from "react";

/**
 * `text` from `from` to `to`, with each marked span (the figure a claim cited, in the
 * record's own words) in a `<mark>`. Spans outside the range are skipped, so a caller
 * can render a line in two parts and still mark a figure that falls in either.
 */
export function MarkedText({ text, marks, from = 0, to = text.length }: {
  text: string;
  marks: Array<[number, number]>;
  from?: number;
  to?: number;
}) {
  const parts: ReactNode[] = [];
  let at = from;
  for (const [start, end] of marks) {
    const left = Math.max(start, at);
    const right = Math.min(end, to);
    if (right <= left) continue;
    if (left > at) parts.push(text.slice(at, left));
    parts.push(<mark key={left} className="ask-figure">{text.slice(left, right)}</mark>);
    at = right;
  }
  if (at < to) parts.push(text.slice(at, to));
  return <>{parts}</>;
}
