"""The commands participants type, exactly as every lab guide shows them.

Guides, terminal messages, completion proofs and the Playground name the same
command, so a participant never translates between a Make target and the
script behind it. The Makefile keeps its targets as maintainer wrappers.
"""

ADVANCE_TO_LAB_2 = "uv run python scripts/lab_state.py advance --lab 1"
ADVANCE_TO_LAB_3 = "uv run python scripts/lab_state.py advance --lab 2"
STATUS = "uv run python scripts/lab_state.py status"
APPLY_SQL = "uv run python scripts/apply_search_functions.py"
LIST_TOOLS = "uv run python scripts/deploy_agentcore.py tools"
DEPLOY_AGENT = "uv run python scripts/deploy_agentcore.py deploy"
VERIFY_AGENT = "uv run python scripts/deploy_agentcore.py verify"
AGENTCORE_RESOURCES = "uv run python scripts/deploy_agentcore.py resources"
COMPARE_SETTINGS = "uv run python scripts/lab_exercise.py compare --lab 2"
RERANK_OFF_ON = "uv run python labs/lab2_rank/rerank_off_on.py"
HNSW_CHECK = "uv run python scripts/hnsw_exercise.py check"


def check_claim(product_id: int, sentence: str) -> str:
    return f'uv run python scripts/check_claim.py {product_id} "{sentence}"'


def ask_agent(question: str) -> str:
    return f'uv run python scripts/ask_agent.py "{question}"'


def ask_setup() -> str:
    """Lab 3's setup request from the terminal, worded exactly as completion checks it."""
    from service.lab_checks import mission_for_lab

    return ask_agent(mission_for_lab(3)["query"])


def start(lab: int) -> str:
    return f"uv run python scripts/lab_state.py start --lab {lab}"


def reset(lab: int) -> str:
    return f"uv run python scripts/lab_state.py reset --lab {lab}"


def solution(lab: int) -> str:
    return f"uv run python scripts/lab_state.py solution --lab {lab}"


def finish(lab: int) -> str:
    """A lab's Running behind? in one command: the steps `finish_steps` names."""
    return f"uv run python scripts/lab_state.py finish --lab {lab}"


def skip_to(lab: int) -> str:
    """Start at a later lab: the earlier labs are finished with their reference answers."""
    return f"uv run python scripts/lab_state.py skip-to --lab {lab}"


def finish_steps(lab: int) -> tuple[str, ...]:
    """The commands `finish` runs for one lab, in order; each is safe to repeat.

    Labs 1 and 2 end handed off to the next lab. Lab 3 ends deployed: completion
    needs a setup run the participant asks for themselves.
    """
    if lab == 3:
        return (start(3), solution(3), LIST_TOOLS, DEPLOY_AGENT)
    checks = (exercise_check(2), ADVANCE_TO_LAB_3) if lab == 2 else (ADVANCE_TO_LAB_2,)
    return (start(lab), solution(lab), APPLY_SQL, repeat_request(lab), *checks)


# Which lines of your lab files differ from the reference answer, without the answer.
DIFF = "uv run python scripts/diff.py"
# The same report with the reference answer's lines: the last step of a Stuck? block.
DIFF_ANSWER = "uv run python scripts/diff.py --answer"


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


# How long each command `finish` and `skip-to` run usually takes, in seconds, rounded up:
# measured on event 814672215611 on 25 October 2026, where `finish --lab 3` from a fresh
# account took 1:41. A later lab's start only reads its record, because the previous
# hand-off started that lab. The deploy is the sum of its phases.
DEPLOY_PHASE_SECONDS = (5, 16, 16, 21, 13)
USUAL_SECONDS: dict[str, float] = {
    start(1): 5,
    solution(1): 1,
    APPLY_SQL: 1,
    repeat_request(1): 5,
    ADVANCE_TO_LAB_2: 9,
    start(2): 1,
    solution(2): 1,
    repeat_request(2): 5,
    exercise_check(2): 1,
    ADVANCE_TO_LAB_3: 7,
    start(3): 1,
    solution(3): 1,
    LIST_TOOLS: 2,
    DEPLOY_AGENT: sum(DEPLOY_PHASE_SECONDS),
}
