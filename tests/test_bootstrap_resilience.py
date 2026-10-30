"""The bootstrap must survive a reboot or a session kill part-way through.

An account that patches new instances on launch ended the bootstrap four minutes
in: one Region lost a child to SIGHUP and rolled the stack back, the other lost the
script silently and waited out a two-hour timeout. The loader therefore starts the
script as a systemd unit that resumes at the next boot, and the script keeps a
marker per phase. These tests run the real shell text, with only curl, systemctl,
aws and the host's absolute paths faked.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "deploy" / "mosaic-bootstrap.sh"
EDITOR_TEMPLATE = (
    ROOT / "deploy" / "cloudformation" / "hybrid-retrieval-code-editor.yml"
)

PHASES = (
    "packages",
    "source",
    "secrets",
    "image",
    "ui",
    "catalog",
    "services",
    "readiness",
)


@pytest.fixture(scope="module")
def script() -> str:
    return BOOTSTRAP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def user_data() -> str:
    """The launch template's user data with its YAML indentation removed."""
    text = EDITOR_TEMPLATE.read_text(encoding="utf-8")
    marker = "        UserData:\n          Fn::Base64: !Sub |\n"
    lines = []
    for line in text[text.index(marker) + len(marker) :].splitlines():
        if line.strip() and not line.startswith(" " * 12):
            break
        lines.append(line[12:])
    return "\n".join(lines) + "\n"


def _heredoc(text: str, opener: str, terminator: str) -> str:
    start = text.index(opener)
    body = text[text.index("\n", start) + 1 :]
    return body[: body.index(f"\n{terminator}\n")] + "\n"


def _function(script: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{$.*?^\}}$", script, re.MULTILINE | re.DOTALL)
    assert match, f"{name} is no longer defined at the start of a line"
    return match.group()


def _bash(program: str, env: dict | None = None, path: Path | None = None):
    environment = {**os.environ, **(env or {})}
    if path is not None:
        environment["PATH"] = f"{path}:{environment['PATH']}"
    return subprocess.run(
        ["bash", "-c", program],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


# ------------------------------------------------------------------ the unit


def test_the_unit_resumes_after_a_reboot_and_stops_once_complete(user_data):
    unit = _heredoc(
        user_data,
        "cat >/etc/systemd/system/mosaic-bootstrap.service <<'UNIT'",
        "UNIT",
    )
    lines = set(unit.splitlines())
    assert {
        "Description=Mosaic workshop host bootstrap",
        "After=network-online.target cloud-final.service",
        "Wants=network-online.target",
        "ConditionPathExists=!/var/lib/mosaic-bootstrap/complete",
        "Type=exec",
        "EnvironmentFile=/etc/mosaic-bootstrap.env",
        "ExecStart=/opt/mosaic-bootstrap.sh",
        "ExecStopPost=/opt/mosaic-bootstrap-stop-post.sh",
        "TimeoutStartSec=0",
        "TimeoutStopSec=30",
        "KillMode=mixed",
        "WantedBy=multi-user.target",
    } <= lines, unit


def test_the_loader_starts_the_unit_instead_of_running_the_script(user_data):
    live = "\n".join(
        line for line in user_data.splitlines() if not line.lstrip().startswith("#")
    )
    assert "systemctl enable --now --no-block mosaic-bootstrap.service" in live
    assert not re.search(r'^"\$BOOTSTRAP_SCRIPT"$', live, re.MULTILINE), (
        "the loader runs the script inline again, so a reboot or a session kill ends it"
    )
    assert 'exec "$BOOTSTRAP_SCRIPT"' not in live


def _render_loader(user_data: str, root: Path, values: dict | None = None) -> str:
    """Resolve Fn::Sub placeholders and move the host's absolute paths under `root`."""
    values = {"AWS::Region": "us-east-1", **(values or {})}
    program = re.sub(
        r"\$\{([A-Za-z:.]+)\}",
        lambda match: values.get(match.group(1), f"v-{match.group(1)}"),
        user_data,
    )
    # Fn::Sub writes `${!x}` as the literal `${x}`, which bash then expands itself.
    program = program.replace("${!", "${")
    program = re.sub(r"^exec > >\(tee .*$", "exec 2>&1", program, flags=re.MULTILINE)
    for host_path in (
        "/etc/mosaic-bootstrap.env",
        "/etc/systemd/system/mosaic-bootstrap.service",
        "/opt/mosaic-bootstrap-stop-post.sh",
        "/opt/mosaic-bootstrap.sh",
        "/var/log/mosaic-bootstrap.log",
        "/run/mosaic-bootstrap-failure-signalled",
        "/var/lib/mosaic-bootstrap/complete",
    ):
        program = program.replace(host_path, str(root) + host_path)
    return program


def _loader_host(root: Path) -> Path:
    stubs = root / "stubs"
    stubs.mkdir()
    (root / "etc" / "systemd" / "system").mkdir(parents=True)
    for directory in ("opt", "run", "var/log", "var/lib/mosaic-bootstrap"):
        (root / directory).mkdir(parents=True)
    _stub(stubs, "aws", f'printf "#!/bin/bash\\ntouch {root}/script-ran\\n" >"$4"')
    _stub(stubs, "sha256sum", "cat >/dev/null")
    _stub(stubs, "logger", "cat >/dev/null")
    _stub(stubs, "install", 'cp /dev/null "$4"; chmod 600 "$4"')
    _stub(stubs, "systemctl", f'echo "$*" >>{root}/systemctl-calls')
    _stub(stubs, "curl", f'echo "${{*: -1}}" >>{root}/curl-calls')
    return stubs


def test_the_loader_writes_the_environment_file_and_never_runs_the_script(
    user_data, tmp_path
):
    stubs = _loader_host(tmp_path)
    program = _render_loader(
        user_data, tmp_path, {"RepoUrl": "https://x.test/repo.git"}
    )
    result = _bash(program, path=stubs)
    assert result.returncode == 0, result.stdout + result.stderr

    environment = tmp_path / "etc" / "mosaic-bootstrap.env"
    assert oct(environment.stat().st_mode & 0o777) == "0o600"
    written = environment.read_text().splitlines()
    assert 'REPO_URL="https://x.test/repo.git"' in written
    assert 'AWS_REGION="us-east-1"' in written
    assert 'CODE_EDITOR_CONNECTION_TOKEN="v-SecretPlaintext.password"' in written
    assert 'ORIGIN_VERIFY_SECRET="v-OriginSecretPlaintext.password"' in written
    assert all(re.fullmatch(r'[A-Z_]+="[^"]*"', line) for line in written), written

    assert (tmp_path / "etc/systemd/system/mosaic-bootstrap.service").is_file()
    stop_post = tmp_path / "opt" / "mosaic-bootstrap-stop-post.sh"
    assert oct(stop_post.stat().st_mode & 0o777) == "0o700"
    calls = (tmp_path / "systemctl-calls").read_text().splitlines()
    assert calls == [
        "daemon-reload",
        "enable --now --no-block mosaic-bootstrap.service",
    ]
    assert not (tmp_path / "script-ran").exists()
    assert not (tmp_path / "curl-calls").exists()


def test_the_loader_escapes_quotes_and_backslashes_the_way_systemd_reads_them(
    user_data, tmp_path
):
    """The origin secret allows punctuation, so a value may hold either character."""
    stubs = _loader_host(tmp_path)
    raw = 'https://x.test/a\\b"c'
    program = _render_loader(user_data, tmp_path, {"RepoUrl": raw})
    result = _bash(program, path=stubs)
    assert result.returncode == 0, result.stdout + result.stderr
    written = (tmp_path / "etc" / "mosaic-bootstrap.env").read_text().splitlines()
    line = next(line for line in written if line.startswith("REPO_URL="))
    assert line == 'REPO_URL="https://x.test/a\\\\b\\"c"'
    # systemd's EnvironmentFile undoes exactly these escapes inside double quotes.
    value = line.split("=", 1)[1][1:-1]
    assert value.replace('\\"', '"').replace("\\\\", "\\") == raw


def test_the_loader_refuses_a_newline_the_environment_file_cannot_hold(
    user_data, tmp_path
):
    stubs = _loader_host(tmp_path)
    program = _render_loader(user_data, tmp_path, {"RepoUrl": "https://x.test/a\nb"})
    result = _bash(program, path=stubs)
    assert result.returncode != 0
    assert "REPO_URL" in result.stdout
    assert (tmp_path / "curl-calls").read_text().splitlines() == [
        "v-BootstrapWaitHandle",
        "v-ImageReadyWaitHandle",
    ]
    assert not (tmp_path / "systemctl-calls").exists()


# ------------------------------------------------------------------ stop-post


def _systemctl_stub(directory: Path, state: str, jobs: str = "") -> None:
    """is-system-running and list-jobs answer separately, as on a real host."""
    _stub(
        directory,
        "systemctl",
        f"""case "$1" in
  is-system-running) echo "{state}"; exit 1 ;;
  list-jobs) printf '%s' "{jobs}"; exit 0 ;;
esac""",
    )


def _run_stop_post(
    user_data,
    tmp_path,
    *,
    exit_status,
    state,
    jobs="",
    service_result="exit-code",
    markers=(),
):
    stubs = _loader_host(tmp_path)
    program = _render_loader(user_data, tmp_path)
    body = _heredoc(
        program,
        "cat >" + str(tmp_path) + "/opt/mosaic-bootstrap-stop-post.sh <<'STOPPOST'",
        "STOPPOST",
    )
    stop_post = tmp_path / "stop-post.sh"
    stop_post.write_text(body)
    _systemctl_stub(stubs, state, jobs)
    _stub(stubs, "curl", f'echo "$*" >>{tmp_path}/curl-calls')
    for marker in markers:
        (tmp_path / marker).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / marker).touch()
    result = _bash(
        f"bash {stop_post}",
        env={
            "EXIT_STATUS": exit_status,
            "SERVICE_RESULT": service_result,
            "BOOTSTRAP_WAIT_HANDLE": "https://bootstrap.test/h",
            "IMAGE_READY_WAIT_HANDLE": "https://image.test/h",
        },
        path=stubs,
    )
    calls = tmp_path / "curl-calls"
    return result, calls.read_text().splitlines() if calls.exists() else []


def test_stop_post_relies_on_the_units_environment_file(user_data):
    body = _heredoc(
        user_data, "cat >/opt/mosaic-bootstrap-stop-post.sh <<'STOPPOST'", "STOPPOST"
    )
    assert ". /etc/mosaic-bootstrap.env" not in body
    assert body.count("--max-time 10") == 2


@pytest.mark.parametrize(
    ("exit_status", "state", "jobs", "service_result"),
    [
        ("1", "stopping", "", "exit-code"),
        ("TERM", "stopping", "", "signal"),
        ("KILL", "stopping", "", "timeout"),
        ("143", "running", "reboot.target start waiting", "exit-code"),
        ("1", "running", "poweroff.target start waiting", "exit-code"),
    ],
)
def test_stop_post_sends_nothing_when_the_system_is_shutting_down(
    user_data, tmp_path, exit_status, state, jobs, service_result
):
    result, curl_calls = _run_stop_post(
        user_data,
        tmp_path,
        exit_status=exit_status,
        state=state,
        jobs=jobs,
        service_result=service_result,
    )
    assert result.returncode == 0
    assert curl_calls == []
    log = (tmp_path / "var/log/mosaic-bootstrap.log").read_text()
    assert "interrupted by a shutdown" in log
    assert "mosaic-bootstrap.service resumes at the next boot" in log
    assert not (tmp_path / "run/mosaic-bootstrap-failure-signalled").exists()


@pytest.mark.parametrize(
    ("exit_status", "service_result"),
    [
        ("TERM", "signal"),
        ("HUP", "signal"),
        ("143", "exit-code"),
        ("129", "exit-code"),
        ("KILL", "timeout"),
    ],
)
def test_stop_post_reports_a_death_by_signal_on_a_running_system(
    user_data, tmp_path, exit_status, service_result
):
    result, curl_calls = _run_stop_post(
        user_data,
        tmp_path,
        exit_status=exit_status,
        state="running",
        service_result=service_result,
    )
    assert result.returncode == 0
    assert len(curl_calls) == 2
    assert all('"Status":"FAILURE"' in call for call in curl_calls)
    assert (tmp_path / "run/mosaic-bootstrap-failure-signalled").exists()


def test_stop_post_reports_a_real_failure_once_and_marks_it(user_data, tmp_path):
    result, curl_calls = _run_stop_post(
        user_data, tmp_path, exit_status="1", state="running"
    )
    assert result.returncode == 0
    assert len(curl_calls) == 2
    assert curl_calls[0].endswith("https://bootstrap.test/h")
    assert curl_calls[1].endswith("https://image.test/h")
    assert all('"Status":"FAILURE"' in call for call in curl_calls)
    assert "without an acknowledged failure report" in curl_calls[0]
    assert (tmp_path / "run/mosaic-bootstrap-failure-signalled").exists()


@pytest.mark.parametrize(
    "marker",
    ["var/lib/mosaic-bootstrap/complete", "run/mosaic-bootstrap-failure-signalled"],
)
def test_stop_post_sends_nothing_after_completion_or_an_acknowledged_failure(
    user_data, tmp_path, marker
):
    result, curl_calls = _run_stop_post(
        user_data, tmp_path, exit_status="1", state="running", markers=(marker,)
    )
    assert result.returncode == 0
    assert curl_calls == []


# ------------------------------------------------------------- signals in the script


def test_hangup_is_ignored_and_terminate_stops_without_a_failure(script, tmp_path):
    hangup = "trap '' HUP"
    assert hangup in script
    assert script.index(hangup) < script.index("exec > >(tee -a")
    program = "\n".join(
        [
            hangup,
            _function(script, "stop_for_shutdown"),
            "trap stop_for_shutdown TERM",
            "signal_failure() { echo SIGNALLED-A-FAILURE; }",
            "trap 'signal_failure $?' ERR",
            "kill -HUP $$",
            "echo survived-hangup",
            "bash -c 'kill -HUP $$; echo child-survived-hangup'",
            "kill -TERM $$",
            "echo not-reached",
        ]
    )
    result = _bash(program)
    assert result.returncode == 143
    assert "survived-hangup" in result.stdout
    assert "child-survived-hangup" in result.stdout
    assert (
        "stopping for a shutdown; the service resumes at the next boot" in result.stdout
    )
    assert "SIGNALLED-A-FAILURE" not in result.stdout
    assert "not-reached" not in result.stdout


def _signal_failure_run(script, tmp_path, *, rc, state, jobs=""):
    handler = (
        _function(script, "shutting_down") + "\n" + _function(script, "signal_failure")
    ).replace("/run/mosaic-bootstrap-failure-signalled", str(tmp_path / "marker"))
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _systemctl_stub(stubs, state, jobs)
    _stub(stubs, "curl", f'echo "$*" >>{tmp_path}/curl-calls')
    result = _bash(
        f"""set -Eeuo pipefail
BOOTSTRAP_WAIT_HANDLE=https://bootstrap.test
IMAGE_READY_WAIT_HANDLE=https://image.test
failure_reason() {{ printf 'reason'; }}
{handler}
signal_failure {rc}
""",
        path=stubs,
    )
    calls = tmp_path / "curl-calls"
    return result, calls.read_text().splitlines() if calls.exists() else []


@pytest.mark.parametrize(
    ("rc", "state", "jobs"),
    [
        (17, "stopping", ""),
        (143, "stopping", ""),
        (17, "running", "reboot.target start waiting"),
    ],
)
def test_signal_failure_stays_silent_when_the_system_is_shutting_down(
    script, tmp_path, rc, state, jobs
):
    result, calls = _signal_failure_run(script, tmp_path, rc=rc, state=state, jobs=jobs)
    assert result.returncode == rc
    assert calls == []
    assert not (tmp_path / "marker").exists()
    assert "resumes at the next boot" in result.stdout


@pytest.mark.parametrize("rc", [17, 129, 143])
def test_signal_failure_reports_every_status_on_a_running_system(script, tmp_path, rc):
    result, calls = _signal_failure_run(script, tmp_path, rc=rc, state="running")
    assert result.returncode == rc
    assert len(calls) == 2


def test_signal_failure_still_reports_a_failure_on_a_running_system(script, tmp_path):
    result, calls = _signal_failure_run(script, tmp_path, rc=17, state="running")
    assert result.returncode == 17
    assert len(calls) == 2


# ------------------------------------------------------------------ phases


def _run_phase_program(script, state_dir, body):
    return _bash(
        f"""set -Eeuo pipefail
STATE_DIR={state_dir}
{_function(script, "run_phase")}
{body}
"""
    )


def test_a_finished_phase_is_skipped_and_an_unfinished_one_runs_again(script, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    counter = tmp_path / "runs"

    broken = f"once() {{ echo run >>{counter}; false; }}\nrun_phase demo once"
    first = _run_phase_program(script, state_dir, broken)
    assert first.returncode != 0
    assert not (state_dir / "demo.done").exists()

    working = (
        f"once() {{ echo run >>{counter}; }}\nrun_phase demo once\nrun_phase demo once"
    )
    second = _run_phase_program(script, state_dir, working)
    assert second.returncode == 0, second.stderr
    assert counter.read_text().splitlines() == ["run", "run"]
    assert (state_dir / "demo.done").exists()

    timestamp = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"
    lines = second.stdout.splitlines()
    assert [re.fullmatch(timestamp + r" phase demo: (\w+)", line) for line in lines]
    assert [line.split(": ")[1] for line in lines] == ["start", "done", "skip"]


def test_the_script_runs_every_phase_in_order_and_completes_last(script):
    calls = [f"run_phase {name} phase_{name}" for name in PHASES]
    positions = [script.index(call) for call in calls]
    assert positions == sorted(positions)
    assert script.index("load_database_credentials\nrun_phase secrets") > positions[1]
    success = script.index('"Status":"SUCCESS","Reason":"Mosaic bootstrap complete"')
    complete = script.index('touch "$STATE_DIR/complete"')
    hnsw = script.index("systemctl start --no-block mosaic-hnsw-prepare.service")
    assert positions[-1] < success < hnsw < complete


def test_participant_commands_run_in_their_own_session(script):
    assert re.search(
        r"^sudo\(\) \{\n  setsid -w sudo \"\$@\"\n\}$", script, re.MULTILINE
    )


def _catalog_wait_program(script: str, tmp_path: Path, busy_answers: int):
    """Run the catalog phase's lock handling up to `make db-bootstrap-schema`."""
    body = script[script.index("  export MOSAIC_VOCABULARY_CACHE_DIR=") :]
    body = body[
        : body.index("  make db-bootstrap-schema\n")
        + len("  make db-bootstrap-schema\n")
    ]
    body = body.replace('\\"', '"').replace("\\$", "$")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "log"
    _stub(
        stubs,
        "psql",
        f"""case "$*" in
  *pg_terminate_backend*) echo terminate >>{log}; echo 1 ;;
  *count*) n=$(grep -c '^count' {log} 2>/dev/null || true)
    echo count >>{log}
    if [ "$n" -lt {busy_answers} ]; then echo 1; else echo 0; fi ;;
esac""",
    )
    _stub(stubs, "make", f'echo "make $*" >>{log}')
    _stub(stubs, "sleep", f"echo sleep >>{log}")
    result = _bash(body, env={"DATABASE_URL": "postgresql://x"}, path=stubs)
    return result, log.read_text().split()


def test_the_catalog_waits_for_the_ended_restore_session_before_the_schema(
    script, tmp_path
):
    result, events = _catalog_wait_program(script, tmp_path, busy_answers=2)
    assert result.returncode == 0, result.stderr
    assert [e for e in events if e != "sleep"] == [
        "terminate",
        "count",
        "count",
        "count",
        "make",
        "db-bootstrap-schema",
    ]
    assert events.count("sleep") == 2


def test_the_catalog_gives_up_waiting_after_thirty_polls(script, tmp_path):
    result, events = _catalog_wait_program(script, tmp_path, busy_answers=999)
    assert result.returncode == 0, result.stderr
    assert events.count("count") == 30
    assert events[-2:] == ["make", "db-bootstrap-schema"]


def test_the_loader_and_the_script_agree_on_the_variables_it_hands_over(
    script, user_data
):
    def array(name: str) -> set[str]:
        return set(
            re.search(rf"^{name}=\(\n(.*?)^\)", script, re.MULTILINE | re.DOTALL)[
                1
            ].split()
        )

    loader = re.search(r"for name in (.*?); do", user_data, re.DOTALL)[1]
    written = set(loader.replace("\\\n", " ").split())
    # AWS_DEFAULT_REGION is for the AWS CLI v1 fallback and WORKSHOP_NAME is optional
    # in the script (`${WORKSHOP_NAME:-}`), so neither is a required name.
    expected = (
        array("required_environment")
        | array("required_defined_environment")
        | {"AWS_DEFAULT_REGION", "WORKSHOP_NAME"}
    )
    assert written == expected, (
        f"loader writes {sorted(written - expected)} the script does not require; "
        f"script requires {sorted(expected - written)} the loader never writes"
    )
