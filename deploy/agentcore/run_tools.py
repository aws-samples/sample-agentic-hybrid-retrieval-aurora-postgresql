"""Start the workshop SQL tools on AgentCore Runtime's MCP port."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.chdir(Path(__file__).resolve().parents[2])

from deploy.agentcore.tools import mcp

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
