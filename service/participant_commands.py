"""The commands participants type, exactly as every lab guide shows them.

Guides, terminal messages, completion proofs and the Playground name the same
command, so a participant never translates between a Make target and the
script behind it. The Makefile keeps its targets as maintainer wrappers.
"""

STATUS = "uv run python scripts/lab_state.py status"
APPLY_SQL = "uv run python scripts/apply_search_functions.py"
LIST_TOOLS = "uv run python scripts/deploy_agentcore.py tools"
DEPLOY_AGENT = "uv run python scripts/deploy_agentcore.py deploy"
VERIFY_AGENT = "uv run python scripts/deploy_agentcore.py verify"


def start(lab: int) -> str:
    return f"uv run python scripts/lab_state.py start --lab {lab}"


def reset(lab: int) -> str:
    return f"uv run python scripts/lab_state.py reset --lab {lab}"


def solution(lab: int) -> str:
    return f"uv run python scripts/lab_state.py solution --lab {lab}"


def validate(lab: int) -> str:
    return f"uv run python scripts/validate_lab.py --lab {lab}"


def complete_lab_3(run_id: str = "<your-run-id>") -> str:
    return f"uv run python scripts/complete_agent.py --run-id {run_id}"
