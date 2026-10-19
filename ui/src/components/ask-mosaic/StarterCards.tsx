import type { workspaceRequests } from "../../labMissions";
import type { SearchFilters } from "../../types";

type WorkspaceRequest = ReturnType<typeof workspaceRequests>[number];

/**
 * One plain line per starter: what the request shows in its lab. Kept here, not
 * in the mission manifest, because the manifest feeds the retrieval fingerprint
 * and this is panel copy. A request with no line shows its title and clue only.
 */
const STARTER_LESSONS: Record<string, string> = {
  "plan-workspace": "Lab 3: three needs, one cited answer.",
  "focus-at-home": "One pair of headphones through every step.",
  "recover-headphones": "Lab 1: fuzzy matching finds a mistyped ID.",
  "comfortable-days": "Adjustable support, followed from search to comparison.",
  "more-screen-space": "Lab 2: fusion keeps the right monitor in play.",
  "check-focus-picks": "Two picks, one question: will teammates hear him?",
  "check-sources": "Every claim needs a source that supports it.",
};

/**
 * Where a conversation can start: each manifest request as a compact card with
 * a short title, what it shows, and the request itself as a quoted clue. The
 * lesson line is the card's description, not part of its name, so a screen
 * reader hears the title first.
 */
export function StarterCards({ suggestions, onRun }: {
  suggestions: WorkspaceRequest[];
  onRun: (query: string, filters?: SearchFilters, replaceShopFilters?: boolean) => void;
}) {
  return (
    <section className="ask-start">
      <h3>What can I help you find?</h3>
      {suggestions.length ? (
        <ul aria-label="Example questions">
          {suggestions.map((suggestion) => {
            const labelId = `ask-starter-${suggestion.id}-label`;
            const lessonId = `ask-starter-${suggestion.id}`;
            const lesson = STARTER_LESSONS[suggestion.id];
            return (
              <li key={suggestion.id}>
                <button
                  type="button"
                  aria-labelledby={labelId}
                  aria-describedby={lesson ? lessonId : undefined}
                  onClick={() => onRun(suggestion.query, suggestion.filters, Boolean(suggestion.mission_id))}
                >
                  <span className="ask-start-label" id={labelId}>{suggestion.shop_label}</span>
                  {lesson ? <span className="ask-start-lesson" id={lessonId}>{lesson}</span> : null}
                  <q className="ask-start-clue">{suggestion.query}</q>
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p>Tell me what matters to you. I’ll help you compare the options.</p>
      )}
    </section>
  );
}
