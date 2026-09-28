import { trigrams } from "../../retrievalMatrix";
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
 * looks up, the trigrams close spelling compares, and the vector meaning
 * match embeds. The agent may reword Alex's request, so this reads the
 * search's own query. A term no listing holds is struck through, from the
 * search's coverage record; a replayed record keeps none, and says so.
 */
export function MethodReads({ response, label }: { response: SearchResponse; label: string }) {
  const terms = response.coverage?.terms.filter((term) => term.lexeme) ?? [];
  const grams = requestTrigrams(response.query);
  const counts = response.diagnostics?.candidate_counts;
  const embedding = modelName(response.diagnostics?.embedding_model_id);
  return (
    <div className="pg-reads-block">
      <p className="pg-reads-label">{label}</p>
      <ul className="pg-reads" aria-label={label}>
        <li data-arm="fts">
          <i aria-hidden="true" />Exact terms
          {terms.length ? terms.map((term) => (term.verdict === "matched"
            ? <code key={term.ordinal}>{term.lexeme}</code>
            : <s key={term.ordinal} title={term.verdict === "recoverable" ? `No listing holds it; closest is ${term.closest_lexeme}` : "No listing holds it"}><code>{term.lexeme}</code></s>))
            : <span>words not in the saved record</span>}
        </li>
        <li data-arm="trigram">
          <i aria-hidden="true" />Close spelling
          {grams.slice(0, SHOWN_TRIGRAMS).map((gram) => <code key={gram}>{gram.replace(/ /g, "␣")}</code>)}
          {grams.length > SHOWN_TRIGRAMS ? <span>+{grams.length - SHOWN_TRIGRAMS}</span> : null}
          {counts?.trigram_in_pool === 0 ? <b>no candidates</b> : null}
        </li>
        <li data-arm="semantic">
          <i aria-hidden="true" />Meaning match <code>vector</code>{embedding ? ` from ${embedding}` : null}
        </li>
      </ul>
    </div>
  );
}
