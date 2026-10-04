import { DEPLOY_AGENT, VERIFY_AGENT } from "../../participantCommands";

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
