import { useMemo } from "react";
import Markdown from "react-markdown";
import type { AgentCitation } from "../../types";
import { ageText, type MdNode } from "./ageText";
import { jumpToSource } from "./citations";

/**
 * The answer of record as it arrives: Markdown prose whose newest characters
 * are faint and darken as more text follows, with citation numbers as chips.
 *
 * `text` is the revealed slice and `reveal` is the answer's clock (see
 * `useSoftReveal`). Once `reveal` is `TRAIL` past the end nothing is faint, so
 * a settled or restored answer renders as ordinary prose.
 */
export function StreamedAnswer({
  text,
  reveal,
  citations,
  answerId,
}: {
  text: string;
  reveal: number;
  citations: AgentCitation[];
  answerId: string;
}) {
  const numbers = useMemo(() => new Set(citations.map((citation) => citation.number)), [citations]);
  return (
    <div className="ask-prose">
      <Markdown
        remarkPlugins={[() => (tree) => ageText(tree as MdNode, reveal, numbers, answerId)]}
        components={{
          a: ({ node, children, href, ...props }) => {
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
          },
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
