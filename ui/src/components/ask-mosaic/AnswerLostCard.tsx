import { GRADE_SETUP_RUN } from "../../participantCommands";
import { TerminalCommand } from "../TerminalCommand";

/**
 * A required Lab 3 answer whose stream broke before it arrived. The Retrieval agent may
 * still save the run, and asking again would spend a second turn, so this points to the
 * completion check, which reads the saved runs, as `ask_agent.py` does on a lost stream.
 */
export function AnswerLostCard({ runId }: { runId?: string }) {
  return (
    <section aria-label="Check your saved answers" className="ask-mosaic-setup" role="status">
      <strong>The connection closed before the answer arrived.</strong>
      <span>
        The Retrieval agent may still save this run, so asking again would start a second one.
        Wait a minute, then check your saved answers and follow the check’s Next line.
      </span>
      <TerminalCommand command={GRADE_SETUP_RUN} />
      {runId ? <small>Run ID <code>{runId}</code></small> : null}
    </section>
  );
}
