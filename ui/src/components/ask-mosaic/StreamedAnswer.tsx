import { useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import type { AgentCitation } from "../../types";
import { revealText, type MdNode } from "./revealText";
import { jumpToSource } from "./citations";

/**
 * A citation chip, or an ordinary link. Defined once, outside render: an inline
 * renderer is a new component type on every reveal step, so React would remount
 * each chip as the prose grows and restart its fade before it could finish.
 */
const AnswerLink: Components["a"] = ({ node, children, href, ...props }) => {
  const source = node?.properties?.dataSource ?? node?.properties?.["data-source"];
  if (source == null) return <a href={href} {...props}>{children}</a>;
  return (
    <a
      {...props}
      href={href}
      aria-label={`Source ${source}`}
      onClick={(event) => jumpToSource(event, String(href).slice(1))}
    >
      {children}
    </a>
  );
};

const COMPONENTS: Components = { a: AnswerLink };

/**
 * The answer of record as it arrives: Markdown prose read out a few words at a
 * time, each chunk fading in once from a soft blur, with citation numbers as
 * chips.
 *
 * `text` is the revealed slice and `chunks` where each revealed chunk starts
 * (see `useSoftReveal`). A restored answer has no chunks and renders as
 * ordinary prose. `className` lets a surface keep its own prose styles.
 */
export function StreamedAnswer({
  text,
  chunks,
  citations,
  answerId,
  className = "ask-prose",
}: {
  text: string;
  chunks: readonly number[];
  citations: AgentCitation[];
  answerId: string;
  className?: string;
}) {
  const numbers = useMemo(() => new Set(citations.map((citation) => citation.number)), [citations]);
  return (
    <div className={className}>
      <Markdown
        remarkPlugins={[() => (tree) => revealText(tree as MdNode, chunks, numbers, answerId)]}
        components={COMPONENTS}
      >
        {text}
      </Markdown>
    </div>
  );
}
