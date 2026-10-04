import { DEPLOY_AGENT, VERIFY_AGENT } from "../../participantCommands";
import { StartCommand } from "../LabRail";

/**
 * The two messages that are a next step for the participant: the agent has not
 * been assembled yet. Every other `agent_setup` message reports a deployment or
 * Gateway fault, which is an outage to read in full, not a to-do.
 */
const SETUP_CARD_LEADS = [
  "Your agent is not built yet.",
  "Your agent is missing its Mosaic tools.",
];

export function isSetupCardMessage(detail: string): boolean {
  return SETUP_CARD_LEADS.some((lead) => detail.startsWith(lead));
}

/**
 * The earliest participant command the message names, matched against the exact
 * strings the guides print so no trailing words are ever copied with it. The
 * prose is always the whole message.
 */
export function splitSetupCommand(detail: string): { prose: string; command: string | null } {
  const found = [DEPLOY_AGENT, VERIFY_AGENT]
    .map((command) => ({ command, at: detail.indexOf(command) }))
    .filter((entry) => entry.at >= 0)
    .sort((left, right) => left.at - right.at);
  return { prose: detail, command: found[0]?.command ?? null };
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
