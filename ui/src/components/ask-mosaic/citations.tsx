import type { MouseEvent } from "react";

/** The id of source `number` in this answer's source list. */
export const sourceAnchor = (answerId: string, number: number) => `${answerId}-source-${number}`;

export function jumpToSource(event: MouseEvent<HTMLAnchorElement>, id: string) {
  const target = document.getElementById(id);
  if (!target) return;
  // The panel scrolls, not the page; a hash would also enter browser history.
  event.preventDefault();
  target.scrollIntoView({ block: "nearest" });
  target.focus({ preventScroll: true });
}

/** Numbered pills that jump to the sources they name. */
export function CitePills({ numbers, answerId }: { numbers: number[]; answerId: string }) {
  return (
    <>
      {numbers.map((number) => {
        const id = sourceAnchor(answerId, number);
        return (
          <a
            key={number}
            className="ask-answer-cite"
            href={`#${id}`}
            aria-label={`Source ${number}`}
            onClick={(event) => jumpToSource(event, id)}
          >
            {number}
          </a>
        );
      })}
    </>
  );
}
