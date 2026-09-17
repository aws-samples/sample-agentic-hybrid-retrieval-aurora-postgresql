"""Exercise smoke-target ownership and protocol checks without a Docker daemon."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", ["none", "collision", "ping", "identity"])
def test_smoke_checks_protocol_and_only_removes_its_own_container(tmp_path, failure):
    docker = tmp_path / "docker"
    docker.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['SMOKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[0] == 'run':
    if os.environ['SMOKE_FAILURE'] == 'collision':
        sys.exit(125)
    if '--cidfile' in args:
        pathlib.Path(args[args.index('--cidfile') + 1]).write_text('owned-container-id')
    print('owned-container-id')
""")
    curl = tmp_path / "curl"
    curl.write_text("""#!/usr/bin/env python3
import json, os, sys
with open(os.environ['SMOKE_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
body = {'status': 'Healthy'} if sys.argv[-1].endswith('/ping') else {'service': 'catalog-hybrid-retrieval'}
if os.environ['SMOKE_FAILURE'] == 'ping': body['status'] = 'unhealthy'
if os.environ['SMOKE_FAILURE'] == 'identity': body['service'] = 'another-project'
print(json.dumps(body))
""")
    docker.chmod(0o755)
    curl.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    result = subprocess.run(
        ["make", "agentcore-image-smoke", f"DOCKER={docker}"],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DATABASE_URL": "not-used-by-the-fake-container",
            "SMOKE_LOG": str(log),
            "SMOKE_FAILURE": failure,
            "PYTHONOPTIMIZE": "1",
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    removals = [call for call in calls if call[0] == "rm"]
    if failure == "collision":
        assert result.returncode != 0
        assert not removals, "a failed start must not remove a pre-existing container"
    else:
        assert (result.returncode == 0) == (failure == "none"), result.stderr
        assert removals == [["rm", "-f", "owned-container-id"]]
        assert any(call[-1].endswith("/ping") for call in calls)
        if failure != "ping":
            assert any(call[-1].endswith("/api/health") for call in calls)
