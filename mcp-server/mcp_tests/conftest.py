from __future__ import annotations

import sys
from pathlib import Path

import pytest

MCP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = MCP_ROOT.parent
for path in (MCP_ROOT, REPOSITORY_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
