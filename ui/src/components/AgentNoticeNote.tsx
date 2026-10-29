import { Info } from "lucide-react";
import type { AgentNotice } from "../api";

/** The service's note on an agent answer, such as that the reference Retrieval agent gave it. */
export function AgentNoticeNote({ notice }: { notice: AgentNotice }) {
  return (
    <div className="agent-notice" role="note" aria-label={notice.title}>
      <span className="agent-notice-heading">
        <Info size={15} aria-hidden="true" />
        {notice.title}
      </span>
      <small>{notice.detail}</small>
    </div>
  );
}
