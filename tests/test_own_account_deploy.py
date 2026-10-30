"""Plans, refusals and the release digest of deploy/own-account/deploy.py."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
import yaml
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
CLOUDFORMATION = ROOT / "deploy" / "cloudformation"
SPEC = importlib.util.spec_from_file_location(
    "own_account_deploy", ROOT / "deploy" / "own-account" / "deploy.py"
)
deploy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = deploy
SPEC.loader.exec_module(deploy)

HEAD = "a" * 40
STUDIO_PIN = "11748fc9316005c9"
STUDIO_REPO_PATTERN = (
    r"^https://github\.com/aws-samples/"
    r"sample-agentic-hybrid-retrieval-aurora-postgresql\.git$"
)


def context(tmp_path: Path, **overrides) -> deploy.Context:
    values = {
        "region": "us-west-2",
        "profile": None,
        "bucket": "my-bucket",
        "stack_name": "mosaic-hybrid-retrieval",
        "dry_run": True,
        "repo_url": "https://github.com/me/fork.git",
        "source_revision": HEAD,
        "assets_dir": tmp_path / "assets",
        "out": lambda _line: None,
    }
    return deploy.Context(**{**values, **overrides})


class CodedError(Exception):
    """Stands in for botocore's ClientError where only the code matters."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.response = {"Error": {"Code": code, "Message": message}}


class FakeS3:
    """In-memory S3: objects map key -> (body, metadata); tags None means no tag set."""

    def __init__(self, objects=None, *, exists=True, tags="owned"):
        self.objects = dict(objects or {})
        self.exists = exists
        self.tags = [deploy.OWNER_TAG] if tags == "owned" else tags
        self.deleted: list = []
        self.delete_errors: list = []
        self.created = None
        self.bucket_deleted = False
        self.delete_bucket_error = None

    def head_bucket(self, Bucket):
        if not self.exists:
            raise CodedError("404")

    def create_bucket(self, **params):
        self.created = params
        self.exists = True

    def put_bucket_tagging(self, Bucket, Tagging):
        self.tags = Tagging["TagSet"]

    def get_bucket_tagging(self, Bucket):
        if self.tags is None:
            raise CodedError("NoSuchTagSet")
        return {"TagSet": self.tags}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise CodedError("404")
        body, metadata = self.objects[Key]
        return {"ContentLength": len(body), "Metadata": metadata}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise CodedError("NoSuchKey")
        body, metadata = self.objects[Key]
        return {"Body": io.BytesIO(body), "Metadata": metadata}

    def put_object(self, Bucket, Key, Body, Metadata):
        self.objects[Key] = (Body, Metadata)

    def get_paginator(self, _name):
        outer = self

        class Paginator:
            def paginate(self, Bucket):
                yield {
                    "Versions": [{"Key": k, "VersionId": "1"} for k in outer.objects],
                    "DeleteMarkers": [],
                }

        return Paginator()

    def delete_objects(self, Bucket, Delete):
        self.deleted += Delete["Objects"]
        return {"Errors": self.delete_errors}

    def delete_bucket(self, Bucket):
        if self.delete_bucket_error:
            raise CodedError(self.delete_bucket_error)
        self.bucket_deleted = True


def live_context(
    tmp_path: Path, client, lines: list[str], **overrides
) -> deploy.Context:
    ctx = context(tmp_path, dry_run=False, out=lines.append, **overrides)
    ctx.client_factory = lambda _service: client
    return ctx


@pytest.fixture
def clean_tree(monkeypatch):
    monkeypatch.setattr(deploy, "require_clean_tree", lambda: None)
    monkeypatch.setattr(deploy, "require_head", lambda _revision: None)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)


def operations(plan: list) -> list[tuple[str, str]]:
    return [(s, o) for step in plan for s, o, _ in step.calls]


def call(plan: list, operation: str) -> tuple:
    return next(c for step in plan for c in step.calls if c[1] == operation)


# ---------------------------------------------------------------- revision digest
def test_revision_digest_matches_independent_computation():
    def template(revision: str, source: str, bootstrap: str) -> str:
        return (
            "Parameters:\n"
            f"  InfrastructureRevision:\n    Type: String\n    Default: {revision}\n"
            f"  SourceRevision:\n    Type: String\n    Default: {source}\n"
            f"  BootstrapScriptSha256:\n    Type: String\n    Default: {bootstrap}\n"
        )

    main = template("0123456789abcdef", "b" * 40, "c" * 64)
    contract = "\n".join(
        [
            template("<derived-infrastructure-revision>", "b" * 40, "c" * 64),
            "b" * 40,
            "c" * 64,
            "VPC",
            "DATABASE",
            "EDITOR",
        ]
    )
    expected = hashlib.sha256(contract.encode()).hexdigest()[:16]
    assert (
        deploy.calculate_infrastructure_revision(main, "VPC", "DATABASE", "EDITOR")
        == expected
    )


def test_digest_with_the_studio_repourl_pattern_equals_the_studio_pin():
    """Only the two RepoUrl patterns differ from Studio's templates; revert them in memory."""
    new_pattern = r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$"
    main = (CLOUDFORMATION / deploy.MAIN_TEMPLATE).read_text()
    editor = (CLOUDFORMATION / deploy.EDITOR_TEMPLATE).read_text()
    assert new_pattern in main
    assert new_pattern in editor
    computed = deploy.calculate_infrastructure_revision(
        main.replace(new_pattern, STUDIO_REPO_PATTERN),
        (CLOUDFORMATION / deploy.VPC_TEMPLATE).read_text(),
        (CLOUDFORMATION / deploy.DATABASE_TEMPLATE).read_text(),
        editor.replace(new_pattern, STUDIO_REPO_PATTERN),
    )
    assert computed == STUDIO_PIN


def test_pinned_revision_matches_the_templates_in_this_repository():
    main = (CLOUDFORMATION / deploy.MAIN_TEMPLATE).read_text()
    computed = deploy.calculate_infrastructure_revision(
        main,
        (CLOUDFORMATION / deploy.VPC_TEMPLATE).read_text(),
        (CLOUDFORMATION / deploy.DATABASE_TEMPLATE).read_text(),
        (CLOUDFORMATION / deploy.EDITOR_TEMPLATE).read_text(),
    )
    assert computed == deploy.cfn_default(main, "InfrastructureRevision")


def test_release_is_pinned_to_the_requested_source():
    release = deploy.build_release(HEAD)
    main = release.files[deploy.MAIN_TEMPLATE].decode()
    assert deploy.cfn_default(main, "SourceRevision") == HEAD
    assert deploy.cfn_default(main, "InfrastructureRevision") == release.revision
    assert (
        deploy.cfn_default(main, "EditorLauncherArchiveName") == release.launcher_name
    )
    editor = release.files[deploy.EDITOR_TEMPLATE].decode()
    assert deploy.cfn_default(editor, "SourceRevision") == HEAD
    assert set(release.parameters()) == {
        "SourceRevision",
        "InfrastructureRevision",
        "BootstrapScriptSha256",
        "EditorLauncherArchiveName",
        "EditorLauncherCodeSha256",
    }


# ---------------------------------------------------------------- bucket
def test_default_bucket_name():
    assert deploy.default_bucket("123456789012", "us-east-1") == (
        "mosaic-own-account-123456789012-us-east-1"
    )


def test_bucket_is_private_tagged_and_unversioned(tmp_path):
    steps = deploy.bucket_steps(context(tmp_path))
    names = operations(steps)
    for operation in (
        "PutPublicAccessBlock",
        "PutBucketEncryption",
        "PutBucketPolicy",
        "PutBucketTagging",
    ):
        assert ("s3", operation) in names
    assert ("s3", "PutBucketVersioning") not in names
    assert call(steps, "CreateBucket")[2]["CreateBucketConfiguration"] == {
        "LocationConstraint": "us-west-2"
    }
    policy = json.loads(call(steps, "PutBucketPolicy")[2]["Policy"])
    assert policy["Statement"][0]["Condition"] == {
        "Bool": {"aws:SecureTransport": "false"}
    }


def test_tls_policy_follows_the_partition():
    policy = json.loads(deploy.tls_only_policy("b", "aws-cn"))
    assert policy["Statement"][0]["Resource"][0] == "arn:aws-cn:s3:::b"


def test_us_east_1_bucket_has_no_location_constraint(tmp_path):
    steps = deploy.bucket_steps(context(tmp_path, region="us-east-1"))
    assert "CreateBucketConfiguration" not in call(steps, "CreateBucket")[2]


def test_a_missing_bucket_is_created_and_tagged(tmp_path):
    s3 = FakeS3(exists=False, tags=None)
    ctx = live_context(tmp_path, s3, [])
    deploy.ensure_bucket(ctx, {"Bucket": "my-bucket"})
    assert s3.created == {"Bucket": "my-bucket"}
    assert s3.tags == [deploy.OWNER_TAG]


def test_an_existing_tagged_bucket_is_accepted(tmp_path):
    s3 = FakeS3()
    deploy.ensure_bucket(live_context(tmp_path, s3, []), {"Bucket": "my-bucket"})
    assert s3.created is None


@pytest.mark.parametrize("tags", [None, [{"Key": "team", "Value": "x"}]])
def test_an_existing_bucket_without_the_tag_is_refused(tmp_path, tags):
    s3 = FakeS3(tags=tags)
    with pytest.raises(deploy.Refusal, match="lacks the tag MosaicOwnAccount=true"):
        deploy.ensure_bucket(live_context(tmp_path, s3, []), {"Bucket": "my-bucket"})
    assert s3.created is None


def test_a_forbidden_bucket_is_not_treated_as_missing(tmp_path):
    class Forbidden(FakeS3):
        def head_bucket(self, Bucket):
            raise CodedError("403")

    with pytest.raises(CodedError):
        deploy.ensure_bucket(live_context(tmp_path, Forbidden(), []), {"Bucket": "b"})


# ---------------------------------------------------------------- publish and uploads
def test_publish_plan_lists_release_verification_and_global_endpoint(
    tmp_path, clean_tree
):
    plan = deploy.plan_publish(context(tmp_path))
    keys = [s.description for s in plan if s.description.startswith("upload ")]
    release = deploy.build_release(HEAD)
    assert any(
        f"releases/{release.revision}/hybrid-retrieval-staging.yml" in k for k in keys
    )
    assert any(f"releases/{release.revision}/RELEASE.json" in k for k in keys)
    assert any(release.launcher_name in k for k in keys)
    assert len([s for s in plan if s.description.startswith("verify sha256")]) == len(
        keys
    )
    assert plan[-1].calls[0][:2] == ("https", "GET")
    assert (
        plan[-1]
        .calls[0][2]["url"]
        .startswith("https://my-bucket.s3.amazonaws.com/releases/")
    )


def test_publish_without_local_bundle_verifies_the_bucket(
    tmp_path, clean_tree, monkeypatch
):
    monkeypatch.setattr(
        deploy, "expected_bundle", lambda: [("real-catalog/p-000", "a" * 64, 3)]
    )
    plan = deploy.plan_publish(context(tmp_path))
    assert not any(
        c[1] == "PutObject" and "real-catalog" in str(c[2])
        for s in plan
        for c in s.calls
    )
    assert plan[-2].calls == (
        ("s3", "HeadObject", {"Bucket": "my-bucket", "Key": "real-catalog/p-000"}),
    )


def asset(**overrides) -> deploy.Asset:
    values = {"key": "releases/r/x.yml", "sha256": "a" * 64, "size": 3, "data": b"abc"}
    return deploy.Asset(**{**values, **overrides})


def test_an_unchanged_asset_is_not_uploaded(tmp_path):
    s3 = FakeS3({"releases/r/x.yml": (b"abc", {"sha256": "a" * 64})})
    ctx = live_context(tmp_path, s3, [])
    deploy.upload_asset(ctx, asset())
    assert ctx.uploaded == []


@pytest.mark.parametrize(
    "existing",
    [(b"abc", {}), (b"abc", {"sha256": "b" * 64}), (b"abcd", {"sha256": "a" * 64})],
)
def test_an_immutable_key_with_other_content_or_no_metadata_is_refused(
    tmp_path, existing
):
    s3 = FakeS3({"releases/r/x.yml": existing})
    with pytest.raises(deploy.Refusal, match="immutable"):
        deploy.upload_asset(live_context(tmp_path, s3, []), asset())
    assert s3.objects["releases/r/x.yml"] == existing


def test_a_mutable_key_is_overwritten(tmp_path):
    s3 = FakeS3({"releases/r/x.yml": (b"old", {})})
    ctx = live_context(tmp_path, s3, [])
    deploy.upload_asset(ctx, asset(immutable=False))
    assert s3.objects["releases/r/x.yml"] == (b"abc", {"sha256": "a" * 64})


def test_a_forbidden_head_object_is_not_treated_as_absent(tmp_path):
    class Forbidden(FakeS3):
        def head_object(self, Bucket, Key):
            raise CodedError("403")

    with pytest.raises(CodedError):
        deploy.upload_asset(live_context(tmp_path, Forbidden(), []), asset())


# ---------------------------------------------------------------- bundle contracts
def write_contracts(tmp_path: Path, monkeypatch, payload: bytes, claimed: str) -> Path:
    catalog = {
        "parts": [
            {
                "name": "real-catalog.tar.gz.part-000",
                "bytes": len(payload),
                "sha256": claimed,
            }
        ]
    }
    catalog_file = tmp_path / "real-catalog-cache.json"
    vocabulary_file = tmp_path / "corpus-vocabulary-cache.json"
    catalog_file.write_text(json.dumps(catalog))
    vocabulary_file.write_text(
        json.dumps({"schemas": {"mosaic_search": {"tables": {}}}})
    )
    monkeypatch.setattr(deploy, "REAL_CATALOG_CONTRACT", catalog_file)
    monkeypatch.setattr(deploy, "VOCABULARY_CONTRACT", vocabulary_file)
    assets = tmp_path / "assets"
    (assets / "real-catalog").mkdir(parents=True)
    (assets / "real-catalog" / "real-catalog.tar.gz.part-000").write_bytes(payload)
    return assets


def test_local_bundle_matching_the_contract_is_accepted(tmp_path, monkeypatch):
    payload = b"catalog bytes"
    assets = write_contracts(
        tmp_path, monkeypatch, payload, hashlib.sha256(payload).hexdigest()
    )
    assert [f.key for f in deploy.collect_bundle(assets)] == [
        "real-catalog/real-catalog.tar.gz.part-000"
    ]


def test_local_bundle_differing_from_the_contract_is_refused(
    tmp_path, monkeypatch, clean_tree
):
    assets = write_contracts(tmp_path, monkeypatch, b"catalog bytes", "0" * 64)
    with pytest.raises(deploy.Refusal, match="catalog-bundle"):
        deploy.plan_publish(context(tmp_path, assets_dir=assets))


def test_missing_local_bundle_file_is_refused(tmp_path, monkeypatch):
    assets = write_contracts(
        tmp_path, monkeypatch, b"x", hashlib.sha256(b"x").hexdigest()
    )
    (assets / "real-catalog" / "real-catalog.tar.gz.part-000").unlink()
    with pytest.raises(deploy.Refusal, match="missing"):
        deploy.collect_bundle(assets)


ONE_PART = [("real-catalog/p-000", "a" * 64, 3)]


def test_bucket_bundle_matching_the_contracts_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "expected_bundle", lambda: ONE_PART)
    s3 = FakeS3({"real-catalog/p-000": (b"abc", {"sha256": "a" * 64})})
    lines: list[str] = []
    deploy.verify_bucket_bundle(live_context(tmp_path, s3, lines))
    assert "bundle verified" in lines[-1]


@pytest.mark.parametrize(
    ("objects", "message"),
    [
        ({}, "not in the bucket"),
        ({"real-catalog/p-000": (b"ab", {"sha256": "a" * 64})}, "bucket has 2 bytes"),
        ({"real-catalog/p-000": (b"abc", {"sha256": "b" * 64})}, "metadata sha256"),
        ({"real-catalog/p-000": (b"abc", {})}, "metadata sha256"),
    ],
)
def test_bucket_bundle_mismatch_is_refused(tmp_path, monkeypatch, objects, message):
    monkeypatch.setattr(deploy, "expected_bundle", lambda: ONE_PART)
    with pytest.raises(deploy.Refusal, match=message):
        deploy.verify_bucket_bundle(live_context(tmp_path, FakeS3(objects), []))


# ---------------------------------------------------------------- contracts pull
CATALOG_BODY = json.dumps(
    {"parts": [{"name": "p-000", "bytes": 3, "sha256": "a" * 64}]}
).encode()
VOCAB_BODY = json.dumps(
    {"schemas": {"s": {"tables": {"t": {"bytes": 2, "sha256": "b" * 64}}}}}
).encode()
CONTRACT_KEYS = (
    "contracts/real-catalog-cache.json",
    "contracts/corpus-vocabulary-cache.json",
)


def pull_fixture(tmp_path: Path, monkeypatch, *, metadata=True, bundle=True):
    (tmp_path / "db").mkdir(exist_ok=True)
    targets = {
        CONTRACT_KEYS[0]: tmp_path / "db" / "real.json",
        CONTRACT_KEYS[1]: tmp_path / "db" / "vocab.json",
    }
    monkeypatch.setattr(deploy, "CONTRACT_FILES", targets)
    monkeypatch.setattr(deploy, "REPO", tmp_path)

    def meta(body):
        return {"sha256": hashlib.sha256(body).hexdigest()} if metadata else {}

    objects = {
        CONTRACT_KEYS[0]: (CATALOG_BODY, meta(CATALOG_BODY)),
        CONTRACT_KEYS[1]: (VOCAB_BODY, meta(VOCAB_BODY)),
    }
    if bundle:
        objects["real-catalog/p-000"] = (b"abc", {"sha256": "a" * 64})
        objects["real-catalog/vocabulary/s.t.csv.gz"] = (b"bb", {"sha256": "b" * 64})
    return targets, objects


def test_contracts_pull_plan_reads_both_contract_keys(tmp_path):
    plan = deploy.plan_contracts_pull(context(tmp_path))
    assert [c[2]["Key"] for c in plan[0].calls] == list(CONTRACT_KEYS)


def test_contracts_pull_writes_both_files_atomically_and_prints_git_commands(
    tmp_path, monkeypatch
):
    targets, objects = pull_fixture(tmp_path, monkeypatch)
    lines: list[str] = []
    deploy.pull_contracts(live_context(tmp_path, FakeS3(objects), lines))
    assert targets[CONTRACT_KEYS[0]].read_bytes() == CATALOG_BODY
    assert targets[CONTRACT_KEYS[1]].read_bytes() == VOCAB_BODY
    assert not list((tmp_path / "db").glob("*.tmp"))
    assert any("git commit" in line and "git push" in line for line in lines)
    lines.clear()
    deploy.pull_contracts(live_context(tmp_path, FakeS3(objects), lines))
    assert sum("unchanged" in line for line in lines) == 2


def test_contracts_pull_refuses_when_the_bucket_has_none(tmp_path, monkeypatch):
    targets, _ = pull_fixture(tmp_path, monkeypatch)
    with pytest.raises(deploy.Refusal, match="does not exist"):
        deploy.pull_contracts(live_context(tmp_path, FakeS3({}), []))
    assert not any(path.exists() for path in targets.values())


def test_contracts_pull_requires_sha256_metadata(tmp_path, monkeypatch):
    targets, objects = pull_fixture(tmp_path, monkeypatch, metadata=False)
    with pytest.raises(deploy.Refusal, match="no sha256 metadata"):
        deploy.pull_contracts(live_context(tmp_path, FakeS3(objects), []))
    assert not any(path.exists() for path in targets.values())


def test_contracts_pull_refuses_a_corrupted_object(tmp_path, monkeypatch):
    _, objects = pull_fixture(tmp_path, monkeypatch)
    objects[CONTRACT_KEYS[0]] = (CATALOG_BODY, {"sha256": "0" * 64})
    with pytest.raises(deploy.Refusal, match="recorded sha256"):
        deploy.pull_contracts(live_context(tmp_path, FakeS3(objects), []))


def test_contracts_pull_validates_the_bundle_before_writing_anything(
    tmp_path, monkeypatch
):
    targets, objects = pull_fixture(tmp_path, monkeypatch, bundle=False)
    with pytest.raises(deploy.Refusal, match="nothing was written"):
        deploy.pull_contracts(live_context(tmp_path, FakeS3(objects), []))
    assert not any(path.exists() for path in targets.values())


def test_a_malformed_contract_is_refused(tmp_path, monkeypatch):
    with pytest.raises(deploy.Refusal, match="malformed"):
        deploy.expected_bundle({"nothing": 1}, {"schemas": {}})


# ---------------------------------------------------------------- stacks
def test_deploy_plan_passes_every_parameter_explicitly(tmp_path, clean_tree):
    plan = deploy.plan_deploy(context(tmp_path))
    create = call(plan, "CreateStack")
    params = {p["ParameterKey"]: p["ParameterValue"] for p in create[2]["Parameters"]}
    release = deploy.build_release(HEAD)
    assert params == {
        "WorkshopName": "mosaic-hybrid-retrieval",
        "RepoUrl": "https://github.com/me/fork.git",
        **release.parameters(),
        "AssetsBucketName": "my-bucket",
        "AssetsBucketPrefix": "",
        "PublicAssetsBucketName": "",
        "PublicAssetsBucketPrefix": "",
    }
    assert "CAPABILITY_NAMED_IAM" in create[2]["Capabilities"]
    assert create[2]["TemplateURL"].endswith(
        f"/releases/{release.revision}/{deploy.MAIN_TEMPLATE}"
    )


def test_deploy_and_staging_up_check_before_they_create(tmp_path, clean_tree):
    for plan in (
        deploy.plan_deploy(context(tmp_path)),
        deploy.plan_staging_up(context(tmp_path)),
    ):
        names = operations(plan)
        assert names[0] == ("cloudformation", "DescribeStacks")
        assert names.index(("iam", "CreateServiceLinkedRole")) < names.index(
            ("cloudformation", "CreateStack")
        )
        assert any(c[0] == "git" for step in plan for c in step.calls)


def test_staging_up_checks_the_stack_and_creates_the_bucket_before_any_upload(
    tmp_path, clean_tree
):
    plan = deploy.plan_staging_up(context(tmp_path))
    names = operations(plan)
    assert names[0] == ("cloudformation", "DescribeStacks")
    assert names.index(("s3", "CreateBucket")) < names.index(("s3", "PutObject"))
    params = {
        p["ParameterKey"]: p["ParameterValue"]
        for p in call(plan, "CreateStack")[2]["Parameters"]
    }
    assert params["AssetsBucketName"] == "my-bucket"
    assert params["AssetsBucketPrefix"] == ""
    assert call(plan, "CreateStack")[2]["TemplateURL"].endswith(deploy.STAGING_TEMPLATE)


class FakeCloudformation:
    def __init__(self, statuses, events=()):
        self.statuses = list(statuses)
        self.events = list(events)

    def describe_stacks(self, StackName):
        if not self.statuses:
            raise CodedError("ValidationError", f"Stack {StackName} does not exist")
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if status is None:
            raise CodedError("ValidationError", f"Stack {StackName} does not exist")
        return {"Stacks": [{"StackName": StackName, "StackStatus": status}]}

    def describe_stack_events(self, StackName):
        return {"StackEvents": self.events}


def test_an_existing_stack_is_refused_naming_the_fixes(tmp_path):
    ctx = live_context(tmp_path, FakeCloudformation(["CREATE_COMPLETE"]), [])
    with pytest.raises(deploy.Refusal, match="status.*teardown.*--stack-name"):
        deploy.refuse_existing_stack(ctx)


def test_an_absent_stack_passes_the_existence_check(tmp_path):
    deploy.refuse_existing_stack(live_context(tmp_path, FakeCloudformation([None]), []))


def test_wait_returns_on_the_goal_status(tmp_path, no_sleep):
    cloudformation = FakeCloudformation(["CREATE_IN_PROGRESS", "CREATE_COMPLETE"])
    deploy.wait_for_stack(live_context(tmp_path, cloudformation, []), "CREATE_COMPLETE")


def test_a_rollback_is_waited_out_then_reported_with_the_first_failure(
    tmp_path, no_sleep
):
    events = [
        {
            "LogicalResourceId": "Late",
            "ResourceStatus": "DELETE_FAILED",
            "ResourceStatusReason": "later",
        },
        {
            "LogicalResourceId": "DatabaseStack",
            "ResourceStatus": "CREATE_FAILED",
            "ResourceStatusReason": "first cause",
        },
    ]
    cloudformation = FakeCloudformation(
        [
            "CREATE_IN_PROGRESS",
            "ROLLBACK_IN_PROGRESS",
            "ROLLBACK_IN_PROGRESS",
            "ROLLBACK_COMPLETE",
        ],
        events,
    )
    lines: list[str] = []
    with pytest.raises(deploy.Refusal, match="ROLLBACK_COMPLETE"):
        deploy.wait_for_stack(
            live_context(tmp_path, cloudformation, lines), "CREATE_COMPLETE"
        )
    assert cloudformation.statuses[0] == "ROLLBACK_COMPLETE"
    assert lines.index("    DatabaseStack: CREATE_FAILED: first cause") < len(lines)
    assert lines[-2].startswith("    DatabaseStack")


def test_rollback_in_progress_alone_is_not_terminal(tmp_path, no_sleep):
    cloudformation = FakeCloudformation(["ROLLBACK_IN_PROGRESS", "CREATE_COMPLETE"])
    deploy.wait_for_stack(live_context(tmp_path, cloudformation, []), "CREATE_COMPLETE")


def test_delete_wait_ends_when_the_stack_is_gone(tmp_path, no_sleep):
    cloudformation = FakeCloudformation(["DELETE_IN_PROGRESS", None])
    deploy.wait_for_stack(live_context(tmp_path, cloudformation, []), "DELETE_COMPLETE")


def test_delete_failed_is_terminal(tmp_path, no_sleep):
    with pytest.raises(deploy.Refusal, match="DELETE_FAILED"):
        deploy.wait_for_stack(
            live_context(tmp_path, FakeCloudformation(["DELETE_FAILED"]), []),
            "DELETE_COMPLETE",
        )


def test_interrupting_a_wait_says_the_stack_keeps_going(tmp_path, monkeypatch):
    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(deploy.time, "sleep", interrupt)
    lines: list[str] = []
    ctx = live_context(tmp_path, FakeCloudformation(["CREATE_IN_PROGRESS"]), lines)
    with pytest.raises(KeyboardInterrupt):
        deploy.wait_for_stack(ctx, "CREATE_COMPLETE")
    assert "keeps going" in lines[-1]
    assert "status" in lines[-1]


def test_tokens_are_redacted_in_status_output(tmp_path):
    class Cloudformation:
        def describe_stacks(self, StackName):
            output = {
                "OutputKey": "CodeEditorURL",
                "OutputValue": "https://x/?tkn=SECRET",
            }
            return {
                "Stacks": [
                    {
                        "StackName": StackName,
                        "StackStatus": "CREATE_COMPLETE",
                        "Outputs": [output],
                    }
                ]
            }

    lines: list[str] = []
    ctx = live_context(tmp_path, Cloudformation(), lines)
    deploy.print_outputs(ctx, show_token=False)
    assert "SECRET" not in "\n".join(lines)
    deploy.print_outputs(ctx, show_token=True)
    assert "SECRET" in "\n".join(lines)


# ---------------------------------------------------------------- global endpoint
def test_global_endpoint_wait_polls_until_it_stops_redirecting(
    tmp_path, monkeypatch, no_sleep
):
    answers = iter([307, 307, 200])
    monkeypatch.setattr(deploy, "signed_status", lambda _ctx, _url: next(answers))
    lines: list[str] = []
    deploy.wait_for_global_endpoint(
        live_context(tmp_path, FakeS3(), lines), deploy.build_release(HEAD)
    )
    assert lines.count("    waiting for the bucket's global endpoint ...") == 2
    assert "answers" in lines[-1]


def test_global_endpoint_wait_is_skipped_in_us_east_1(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "signed_status", lambda *_: pytest.fail("polled"))
    ctx = live_context(tmp_path, FakeS3(), [], region="us-east-1")
    deploy.wait_for_global_endpoint(ctx, deploy.build_release(HEAD))


def test_global_endpoint_forbidden_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "signed_status", lambda *_: 403)
    with pytest.raises(deploy.Refusal, match="HTTP 403"):
        deploy.wait_for_global_endpoint(
            live_context(tmp_path, FakeS3(), []), deploy.build_release(HEAD)
        )


# ---------------------------------------------------------------- staging down and teardown
def contract_objects(*, metadata: bool = True) -> dict:
    return {key: (b"x", {"sha256": "0"} if metadata else {}) for key in CONTRACT_KEYS}


def test_staging_down_plan_checks_the_contracts_then_deletes_and_reports(tmp_path):
    plan = deploy.plan_staging_down(context(tmp_path))
    names = operations(plan)
    assert [c[2]["Key"] for c in plan[0].calls] == list(CONTRACT_KEYS)
    assert names.index(("s3", "HeadObject")) < names.index(
        ("cloudformation", "DeleteStack")
    )
    assert plan[-1].description == "report what the stack leaves behind"
    assert "safe" in plan[0].description


def test_staging_down_ignores_the_committed_contracts_part_list(tmp_path, monkeypatch):
    monkeypatch.setattr(
        deploy,
        "expected_bundle",
        lambda: pytest.fail("the committed contract was read"),
    )
    deploy.plan_staging_down(context(tmp_path))
    deploy.require_bundle_uploaded(
        live_context(tmp_path, FakeS3(contract_objects()), []), force=False
    )


def test_staging_down_refuses_while_a_contract_is_missing(tmp_path):
    objects = contract_objects()
    del objects[CONTRACT_KEYS[1]]
    with pytest.raises(deploy.Refusal, match="corpus-vocabulary-cache.json"):
        deploy.require_bundle_uploaded(
            live_context(tmp_path, FakeS3(objects), []), force=False
        )


def test_staging_down_refuses_a_contract_without_sha256_metadata(tmp_path):
    with pytest.raises(deploy.Refusal, match="sha256 metadata"):
        deploy.require_bundle_uploaded(
            live_context(tmp_path, FakeS3(contract_objects(metadata=False)), []),
            force=False,
        )


def test_staging_down_force_overrides(tmp_path):
    lines: list[str] = []
    deploy.require_bundle_uploaded(
        live_context(tmp_path, FakeS3({}), lines), force=True
    )
    assert "--force" in lines[-1]


def test_teardown_plan_keeps_bucket_by_default(tmp_path):
    plan = deploy.plan_teardown(context(tmp_path), delete_bucket=False)
    assert ("cloudformation", "DeleteStack") in operations(plan)
    assert ("s3", "DeleteBucket") not in operations(plan)
    assert "keep bucket" in plan[-1].description


def test_teardown_deletes_a_prefixed_bucket_on_request(tmp_path):
    ctx = context(tmp_path, bucket="mosaic-own-account-1-us-east-1")
    assert operations(deploy.plan_teardown(ctx, delete_bucket=True))[-1] == (
        "s3",
        "DeleteBucket",
    )


def test_teardown_refuses_to_empty_an_unrelated_bucket_name(tmp_path):
    with pytest.raises(deploy.Refusal, match="neither"):
        deploy.plan_teardown(
            context(tmp_path, bucket="company-data"), delete_bucket=True
        )


def test_an_explicit_bucket_name_is_the_second_guard(tmp_path):
    ctx = context(tmp_path, bucket="company-data", bucket_explicit=True)
    assert deploy.plan_teardown(ctx, delete_bucket=True)


def test_emptying_refuses_an_untagged_bucket(tmp_path):
    s3 = FakeS3({"k": (b"x", {})}, tags=None)
    with pytest.raises(deploy.Refusal, match="did not create it"):
        deploy.empty_and_delete_bucket(live_context(tmp_path, s3, []))
    assert s3.deleted == [] and not s3.bucket_deleted


def test_emptying_deletes_objects_then_the_bucket(tmp_path):
    s3 = FakeS3({"k": (b"x", {})})
    deploy.empty_and_delete_bucket(live_context(tmp_path, s3, []))
    assert s3.deleted == [{"Key": "k", "VersionId": "1"}]
    assert s3.bucket_deleted


def test_emptying_raises_on_delete_objects_errors(tmp_path):
    s3 = FakeS3({"k": (b"x", {})})
    s3.delete_errors = [{"Key": "k", "Code": "AccessDenied"}]
    with pytest.raises(deploy.Refusal, match="k \\(AccessDenied\\)"):
        deploy.empty_and_delete_bucket(live_context(tmp_path, s3, []))
    assert not s3.bucket_deleted


def test_bucket_not_empty_is_named(tmp_path):
    s3 = FakeS3()
    s3.delete_bucket_error = "BucketNotEmpty"
    with pytest.raises(deploy.Refusal, match="is not empty"):
        deploy.empty_and_delete_bucket(live_context(tmp_path, s3, []))


def test_a_vanished_cluster_does_not_abort_the_teardown(tmp_path, monkeypatch):
    class Rds:
        def describe_db_clusters(self, DBClusterIdentifier):
            raise CodedError("DBClusterNotFoundFault")

    def collect(ctx, stack, found):
        found["AWS::RDS::DBCluster"] = ["gone-cluster"]

    monkeypatch.setattr(deploy, "collect_resources", collect)
    lines: list[str] = []
    deploy.discover_resources(live_context(tmp_path, Rds(), lines))
    assert any("could not describe cluster gone-cluster" in line for line in lines)


def test_leftover_report_lists_log_groups_and_streams(tmp_path):
    class Logs:
        def get_paginator(self, _name):
            class Paginator:
                def paginate(self, logGroupNamePrefix):
                    names = {
                        "/aws/rds/cluster/c1/": ["/aws/rds/cluster/c1/postgresql"],
                        "mosaic-staging-BuilderLogs-": ["mosaic-staging-BuilderLogs-X"],
                    }.get(logGroupNamePrefix, [])
                    yield {"logGroups": [{"logGroupName": n} for n in names]}

            return Paginator()

    lines: list[str] = []
    ctx = live_context(tmp_path, Logs(), lines, stack_name="mosaic-staging")
    ctx.discovered = {
        "AWS::RDS::DBCluster": ["c1"],
        "DbClusterResourceId": ["cluster-ABC"],
    }
    deploy.report_leftovers(ctx)
    text = "\n".join(lines)
    assert "/aws/rds/cluster/c1/postgresql" in text
    assert "mosaic-staging-BuilderLogs-X" in text
    assert "RDSOSMetrics streams starting cluster-ABC" in text
    assert "7-day deletion window" in text


def test_dry_run_prints_calls_and_makes_none(tmp_path):
    lines: list[str] = []
    ctx = context(tmp_path, out=lines.append, bucket="mosaic-own-account-1-us-west-2")
    ctx.client_factory = lambda _service: pytest.fail("dry run created an AWS client")
    deploy.run_plan(deploy.plan_teardown(ctx, delete_bucket=True), ctx)
    assert any("cloudformation.DeleteStack" in line for line in lines)
    assert lines[-1] == "dry run: no AWS call was made"


# ---------------------------------------------------------------- source checks
def test_dirty_tree_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "git", lambda *args, **kwargs: " M README.md")
    with pytest.raises(deploy.Refusal, match="uncommitted changes"):
        deploy.plan_deploy(context(tmp_path, dry_run=False))


def test_dry_run_warns_on_a_dirty_tree_and_continues(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "git", lambda *args, **kwargs: " M README.md")
    lines: list[str] = []
    plan = deploy.plan_deploy(context(tmp_path, out=lines.append))
    assert plan
    assert any(line.startswith("warning (dry run") for line in lines)


def test_source_revision_must_be_checked_out(monkeypatch):
    monkeypatch.setattr(deploy, "git", lambda *args, **kwargs: "b" * 40)
    with pytest.raises(deploy.Refusal, match="not the checked-out commit"):
        deploy.require_head(HEAD)


def test_repo_url_forms_are_normalized():
    assert (
        deploy.normalize_repo_url("git@github.com:me/fork")
        == "https://github.com/me/fork.git"
    )


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:me/fork.git",
        "http://github.com/me/fork.git",
        "https://github.com/me/fork",
        "https://gitlab.com/me/fork.git",
    ],
)
def test_repo_url_must_be_https_github_dot_git(url):
    with pytest.raises(deploy.Refusal, match="HTTPS GitHub URL"):
        deploy.validate_repo_url(url)


def test_the_templates_accept_exactly_what_the_tool_accepts():
    for name in (deploy.MAIN_TEMPLATE, deploy.EDITOR_TEMPLATE):
        text = (CLOUDFORMATION / name).read_text()
        pattern = re.search(
            r"RepoUrl:\n(?:    .*\n)*?    AllowedPattern: '(.*)'", text
        ).group(1)
        assert re.fullmatch(pattern, "https://github.com/me/fork.git")
        assert not re.fullmatch(pattern, "https://github.com/me/fork")


def recorded_runs(monkeypatch, outcome=None, error=None):
    calls: list = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if error:
            raise error
        return outcome or subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(deploy.subprocess, "run", run)
    return calls


def test_the_anonymous_probe_ignores_user_git_configuration(monkeypatch):
    calls = recorded_runs(monkeypatch)
    assert deploy.probe_anonymous_fetch("https://github.com/me/f.git", HEAD) is None
    env = calls[0][1]["env"]
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert all(
        kwargs["timeout"] == deploy.GIT_PROBE_TIMEOUT_SECONDS for _, kwargs in calls
    )
    assert "credential.helper=" in calls[2][0]


def test_the_probe_reports_a_missing_git_and_a_timeout(monkeypatch):
    recorded_runs(monkeypatch, error=FileNotFoundError())
    assert "not installed" in deploy.probe_anonymous_fetch("u", HEAD)
    recorded_runs(monkeypatch, error=subprocess.TimeoutExpired("git", 1))
    assert "timed out" in deploy.probe_anonymous_fetch("u", HEAD)


def test_the_probe_reports_the_last_stderr_line(monkeypatch):
    failed = subprocess.CompletedProcess(
        [], 128, "", "noise\nfatal: repository not found"
    )
    recorded_runs(monkeypatch, outcome=failed)
    assert deploy.probe_anonymous_fetch("u", HEAD) == "fatal: repository not found"


def test_the_probe_step_refuses_a_fork_the_host_cannot_clone(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "probe_anonymous_fetch", lambda *_: "fatal: not found")
    with pytest.raises(deploy.Refusal, match="anonymously"):
        deploy.probe_step(context(tmp_path)).run(context(tmp_path))


# ---------------------------------------------------------------- check
def test_check_probes_the_requested_region(tmp_path, monkeypatch):
    calls = recorded_runs(monkeypatch)
    deploy.check_models(live_context(tmp_path, FakeS3(), [], region="us-west-2"))
    command = calls[0][0]
    assert command[command.index("--region") + 1] == "us-west-2"


class FakeIam:
    def __init__(self, existing=(), get_error=None):
        self.existing = set(existing)
        self.created: list[str] = []
        self.get_error = get_error

    def get_role(self, RoleName):
        if self.get_error:
            raise CodedError(self.get_error)
        if RoleName not in self.existing:
            raise CodedError("NoSuchEntity")

    def create_service_linked_role(self, AWSServiceName):
        self.created.append(AWSServiceName)
        self.existing.add(deploy.SERVICE_LINKED_ROLES[AWSServiceName])


def test_check_reports_missing_roles_without_creating_them(tmp_path):
    iam = FakeIam(existing={"AWSServiceRoleForRDS"})
    lines: list[str] = []
    deploy.check_service_linked_roles(live_context(tmp_path, iam, lines))
    assert iam.created == []
    assert any(
        line.startswith("FAIL") and "CloudFrontVPCOrigin" in line for line in lines
    )
    assert any(
        line.startswith("ok") and "AWSServiceRoleForRDS" in line for line in lines
    )


def test_check_names_the_permission_when_get_role_is_denied(tmp_path):
    lines: list[str] = []
    deploy.check_service_linked_roles(
        live_context(tmp_path, FakeIam(get_error="AccessDenied"), lines)
    )
    assert any("iam:GetRole" in line for line in lines)


def test_deploy_creates_only_the_missing_roles(tmp_path):
    iam = FakeIam(existing={"AWSServiceRoleForRDS"})
    deploy.ensure_service_linked_roles(live_context(tmp_path, iam, []))
    assert iam.created == ["vpcorigin.cloudfront.amazonaws.com"]


def test_a_taken_role_name_on_create_is_accepted_if_the_role_exists(tmp_path):
    class Racing(FakeIam):
        def create_service_linked_role(self, AWSServiceName):
            self.existing.add(deploy.SERVICE_LINKED_ROLES[AWSServiceName])
            raise CodedError("InvalidInput", "Service role name X has been taken")

    deploy.ensure_service_linked_roles(live_context(tmp_path, Racing(), []))


def test_check_plan_only_reads_iam(tmp_path):
    plan = deploy.plan_check(context(tmp_path))
    assert ("iam", "CreateServiceLinkedRole") not in operations(plan)
    assert ("iam", "GetRole") in operations(plan)


def test_quota_report_uses_the_instance_types_and_says_the_stacks_are_not_together(
    tmp_path,
):
    class Quotas:
        def get_service_quota(self, ServiceCode, QuotaCode):
            return {"Quota": {"Value": 32}}

    lines: list[str] = []
    deploy.check_quota(live_context(tmp_path, Quotas(), lines))
    assert "c7g.2xlarge" in lines[-1]
    assert "c6g.2xlarge" in lines[-1]
    assert "not up together" in lines[-1]


# ---------------------------------------------------------------- command line
def parse(*argv: str):
    return deploy.build_parser().parse_args(list(argv))


def test_region_falls_back_to_the_environment(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    assert deploy.resolve_region(parse("status")) == "eu-west-1"
    assert (
        deploy.resolve_region(parse("status", "--region", "us-west-2")) == "us-west-2"
    )


def test_commands_that_do_not_deploy_skip_the_repo_checks(monkeypatch):
    monkeypatch.setattr(deploy, "git", lambda *a, **k: pytest.fail("git was called"))
    for argv in (
        ["status"],
        ["teardown"],
        ["contracts", "pull"],
        ["staging", "down"],
        ["staging", "status"],
    ):
        ctx = deploy.make_context(parse(*argv, "--dry-run", "--region", "us-east-1"))
        assert ctx.repo_url == ""
        assert ctx.source_revision == ""


def test_commands_that_deploy_resolve_the_commit_with_rev_parse_verify(monkeypatch):
    seen: list = []

    def fake_git(*arguments, **kwargs):
        seen.append(arguments)
        return "c" * 40

    monkeypatch.setattr(deploy, "git", fake_git)
    args = parse(
        "publish",
        "--dry-run",
        "--region",
        "us-east-1",
        "--repo-url",
        "https://github.com/me/f.git",
        "--source-revision",
        "main",
    )
    ctx = deploy.make_context(args)
    assert seen == [("rev-parse", "--verify", "main^{commit}")]
    assert ctx.source_revision == "c" * 40


def test_outside_a_repository_the_refusal_is_clear(monkeypatch, capsys):
    def fail(*command, **kwargs):
        raise subprocess.CalledProcessError(
            128, command, stderr="fatal: not a git repository"
        )

    monkeypatch.setattr(deploy.subprocess, "run", fail)
    code = deploy.main(
        [
            "publish",
            "--dry-run",
            "--region",
            "us-east-1",
            "--repo-url",
            "https://github.com/me/f.git",
        ]
    )
    assert code == 2
    assert "REFUSED" in capsys.readouterr().err


def test_an_invalid_repo_url_is_refused_by_the_commands_that_clone(capsys):
    code = deploy.main(["deploy", "--dry-run", "--repo-url", "git@github.com:me/f.git"])
    assert code == 2
    assert "HTTPS GitHub URL" in capsys.readouterr().err


def client_error(operation: str, code: str, message: str = "boom") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


@pytest.mark.parametrize(
    ("operation", "code", "expected"),
    [
        ("HeadObject", "403", "s3:ListBucket"),
        ("CreateStack", "AlreadyExistsException", "--stack-name"),
        ("CreateBucket", "BucketAlreadyExists", "--bucket"),
        ("DescribeStacks", "ExpiredToken", "refresh your AWS credentials"),
    ],
)
def test_client_errors_become_a_refusal_with_a_fix(
    monkeypatch, capsys, operation, code, expected
):
    def explode(_args):
        raise client_error(operation, code)

    monkeypatch.setattr(deploy, "make_context", explode)
    assert deploy.main(["status"]) == 2
    err = capsys.readouterr().err
    assert err.startswith(f"REFUSED: {operation} {code}: boom")
    assert expected in err
    assert "Traceback" not in err


def test_interrupt_returns_130(monkeypatch):
    def interrupt(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(deploy, "make_context", interrupt)
    assert deploy.main(["status"]) == 130


# ---------------------------------------------------------------- published release (deploy)
def test_deploy_heads_the_published_release_before_creating_the_stack(
    tmp_path, clean_tree
):
    release = deploy.build_release(HEAD)
    for region in ("us-east-1", "us-west-2"):
        plan = deploy.plan_deploy(context(tmp_path, region=region))
        names = operations(plan)
        heads = [
            c[2]["Key"] for step in plan for c in step.calls if c[1] == "HeadObject"
        ]
        assert heads == [
            f"releases/{release.revision}/RELEASE.json",
            f"releases/{release.revision}/mosaic-bootstrap.sh",
            f"releases/{release.revision}/{deploy.MAIN_TEMPLATE}",
            release.launcher_name,
        ]
        assert names.index(("s3", "HeadObject")) < names.index(
            ("cloudformation", "CreateStack")
        )


def published(release) -> dict:
    return {key: (b"x", {}) for key in deploy.published_release_keys(release)}


def test_deploy_refuses_when_the_release_is_not_published(tmp_path):
    release = deploy.build_release(HEAD)
    objects = published(release)
    del objects[release.launcher_name]
    for region in ("us-east-1", "us-west-2"):
        ctx = live_context(tmp_path, FakeS3(objects), [], region=region)
        with pytest.raises(deploy.Refusal, match="Run publish first") as refusal:
            deploy.require_published_release(ctx, release)
        assert release.launcher_name in str(refusal.value)


def test_deploy_accepts_a_published_release(tmp_path):
    release = deploy.build_release(HEAD)
    ctx = live_context(tmp_path, FakeS3(published(release)), [], region="us-east-1")
    deploy.require_published_release(ctx, release)


# ---------------------------------------------------------------- signed_status
def test_signed_status_turns_network_errors_into_a_retryable_answer(
    tmp_path, monkeypatch
):
    from botocore.credentials import Credentials

    ctx = context(tmp_path)
    monkeypatch.setattr(
        ctx, "session_credentials", lambda: Credentials("AKIA", "secret")
    )

    class Opener:
        def open(self, *_args, **_kwargs):
            raise urllib.error.URLError("name not resolved")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: Opener())
    assert (
        deploy.signed_status(ctx, "https://b.s3.amazonaws.com/k")
        == deploy.NETWORK_ERROR
    )


def test_global_endpoint_wait_retries_after_a_network_error(
    tmp_path, monkeypatch, no_sleep
):
    answers = iter([deploy.NETWORK_ERROR, 307, 200])
    monkeypatch.setattr(deploy, "signed_status", lambda _ctx, _url: next(answers))
    lines: list[str] = []
    deploy.wait_for_global_endpoint(
        live_context(tmp_path, FakeS3(), lines), deploy.build_release(HEAD)
    )
    assert "answers" in lines[-1]


def test_global_endpoint_wait_reports_the_last_answer_not_only_redirects(
    tmp_path, monkeypatch, no_sleep
):
    clock = iter(range(0, 10_000, 400))
    monkeypatch.setattr(deploy.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(deploy, "signed_status", lambda *_: 400)
    with pytest.raises(deploy.Refusal, match=r"last gave HTTP 400 \(or a redirect\)"):
        deploy.wait_for_global_endpoint(
            live_context(tmp_path, FakeS3(), []), deploy.build_release(HEAD)
        )


# ---------------------------------------------------------------- contracts pull crash safety
def test_contracts_pull_stages_both_files_before_replacing_and_cleans_up(
    tmp_path, monkeypatch
):
    _, objects = pull_fixture(tmp_path, monkeypatch)
    staged_at_first_replace: list[int] = []
    real_replace = deploy.os.replace

    def failing_replace(source, destination):
        staged_at_first_replace.append(len(list((tmp_path / "db").glob("*.tmp"))))
        if len(staged_at_first_replace) == 2:
            raise OSError("disk full")
        real_replace(source, destination)

    monkeypatch.setattr(deploy.os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk full"):
        deploy.pull_contracts(live_context(tmp_path, FakeS3(objects), []))
    assert staged_at_first_replace[0] == 2
    assert not list((tmp_path / "db").glob("*.tmp"))


def test_contracts_pull_cleans_up_when_writing_a_temp_file_fails(tmp_path, monkeypatch):
    _, objects = pull_fixture(tmp_path, monkeypatch)
    original = Path.write_bytes
    writes: list[Path] = []

    def flaky(self, data):
        writes.append(self)
        if len(writes) == 2:
            raise OSError("no space")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", flaky)
    with pytest.raises(OSError, match="no space"):
        deploy.pull_contracts(live_context(tmp_path, FakeS3(objects), []))
    assert not list((tmp_path / "db").glob("*.tmp"))


# ---------------------------------------------------------------- delete wait
def test_a_stale_terminal_status_is_not_a_failed_delete(tmp_path, no_sleep):
    cloudformation = FakeCloudformation(
        ["ROLLBACK_COMPLETE", "DELETE_IN_PROGRESS", None]
    )
    lines: list[str] = []
    deploy.wait_for_stack(
        live_context(tmp_path, cloudformation, lines), "DELETE_COMPLETE"
    )
    assert "ROLLBACK_COMPLETE ..." in "".join(lines)


def test_delete_failed_is_terminal_even_before_delete_in_progress(tmp_path, no_sleep):
    with pytest.raises(deploy.Refusal, match="DELETE_FAILED"):
        deploy.wait_for_stack(
            live_context(tmp_path, FakeCloudformation(["DELETE_FAILED"]), []),
            "DELETE_COMPLETE",
        )


def test_a_delete_that_never_starts_is_reported_after_a_grace_period(
    tmp_path, monkeypatch
):
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(deploy.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)
    with pytest.raises(deploy.Refusal, match="never began deleting"):
        deploy.wait_for_stack(
            live_context(tmp_path, FakeCloudformation(["ROLLBACK_COMPLETE"]), []),
            "DELETE_COMPLETE",
        )


def test_create_waits_still_treat_rollback_complete_as_failure(tmp_path, no_sleep):
    with pytest.raises(deploy.Refusal, match="ROLLBACK_COMPLETE"):
        deploy.wait_for_stack(
            live_context(tmp_path, FakeCloudformation(["ROLLBACK_COMPLETE"]), []),
            "CREATE_COMPLETE",
        )


# ---------------------------------------------------------------- staging template (parsed)
class CloudFormationLoader(yaml.SafeLoader):
    """Reads CloudFormation's short tags (!Sub, !Ref, ...) as their long-form mappings."""


def short_tag(loader, suffix, node):
    name = "Ref" if suffix == "Ref" else f"Fn::{suffix}"
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {name: value}


CloudFormationLoader.add_multi_constructor("!", short_tag)


def staging_template() -> dict:
    text = (CLOUDFORMATION / deploy.STAGING_TEMPLATE).read_text()
    return yaml.load(text, Loader=CloudFormationLoader)


def role_statements() -> dict:
    resources = staging_template()["Resources"]
    document = resources["BuilderRole"]["Properties"]["Policies"][0]["PolicyDocument"]
    return {statement["Sid"]: statement for statement in document["Statement"]}


def user_data() -> str:
    resources = staging_template()["Resources"]
    return resources["BuilderInstance"]["Properties"]["UserData"]["Fn::Base64"][
        "Fn::Sub"
    ][0]


def test_staging_role_reads_and_writes_only_the_bundle_prefixes():
    statement = role_statements()["ReadWriteBundleObjects"]
    assert sorted(statement["Action"]) == ["s3:GetObject", "s3:PutObject"]
    resources = [r["Fn::Sub"] for r in statement["Resource"]]
    assert len(resources) == 2
    assert resources[0].endswith("/${AssetsBucketPrefix}real-catalog/*")
    assert resources[1].endswith("/${AssetsBucketPrefix}contracts/*")


def test_staging_role_lists_the_bucket_without_a_prefix_condition():
    statement = role_statements()["ListBucketForHeadObject"]
    assert statement["Action"] == "s3:ListBucket"
    assert "Condition" not in statement
    assert statement["Resource"]["Fn::Sub"].endswith(":s3:::${AssetsBucketName}")


def test_staging_role_limits_kms_decrypt_to_secrets_manager_in_this_account():
    statement = role_statements()["DecryptSecretThroughSecretsManager"]
    condition = statement["Condition"]["StringEquals"]
    assert statement["Action"] == "kms:Decrypt"
    assert set(condition) == {"kms:ViaService", "kms:CallerAccount"}
    assert condition["kms:CallerAccount"] == {"Ref": "AWS::AccountId"}


def test_staging_role_can_signal_the_stack_and_embed_with_cohere():
    statements = role_statements()
    assert statements["SignalStack"]["Action"] == "cloudformation:SignalResource"
    assert statements["EmbedWithCohere"]["Action"] == "bedrock:InvokeModel"
    assert any(
        "cohere.embed-v4:0" in (r if isinstance(r, str) else r["Fn::Sub"])
        for r in statements["EmbedWithCohere"]["Resource"]
    )


def test_staging_log_group_is_retained_and_unnamed():
    group = staging_template()["Resources"]["BuilderLogs"]
    assert group["DeletionPolicy"] == "Retain"
    assert group["UpdateReplacePolicy"] == "Retain"
    assert "LogGroupName" not in group["Properties"]


def test_staging_security_group_allows_https_egress_only():
    group = staging_template()["Resources"]["BuilderSecurityGroup"]
    ports = [rule["FromPort"] for rule in group["Properties"]["SecurityGroupEgress"]]
    assert ports == [443]


def test_staging_nested_stacks_use_regional_endpoints():
    resources = staging_template()["Resources"]
    for name in ("VPCStack", "DatabaseStack"):
        url = resources[name]["Properties"]["TemplateURL"]["Fn::Sub"]
        assert ".s3.${AWS::Region}.amazonaws.com/" in url


def test_staging_instance_waits_for_a_signal_and_exports_the_bucket():
    properties = staging_template()["Resources"]["BuilderInstance"]
    assert properties["CreationPolicy"]["ResourceSignal"]["Count"] == 1
    text = user_data()
    assert "MOSAIC_OWN_ACCOUNT_BUCKET=${AssetsBucketName}" in text
    assert "MOSAIC_OWN_ACCOUNT_PREFIX=${AssetsBucketPrefix}" in text


def test_staging_user_data_installs_the_wrapper_and_signals_with_the_cli():
    text = user_data()
    assert "/usr/local/bin/mosaic-catalog-bundle" in text
    assert "aws cloudformation signal-resource" in text
    assert "cfn-signal" not in text
    assert not re.search(r"signal[^\n]*\|\| true", text)
    assert text.index("command -v aws") < text.index("trap finish EXIT")
    assert "stdbuf -oL tee" in text
    assert text.index('wait "$TEE_PID"') < text.index(
        "ship_log\n", text.index("finish()")
    )


def test_the_wrapper_quotes_arguments_and_checks_the_child_started():
    text = user_data()
    wrapper = text[text.index("cat <<'WRAPPER'") : text.index("\nWRAPPER")]
    assert "printf '%q ' \"$@\"" in wrapper
    assert (
        "setsid -w make catalog-bundle ASSETS_DIR=.local/own-account/assets" in wrapper
    )
    assert "kill -0" in wrapper
    assert "sleep 2" in wrapper
    assert "tail -f $LOG" in wrapper
    motd = text[text.index("cat >/etc/motd") :]
    assert motd.splitlines()[2].strip() == "mosaic-catalog-bundle"
