import { DEPLOY_AGENT, VERIFY_AGENT } from "../../participantCommands";

/**
 * The messages that are a next step for the participant: their agent is not
 * assembled yet, or Runtime does not run their latest code. Every other
 * `agent_setup` message reports a deployment or Gateway fault, which is an outage
 * to read in full, not a to-do.
 */
const SETUP_CARD_LEADS = [
  "Your Retrieval agent is not built yet.",
  "Your Retrieval agent is missing its Mosaic tools.",
  "Your Retrieval agent is missing the supplied execution hooks.",
  "Your Retrieval agent is not ready:",
  "Your Retrieval agent code raised ",
  "Your Retrieval agent has not been deployed since Lab 3 started",
  "Your code in Code Editor changed after your deploy",
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
