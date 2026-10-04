import { StartCommand } from "../LabRail";
import { splitSetupCommand } from "./setupMessage";

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
