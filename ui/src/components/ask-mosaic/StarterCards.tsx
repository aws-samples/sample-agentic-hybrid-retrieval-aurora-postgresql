import {
  Armchair,
  ChevronRight,
  CircleCheck,
  Headphones,
  House,
  MessageCircle,
  Monitor,
  type LucideIcon,
} from "lucide-react";
import type { workspaceRequests } from "../../labMissions";
import type { SearchFilters } from "../../types";

type WorkspaceRequest = ReturnType<typeof workspaceRequests>[number];

const STARTER_ICONS: Record<string, LucideIcon> = {
  "plan-workspace": House,
  "focus-at-home": Headphones,
  "recover-headphones": Headphones,
  "check-focus-picks": Headphones,
  "check-sources": CircleCheck,
  "comfortable-days": Armchair,
  "more-screen-space": Monitor,
};

/**
 * Where a conversation can start: each manifest request as a card with its
 * label and the notice that says what it will do, in full. The notice is the
 * card's description, not part of its name, so a screen reader hears the label
 * first and the explanation after.
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
            const Icon = STARTER_ICONS[suggestion.id] ?? MessageCircle;
            const labelId = `ask-starter-${suggestion.id}-label`;
            const noticeId = `ask-starter-${suggestion.id}`;
            return (
              <li key={suggestion.id}>
                <button
                  type="button"
                  aria-labelledby={labelId}
                  aria-describedby={suggestion.notice ? noticeId : undefined}
                  onClick={() => onRun(suggestion.query, suggestion.filters, Boolean(suggestion.mission_id))}
                >
                  <span className="ask-start-icon" aria-hidden="true"><Icon size={18} /></span>
                  <span className="ask-start-copy">
                    <span className="ask-start-label" id={labelId}>{suggestion.shop_label}</span>
                    {suggestion.notice ? (
                      <span className="ask-start-notice" id={noticeId}>{suggestion.notice}</span>
                    ) : null}
                  </span>
                  <ChevronRight size={14} aria-hidden="true" />
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
