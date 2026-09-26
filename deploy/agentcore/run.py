"""Python ZIP entry point for the preprovisioned workshop agent."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.chdir(Path(__file__).resolve().parents[2])

import uvicorn

if __name__ == "__main__":
    uvicorn.run("deploy.agentcore.app:app", host="0.0.0.0", port=8080)
