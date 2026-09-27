"""Select the native AgentCore protocol without changing the shared image."""

import os
import sys


def main() -> None:
    """Exec the protocol's server so it receives signals as the container process."""
    mode = os.environ.get("MOSAIC_RUNTIME_MODE", "agent")
    if mode == "tools":
        command = [sys.executable, "-m", "deploy.agentcore.run_tools"]
    elif mode == "agent":
        command = [sys.executable, "-m", "deploy.agentcore.run"]
    else:
        raise ValueError(
            f"Runtime protocol rule: unexpected mode {mode!r}; use agent or tools."
        )
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
