"""Exercise image isolation, immutable retries and native protocol selection."""

import base64
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from deploy.agentcore import entrypoint
from scripts import deploy_agentcore as deploy
from scripts import package_agentcore as packaging

URI = "123456789012.dkr.ecr.us-east-1.amazonaws.com/workshop"
DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize("mode,module", [("agent", "run"), ("tools", "run_tools")])
def test_protocol_executes_the_existing_native_server(monkeypatch, mode, module):
    monkeypatch.setenv("MOSAIC_RUNTIME_MODE", mode)
    execute = Mock()
    monkeypatch.setattr(os, "execv", execute)
    entrypoint.main()
    assert execute.call_args.args[1][1:] == ["-m", "deploy.agentcore." + module]


def test_unknown_protocol_fails_before_a_server_starts(monkeypatch):
    monkeypatch.setenv("MOSAIC_RUNTIME_MODE", "other")
    execute = Mock()
    monkeypatch.setattr(os, "execv", execute)
    with pytest.raises(ValueError, match="Runtime protocol rule"):
        entrypoint.main()
    execute.assert_not_called()


def test_context_hash_covers_shipped_bytes_and_excludes_credentials(
    tmp_path, monkeypatch
):
    root = tmp_path / "source"
    root.mkdir()
    files = ["service/app.py", "uv.lock", "deploy/agentcore/Dockerfile"]
    for name in files:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("source")
    (root / ".env").write_text("DATABASE_URL=private")
    monkeypatch.setattr(packaging, "FILES", tuple(files))
    first = tmp_path / "first"
    digest = packaging.package(root, first)
    assert sorted(
        str(p.relative_to(first)) for p in first.rglob("*") if p.is_file()
    ) == sorted(files)
    (root / ".env").write_text("different-private")
    assert packaging.package(root, tmp_path / "second") == digest
    (root / "service/app.py").write_text("participant repair")
    assert packaging.package(root, tmp_path / "third") != digest
    with pytest.raises(ValueError, match="not empty"):
        packaging.package(root, first)


def image_client(monkeypatch):
    ecr = Mock()

    class Missing(Exception):
        pass

    ecr.exceptions.ImageNotFoundException = Missing
    ecr.get_authorization_token.return_value = {
        "authorizationData": [
            {
                "proxyEndpoint": "https://" + URI.split("/")[0],
                "authorizationToken": base64.b64encode(
                    b"AWS:test-sensitive-token"
                ).decode(),
            }
        ]
    }
    monkeypatch.setattr(deploy, "client", lambda service: ecr)
    monkeypatch.setattr(deploy, "package", lambda *_: "b" * 64)
    return ecr, Missing


def test_push_keeps_registry_password_out_of_arguments_and_removes_login_file(
    monkeypatch,
):
    ecr, missing = image_client(monkeypatch)
    ecr.describe_images.side_effect = [
        missing(),
        {"imageDetails": [{"imageDigest": DIGEST}]},
    ]
    commands = []

    def command(argv, **kwargs):
        assert "test-sensitive-token" not in " ".join(argv)
        config = Path(kwargs["env"]["DOCKER_CONFIG"])
        assert config.is_dir() and config.stat().st_mode & 0o777 == 0o700
        if argv[1] == "login":
            assert kwargs["input"] == "test-sensitive-token\n"
            (config / "config.json").write_text(
                json.dumps({"auth": "test-sensitive-token"})
            )
        commands.append((argv, config))

    monkeypatch.setattr(deploy.subprocess, "run", command)
    assert deploy.publish_image(URI, bootstrap=False) == URI + "@" + DIGEST
    assert [command[0][1] for command in commands] == ["login", "build", "push"]
    assert "linux/arm64" in commands[1][0]
    assert commands[2][0][-1] == URI + ":source-" + "b" * 64
    assert all(not config.exists() for _, config in commands)


def test_bootstrap_retry_reuses_the_immutable_tag_without_rebuilding(monkeypatch):
    ecr, _ = image_client(monkeypatch)
    monkeypatch.setenv("SOURCE_REVISION", "c" * 40)
    ecr.describe_images.return_value = {"imageDetails": [{"imageDigest": DIGEST}]}
    command = Mock()
    monkeypatch.setattr(deploy.subprocess, "run", command)
    assert deploy.publish_image(URI, bootstrap=True) == URI + "@" + DIGEST
    assert ecr.describe_images.call_args.kwargs["imageIds"] == [
        {"imageTag": "bootstrap-" + "c" * 40}
    ]
    command.assert_not_called()
    ecr.get_authorization_token.assert_not_called()


def test_failed_push_never_releases_cloudformation(monkeypatch):
    monkeypatch.setenv("MOSAIC_RUNTIME_IMAGE_REPOSITORY", URI)
    monkeypatch.setattr(
        deploy, "publish_image", Mock(side_effect=RuntimeError("push failed"))
    )
    aws = Mock()
    monkeypatch.setattr(deploy, "client", aws)
    with pytest.raises(RuntimeError, match="push failed"):
        deploy.stage(bootstrap=True)
    aws.assert_not_called()


def test_registry_login_retries_transient_failure_and_cleans_up_on_failure(monkeypatch):
    ecr, missing = image_client(monkeypatch)
    ecr.describe_images.side_effect = missing()
    configs = []

    def fail(argv, **kwargs):
        configs.append(Path(kwargs["env"]["DOCKER_CONFIG"]))
        raise deploy.subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(deploy.subprocess, "run", fail)
    monkeypatch.setattr(deploy.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError, match="Registry login rule.*three attempts"):
        deploy.publish_image(URI, bootstrap=False)
    assert len(configs) == 3
    assert all(not config.exists() for config in configs)
