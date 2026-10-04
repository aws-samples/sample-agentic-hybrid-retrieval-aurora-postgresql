import { StartCommand } from "../LabRail";

/**
 * The first command in a setup message, such as the deploy step.
 *
 * The service writes the next step into `detail` as prose ending in a command.
 * Splitting it here puts that command in a copyable element without a second
 * copy of the string on the client.
 */
export function splitSetupCommand(detail: string): { prose: string; command: string | null } {
  const match = /uv run python [\w./-]+(?: [\w./-]+)*/.exec(detail);
  if (!match) return { prose: detail, command: null };
  const prose = detail.slice(0, match.index).replace(/\s*Next:\s*(deploy with)?\s*$/i, "").trim();
  return { prose, command: match[0] };
}

/** A calm next-step card for an agent that has not been assembled or deployed yet. */
export function AgentSetupCard({ detail }: { detail: string }) {
  const { prose, command } = splitSetupCommand(detail);
  return (
    <section
      aria-label="Finish setting up your agent"
      className="ask-mosaic-setup"
      role="status"
    >
      <strong>Finish setting up your agent</strong>
      <span>{prose}</span>
      {command ? (
        <>
          <StartCommand command={command} />
          <small>Then ask your question again.</small>
        </>
      ) : null}
    </section>
  );
}
