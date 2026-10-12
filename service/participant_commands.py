"""The commands participants type, exactly as every lab guide shows them.

Guides, terminal messages, completion proofs and the Playground name the same
command, so a participant never translates between a Make target and the
script behind it. The Makefile keeps its targets as maintainer wrappers.
"""

ADVANCE_TO_LAB_2 = "uv run python scripts/lab_state.py advance --lab 1"
STATUS = "uv run python scripts/lab_state.py status"
APPLY_SQL = "uv run python scripts/apply_search_functions.py"
LIST_TOOLS = "uv run python scripts/deploy_agentcore.py tools"
DEPLOY_AGENT = "uv run python scripts/deploy_agentcore.py deploy"
VERIFY_AGENT = "uv run python scripts/deploy_agentcore.py verify"
AGENTCORE_RESOURCES = "uv run python scripts/deploy_agentcore.py resources"
COMPARE_SETTINGS = "uv run python scripts/lab_exercise.py compare --lab 2"
HNSW_CHECK = "uv run python scripts/hnsw_exercise.py check"


def ask_agent(question: str) -> str:
    return f'uv run python scripts/ask_agent.py "{question}"'


def start(lab: int) -> str:
    return f"uv run python scripts/lab_state.py start --lab {lab}"


def reset(lab: int) -> str:
    return f"uv run python scripts/lab_state.py reset --lab {lab}"


def solution(lab: int) -> str:
    return f"uv run python scripts/lab_state.py solution --lab {lab}"


def diff(lab: int) -> str:
    """Compare a lab's marked block with the reference answer; it prints the answer."""
    return f"uv run python scripts/lab_state.py diff --lab {lab}"


def validate(lab: int) -> str:
    return f"uv run python scripts/validate_lab.py --lab {lab}"


def complete_lab_3(run_id: str = "<your-run-id>") -> str:
    return f"uv run python scripts/complete_agent.py --run-id {run_id}"


def validate_applied(lab: int) -> str:
    """Check the source and the SQL Aurora last applied, as the guides do."""
    return (
        f"uv run python scripts/lab_state.py validate --lab {lab} "
        '--database-url "$DATABASE_URL"'
    )


def repeat_request(lab: int) -> str:
    """Repeat the lab's saved request against the repaired state."""
    return f"uv run python scripts/lab_terminal.py run --lab {lab} --phase after"


def exercise_check(lab: int) -> str:
    """Grade the participant's own exercise or saved run, without a new answer."""
    return f"uv run python scripts/lab_exercise.py check --lab {lab}"


def prove(lab: int) -> str:
    """The guide's proof after applying a SQL repair: repeat the request, then its check.

    Lab 1 hands off to Lab 2 after its checks; Lab 2's first task grades the applied formula.
    """
    check = ADVANCE_TO_LAB_2 if lab == 1 else exercise_check(lab)
    return f"{repeat_request(lab)}, then {check}"
