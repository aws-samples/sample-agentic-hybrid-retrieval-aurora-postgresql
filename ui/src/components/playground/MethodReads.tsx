import { trigrams } from "../../retrievalMatrix";
import type { ReactNode } from "react";
import type { RetrievalArm } from "../../retrievalLanguage";
import type { SearchResponse } from "../../types";
import { modelName } from "./RetrievalPath";

const SHOWN_TRIGRAMS = 5;

/** pg_trgm's trigrams for the request's words, in order and without repeats. */
function requestTrigrams(query: string): string[] {
  const words = query.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  return [...new Set(words.flatMap((word) => [...trigrams(word)]))];
}

/**
 * One search's words as each method reads them: the lexemes full-text search
 * looks up, the trigrams fuzzy matching compares, and the vector semantic
 * search embeds. The agent may reword Alex's request, so this reads the
 * search's own query. A term no listing holds is struck through, from the
 * search's coverage record; a replayed record keeps none, and says so.
 */
export function armReads(response: SearchResponse): Record<RetrievalArm, ReactNode> {
  const terms = response.coverage?.terms.filter((term) => term.lexeme) ?? [];
  const grams = requestTrigrams(response.query);
  const embedding = modelName(response.diagnostics?.embedding_model_id);
  return {
    fts: terms.length
      ? terms.map((term) => (term.verdict === "matched"
        ? <code key={term.ordinal}>{term.lexeme}</code>
        : <s key={term.ordinal} title={term.verdict === "recoverable" ? `No listing holds it; closest is ${term.closest_lexeme}` : "No listing holds it"}><code>{term.lexeme}</code></s>))
      : <span>words not in the saved record</span>,
    fuzzy: <>
      {grams.slice(0, SHOWN_TRIGRAMS).map((gram) => <code key={gram}>{gram.replace(/ /g, "␣")}</code>)}
      {grams.length > SHOWN_TRIGRAMS ? <span>+{grams.length - SHOWN_TRIGRAMS}</span> : null}
    </>,
    semantic: <><code>vector</code>{embedding ? <span>{embedding}</span> : null}</>,
  };
}
