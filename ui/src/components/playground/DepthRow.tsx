import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

export type DetailId = "retrieve" | "rank" | "rerank" | "reason";

export interface DepthItem {
  id: DetailId;
  label: string;
  content: ReactNode;
}

/**
 * The run's depth, one item at a time: a row of quiet buttons under the board,
 * and the open item's panel beneath them. Nothing here is needed to follow the
 * story; everything a reader may want to check is one click away.
 */
export function DepthRow({ items, open, onOpen }: {
  items: DepthItem[];
  open: DetailId | null;
  onOpen: (id: DetailId | null) => void;
}) {
  return <section className="pg-depth" aria-label="Look deeper" data-tour="pg-details">
    <div className="pg-depth-row">
      {items.map((item) => <button
        key={item.id}
        id={`inspect-${item.id}-button`}
        type="button"
        className="pg-inspect"
        aria-expanded={open === item.id}
        aria-controls={`inspect-${item.id}-details`}
        onClick={() => onOpen(open === item.id ? null : item.id)}
      >
        {item.label}<ChevronDown size={16} aria-hidden="true" />
      </button>)}
    </div>
    {items.map((item) => <div
      key={item.id}
      id={`inspect-${item.id}-details`}
      className="pg-section-details pg-depth-panel"
      role="region"
      aria-labelledby={`inspect-${item.id}-button`}
      hidden={open !== item.id}
    >
      {open === item.id ? item.content : null}
    </div>)}
  </section>;
}
