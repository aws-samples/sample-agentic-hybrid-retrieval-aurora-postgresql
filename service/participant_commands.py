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
HNSW_GRADE = "uv run python scripts/hnsw_exercise.py grade"
# The Scale & HNSW exercise's own files, which the index checker grades.
HNSW_FILES = (
    "mkdir -p .local/hnsw && touch .local/hnsw/index.sql .local/hnsw/search.sql"
)
# The guide's Lab 3 follow-up, after Alex's setup request and before the completion check.
ASK_100W_QUESTION = (
    "My laptop needs 100W charging. Does the ViewSonic VG2756-4K monitor still meet that "
    "need? Use its product records and explain what I would need to check."
)


def check_claim_command(product_id: int, sentence: str) -> str:
    return f'uv run python scripts/check_claim.py {product_id} "{sentence}"'


def ask_agent_command(question: str) -> str:
    return f'uv run python scripts/ask_agent.py "{question}"'


def ask_setup_command() -> str:
    """Lab 3's setup request from the terminal, worded exactly as completion checks it."""
    from service.lab_checks import mission_for_lab

    return ask_agent_command(mission_for_lab(3)["query"])


def ask_100w_command() -> str:
    """Lab 3's follow-up: whether the ViewSonic still meets a need for 100W charging."""
    return ask_agent_command(ASK_100W_QUESTION)


def open_psql_command(lab: int) -> str:
    """Open `psql` with a lab's saved request, from the terminal."""
    return f"PSQLRC=.local/lab-{lab}/context.psql psql"


def load_context_command(lab: int) -> str:
    """Load a lab's saved request into a `psql` that is already open."""
    return rf"\i .local/lab-{lab}/context.psql"


def check_builder_tool_command(module: str) -> str:
    """Check the Retrieval tool exercise's file with two brands."""
    return f"uv run python -m scripts.check_builder_tool --module {module}"


def call_headphones_agent_command(module: str) -> str:
    """Let the Retrieval agent call the tool in the exercise's file."""
    return (
        f"PYTHONPATH=. uv run python {module} --agent "
        '--query "Headphones for video calls from home" --brand Bose'
    )


def start_command(lab: int) -> str:
    return f"uv run python scripts/lab_state.py start --lab {lab}"


def reset_command(lab: int) -> str:
    return f"uv run python scripts/lab_state.py reset --lab {lab}"


def apply_solution_command(lab: int) -> str:
    return f"uv run python scripts/lab_state.py apply-solution --lab {lab}"


def finish_command(lab: int) -> str:
    """A lab's Running behind? in one command: the steps `finish_steps` names."""
    return f"uv run python scripts/lab_state.py finish --lab {lab}"


def skip_to_command(lab: int) -> str:
    """Start at a later lab: the earlier labs are finished with their reference answers."""
    return f"uv run python scripts/lab_state.py skip-to --lab {lab}"


def finish_steps(lab: int) -> tuple[str, ...]:
    """The commands `finish` runs for one lab, in order; each is safe to repeat.

    Labs 1 and 2 end handed off to the next lab. Lab 3 ends deployed: completion
    needs a setup run the participant asks for themselves.
    """
    if lab == 3:
        return (start_command(3), apply_solution_command(3), LIST_TOOLS, DEPLOY_AGENT)
    checks = (
        (grade_exercise_command(2), ADVANCE_TO_LAB_3)
        if lab == 2
        else (ADVANCE_TO_LAB_2,)
    )
    return (
        start_command(lab),
        apply_solution_command(lab),
        APPLY_SQL,
        repeat_request_command(lab),
        *checks,
    )


# Which lines of your lab files differ from the reference answer, without the answer.
DIFF = "uv run python scripts/diff.py"
# The same report with the reference answer's lines: the last step of a Stuck? block.
DIFF_ANSWER = "uv run python scripts/diff.py --answer"


def prove_lab_command(lab: int) -> str:
    return f"uv run python scripts/prove_lab.py --lab {lab}"


def grade_setup_run_command(run_id: str | None = None) -> str:
    """Prove Lab 3 on the newest setup run since Lab 3 started, or on the run named."""
    command = "uv run python scripts/grade_setup_run.py"
    return f"{command} --run-id {run_id}" if run_id else command


def lab3_steps(
    *, deploy: bool = False, setup: bool = True, follow_up: bool = True
) -> tuple[str, tuple[str, ...]]:
    """What Lab 3 completion still needs, in order: a `Next:` sentence and its commands.

    Completion checks the newest setup run and the newest answered 100W question since
    Lab 3 started, both made by the code deployed now, so a deploy needs both again. A
    caller that knows a run is already saved from that code leaves it out: each is a
    full agent run.

    Args:
        deploy: The workspace's code is not deployed yet.
        setup: Alex's setup request still needs a run from the deployed code.
        follow_up: The 100W question still needs an answer from the deployed code.
    """
    setup = setup or deploy
    follow_up = follow_up or deploy
    steps: list[str] = []
    commands: list[str] = []
    if deploy:
        steps.append("deploy your Retrieval agent")
        commands.append(DEPLOY_AGENT)
    if setup:
        steps.append("ask Alex's setup request")
        commands.append(ask_setup_command())
    if follow_up:
        steps.append("the 100W question" if setup else "ask the 100W question")
        commands.append(ask_100w_command())
    steps.append("check both answers:" if setup and follow_up else "check completion:")
    commands.append(grade_setup_run_command())
    return ", then ".join(steps), tuple(commands)


def validate_applied_command(lab: int) -> str:
    """Check the source and the SQL Aurora last applied, as the guides do."""
    return (
        f"uv run python scripts/lab_state.py validate --lab {lab} "
        '--database-url "$DATABASE_URL"'
    )


def repeat_request_command(lab: int) -> str:
    """Repeat the lab's saved request against the repaired state."""
    return f"uv run python scripts/lab_request.py send --lab {lab} --phase after"


def grade_exercise_command(lab: int) -> str:
    """Grade the participant's own exercise or saved run, without a new answer."""
    return f"uv run python scripts/lab_exercise.py grade --lab {lab}"


def proof_steps_text(lab: int) -> str:
    """The guide's proof after applying a SQL repair: repeat the request, then its check.

    Lab 1 hands off to Lab 2 after its checks; Lab 2's first task grades the applied formula.
    """
    check = ADVANCE_TO_LAB_2 if lab == 1 else grade_exercise_command(lab)
    return f"{repeat_request_command(lab)}, then {check}"


# How long each command `finish` and `skip-to` run usually takes, in seconds, rounded up:
# measured on a Workshop Studio event on 25 October 2026, where `finish --lab 3` from a fresh
# account took 1:41. A later lab's start only reads its record, because the previous
# hand-off started that lab. The deploy is the sum of its phases. A pair is the shortest and
# longest measured where a step's time varies: the deploy's verification took 13 s on a
# participant's first deploy and 26 to 27 s on seven later ones on the 10 November 2026 event,
# while its other steps took the same time on all eight. It took 29 s and then 27 s on the
# 10 November walk of release 59cc5923229175e4 and 27 s on 11 November, so the longest shown
# is 30 s.
DEPLOY_PHASE_SECONDS: tuple[float | tuple[float, float], ...] = (
    5,
    16,
    16,
    21,
    (13, 30),
)
USUAL_SECONDS: dict[str, float | tuple[float, float]] = {
    start_command(1): 5,
    apply_solution_command(1): 1,
    APPLY_SQL: 1,
    repeat_request_command(1): 5,
    ADVANCE_TO_LAB_2: 9,
    start_command(2): 1,
    apply_solution_command(2): 1,
    repeat_request_command(2): 5,
    grade_exercise_command(2): 1,
    ADVANCE_TO_LAB_3: 7,
    start_command(3): 1,
    apply_solution_command(3): 1,
    LIST_TOOLS: 2,
    DEPLOY_AGENT: (
        sum(p[0] if isinstance(p, tuple) else p for p in DEPLOY_PHASE_SECONDS),
        sum(p[1] if isinstance(p, tuple) else p for p in DEPLOY_PHASE_SECONDS),
    ),
}
