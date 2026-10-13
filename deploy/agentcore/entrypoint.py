"""Select the native AgentCore protocol without changing the shared image."""

import os
import shutil
import sys

#: AgentCore Observability: with the stack's MOSAIC_OBSERVABILITY=on, the AWS
#: Distro for OpenTelemetry launcher starts each server, so the agent's Strands
#: spans and the SQL tools' requests reach CloudWatch. Runtime sets
#: AGENT_OBSERVABILITY_ENABLED, which tells the distro where to send them; see
#: docs/agentcore-runtime.md, "Observability".
LAUNCHER = "opentelemetry-instrument"

SERVERS = {"agent": "deploy.agentcore.run", "tools": "deploy.agentcore.run_tools"}


def main() -> None:
    """Exec the protocol's server so it receives signals as the container process.

    Tracing never decides whether Lab 3 runs. Unset means off, so this image
    behaves as before on a stack that predates the switch, and a missing
    launcher starts the server untraced with the reason in the runtime log.
    """
    mode = os.environ.get("MOSAIC_RUNTIME_MODE", "agent")
    if mode not in SERVERS:
        raise ValueError(
            f"Runtime protocol rule: unexpected mode {mode!r}; use agent or tools."
        )
    command = [sys.executable, "-m", SERVERS[mode]]
    if os.environ.get("MOSAIC_OBSERVABILITY") == "on":
        launcher = shutil.which(LAUNCHER)
        if launcher is None:
            print(
                f"Observability rule: the image has no {LAUNCHER}, so this runtime "
                "starts without traces; fix: build it with "
                "`uv sync --extra agentcore-observability`, as deploy/agentcore/Dockerfile does.",
                file=sys.stderr,
                flush=True,
            )
        else:
            command = [launcher, *command]
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
