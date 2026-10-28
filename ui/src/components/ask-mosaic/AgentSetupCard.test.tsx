// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DEPLOY_AGENT, VERIFY_AGENT } from "../../participantCommands";
import { AgentSetupCard } from "./AgentSetupCard";
import { isSetupCardMessage, splitSetupCommand } from "./setupMessage";

afterEach(cleanup);

/**
 * Every message the service raises as an `AgentSetupError`, copied from
 * service/agent_setup.py, agent_deploys.py, agentcore_transport.py and
 * gateway_tools.py with the command constants substituted. STEPS ask the
 * participant to finish or deploy their own code; FAULTS report a deployment or
 * Gateway fault.
 */
const STARTER = "Your Retrieval agent is not built yet. Open labs/lab3_reason/agent.py in Code Editor and "
  + "complete create_agent with the supplied model, tools, instructions and hooks. "
  + `Next: deploy with ${DEPLOY_AGENT}, then ask your question again.`;
const TOOLS = "Your Retrieval agent is missing its Mosaic tools. Open labs/lab3_reason/agent.py in Code "
  + "Editor and pass the supplied tools to Agent. "
  + `Next: deploy with ${DEPLOY_AGENT}, then ask your question again.`;
const STEPS = [
  STARTER,
  TOOLS,
  "Your Retrieval agent is missing the supplied execution hooks. Open labs/lab3_reason/agent.py "
  + "in Code Editor and pass hooks to Agent. "
  + `Next: deploy with ${DEPLOY_AGENT}, then ask your question again.`,
  "Your Retrieval agent is not ready: in labs/lab3_reason/agent.py, system_prompt must keep the "
  + "supplied instructions, which hold the tool order and evidence rules; pass "
  + "system_prompt=instructions, and put any rule of your own after them, as instructions + "
  + `"\\n...". Next: deploy with ${DEPLOY_AGENT}, then ask your question again.`,
  "Your Retrieval agent code raised NameError: name 'tols' is not defined. Open "
  + "labs/lab3_reason/agent.py in Code Editor and fix that line. "
  + `Next: deploy with ${DEPLOY_AGENT}, then ask your question again.`,
  "Your Retrieval agent has not been deployed since Lab 3 started at 10:00 UTC, so AgentCore "
  + "Runtime still runs the reference Retrieval agent this account was prepared with. "
  + `Next: deploy with ${DEPLOY_AGENT}, then ask your question again.`,
  "Your code in Code Editor changed after your deploy at 10:20 UTC, so AgentCore Runtime still "
  + `runs the earlier code. Next: deploy with ${DEPLOY_AGENT}, then ask your question again.`,
];

const FAULTS = [
  "The deployed Retrieval agent rejected this request. For a follow-up, clear chat and retry with a new "
  + `question. Otherwise, check the deployment with ${VERIFY_AGENT} in Code Editor; if it reports `
  + `changed code, deploy with ${DEPLOY_AGENT}.`,
  `Mosaic could not run the deployed agent. In Code Editor, check the deployment with ${VERIFY_AGENT}. `
  + `If you changed code, deploy with ${DEPLOY_AGENT} first. Next: retry your question; if `
  + "deployment fails, share the terminal message with your facilitator.",
  "The Retrieval agent could not reach its SQL tools through Gateway. In Code Editor, check the deployment "
  + `with ${VERIFY_AGENT}. Next: share a failed deployment check with your facilitator, or retry `
  + "your question if the check passes.",
  `Gateway returned an unreadable tool response. Next: check the deployment with ${VERIFY_AGENT} in `
  + "Code Editor and share the message with your facilitator.",
  `Gateway could not complete the tool request. Next: check the deployment with ${VERIFY_AGENT} in `
  + "Code Editor; ask your facilitator to inspect the Gateway target if it fails.",
  "Gateway tool search_products refused the request; check the retrieval scope and target logs.",
  `Gateway returned incomplete tool data. Next: check the deployment with ${VERIFY_AGENT} in Code `
  + "Editor and share the message with your facilitator.",
  `The deployed SQL tools differ from your workspace. Next: deploy with ${DEPLOY_AGENT} in Code `
  + "Editor, then ask your question again.",
];

describe("setup card eligibility", () => {
  it.each(STEPS)("shows %s as a next step", (message) => {
    expect(isSetupCardMessage(message)).toBe(true);
  });

  it.each(FAULTS)("keeps %s as an error", (message) => {
    expect(isSetupCardMessage(message)).toBe(false);
  });
});

describe("splitSetupCommand", () => {
  it.each(STEPS)("copies exactly the deploy command from %s", (message) => {
    const { prose, command } = splitSetupCommand(message);
    expect(command).toBe(DEPLOY_AGENT);
    expect(prose).toBe(message);
  });

  it("copies the verify command without the sentence that follows it", () => {
    const { command, prose } = splitSetupCommand(FAULTS[2]);
    expect(command).toBe(VERIFY_AGENT);
    expect(prose).toBe(FAULTS[2]);
  });

  it("finds no command in a message that names none", () => {
    expect(splitSetupCommand(FAULTS[5]).command).toBeNull();
  });

  it("never lets a command swallow trailing words", () => {
    for (const message of [...FAULTS, ...STEPS]) {
      const { command } = splitSetupCommand(message);
      expect([null, DEPLOY_AGENT, VERIFY_AGENT]).toContain(command);
    }
  });
});

describe("AgentSetupCard", () => {
  it("keeps the whole message and offers the deploy command", () => {
    render(<AgentSetupCard detail={STARTER} />);
    expect(screen.getByText(STARTER)).toBeTruthy();
    expect(screen.getByRole("button", { name: `Copy ${DEPLOY_AGENT}` })).toBeTruthy();
  });
});
