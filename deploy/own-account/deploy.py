#!/usr/bin/env python3
"""Deploy Mosaic into your own AWS account, without Workshop Studio.

Every subcommand builds a plan (a list of steps, each naming the AWS calls it makes), then
runs it. ``--dry-run`` prints the plan and makes no AWS call. The flow:

    check            verify the account, models, quotas and the source you will deploy
    publish          upload the release and the catalog bundle to your private bucket
    staging up       create the staging Aurora cluster and builder host for the bundle build
    deploy           create the main stack from the published release
    status           show the main stack and its outputs
    teardown         delete the main stack and report what it leaves behind
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError, NoCredentialsError

REPO = Path(__file__).resolve().parents[2]
CLOUDFORMATION = REPO / "deploy" / "cloudformation"
BOOTSTRAP = REPO / "deploy" / "mosaic-bootstrap.sh"
REAL_CATALOG_CONTRACT = REPO / "db" / "config" / "real-catalog-cache.json"
VOCABULARY_CONTRACT = REPO / "db" / "config" / "corpus-vocabulary-cache.json"
DEFAULT_ASSETS_DIR = Path(".local/own-account/assets")

MAIN_TEMPLATE = "hybrid-retrieval-main.yml"
STAGING_TEMPLATE = "hybrid-retrieval-staging.yml"
VPC_TEMPLATE = "hybrid-retrieval-vpc.yml"
DATABASE_TEMPLATE = "hybrid-retrieval-database.yml"
EDITOR_TEMPLATE = "hybrid-retrieval-code-editor.yml"
NESTED_TEMPLATES = (VPC_TEMPLATE, DATABASE_TEMPLATE, EDITOR_TEMPLATE)
#: Templates whose bytes feed the revision digest; their release folder never changes.
DIGESTED_TEMPLATES = (MAIN_TEMPLATE, *NESTED_TEMPLATES)

#: Service principal -> the role AWS creates for it.
SERVICE_LINKED_ROLES = {
    "rds.amazonaws.com": "AWSServiceRoleForRDS",
    "vpcorigin.cloudfront.amazonaws.com": "AWSServiceRoleForCloudFrontVPCOrigin",
}
OWNER_TAG = {"Key": "MosaicOwnAccount", "Value": "true"}
BUCKET_PREFIX = "mosaic-own-account-"
# Model identifiers the application pins (service/config.py and the bootstrap's .env).
CHAT_MODEL = "global.anthropic.claude-sonnet-5-5"
EMBED_MODEL = "us.cohere.embed-v4:0"
RERANK_MODEL = "cohere.rerank-v3-5:0"
#: "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" vCPU quota.
STANDARD_VCPU_QUOTA = "L-1216C47A"
VPC_QUOTA = ("vpc", "L-F678F1CE")
ELASTIC_IP_QUOTA = ("ec2", "L-0263D0A3")
SIZE_VCPUS = {"large": 2, "xlarge": 4, "2xlarge": 8, "4xlarge": 16, "8xlarge": 32}

#: signed_status result when the request never got an HTTP answer.
NETWORK_ERROR = 0
MAIN_STACK_NAME = "mosaic-hybrid-retrieval"
STAGING_STACK_NAME = "mosaic-staging"
POLL_SECONDS = 30
STALE_DELETE_SECONDS = 300
MAX_WAIT_SECONDS = 3 * 3600
GIT_PROBE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}
GIT_PROBE_TIMEOUT_SECONDS = 120
NOT_FOUND_CODES = ("404", "NoSuchKey", "NotFound", "NoSuchBucket")


class Refusal(Exception):
    """A precondition failed; the message names the rule, the value and the fix."""


# --------------------------------------------------------------------------------------
# Revision digest. These helpers replicate, byte for byte, Workshop Studio's
# scripts/validate_workshop.py (calculate_infrastructure_revision, cfn_default) and
# scripts/repin.py (replace_cfn_default). They MUST stay identical to those: the digest is
# the release folder's name, and the Studio build and this tool must agree on it.
# --------------------------------------------------------------------------------------
def cfn_default(text: str, parameter: str) -> str:
    """Return a CloudFormation parameter's ``Default`` value."""
    match = re.search(
        rf"^\s{{2}}{re.escape(parameter)}:\s*\n"
        rf"(?:^\s{{4,}}.*\n)*?^\s{{4}}Default:\s*([^\s]+)\s*$",
        text,
        re.MULTILINE,
    )
    if not match:
        raise Refusal(f"CloudFormation template has no default for {parameter}")
    return match.group(1).strip("'\"")


def replace_cfn_default(text: str, parameter: str, value: str) -> str:
    """Rewrite a CloudFormation parameter ``Default:`` in place."""
    pattern = re.compile(
        rf"(^  {re.escape(parameter)}:\n(?:^    .*\n)*?^    Default: )\S*$",
        re.MULTILINE,
    )
    updated, count = pattern.subn(lambda match: match.group(1) + value, text)
    if count != 1:
        raise Refusal(
            f"template has {count} Default lines for {parameter}, expected exactly 1"
        )
    return updated


def calculate_infrastructure_revision(
    main: str, vpc: str, database: str, editor: str
) -> str:
    """Derive the nested-stack release key from the templates and bootstrap inputs."""
    normalized_main = main.replace(
        cfn_default(main, "InfrastructureRevision"), "<derived-infrastructure-revision>"
    )
    contract = "\n".join(
        (
            normalized_main,
            cfn_default(main, "SourceRevision"),
            cfn_default(main, "BootstrapScriptSha256"),
            vpc,
            database,
            editor,
        )
    )
    return hashlib.sha256(contract.encode("utf-8")).hexdigest()[:16]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


# --------------------------------------------------------------------------------------
# Release: the pinned templates, bootstrap and launcher package for one source revision.
# --------------------------------------------------------------------------------------
def load_launcher_packager(directory: Path) -> Any:
    """Import the launcher packager that sits beside the templates."""
    path = directory / "editor_launcher_package.py"
    spec = importlib.util.spec_from_file_location("editor_launcher_package", path)
    if spec is None or spec.loader is None:
        raise Refusal(f"cannot load {path}; restore deploy/cloudformation from Git")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Release:
    """Everything one release folder holds, plus the launcher package at the bucket root."""

    revision: str
    source_revision: str
    bootstrap_sha256: str
    launcher_name: str
    launcher_code_sha256: str
    files: dict[str, bytes]
    launcher: bytes

    def parameters(self) -> dict[str, str]:
        """The five pinned values every deploy passes explicitly."""
        return {
            "SourceRevision": self.source_revision,
            "InfrastructureRevision": self.revision,
            "BootstrapScriptSha256": self.bootstrap_sha256,
            "EditorLauncherArchiveName": self.launcher_name,
            "EditorLauncherCodeSha256": self.launcher_code_sha256,
        }

    def description(self) -> bytes:
        digests = {
            name: sha256_bytes(body) for name, body in sorted(self.files.items())
        }
        document = {
            "infrastructure_revision": self.revision,
            "source_revision": self.source_revision,
            "sha256": digests,
        }
        return (json.dumps(document, indent=2) + "\n").encode()


def build_release(
    source_revision: str, directory: Path = CLOUDFORMATION, bootstrap: Path = BOOTSTRAP
) -> Release:
    """Pin the templates to ``source_revision`` and derive the release identity."""
    packager = load_launcher_packager(directory)
    launcher = packager.package(directory / "editor_launcher.py")
    launcher_name = packager.archive_name(launcher)
    launcher_sha = packager.code_sha256(launcher)
    bootstrap_body = bootstrap.read_bytes()
    bootstrap_sha = sha256_bytes(bootstrap_body)

    text = {
        name: (directory / name).read_text(encoding="utf-8")
        for name in (*DIGESTED_TEMPLATES, STAGING_TEMPLATE)
    }
    main = text[MAIN_TEMPLATE]
    for parameter, value in (
        ("SourceRevision", source_revision),
        ("BootstrapScriptSha256", bootstrap_sha),
        ("EditorLauncherArchiveName", launcher_name),
        ("EditorLauncherCodeSha256", launcher_sha),
    ):
        main = replace_cfn_default(main, parameter, value)
    editor = replace_cfn_default(
        text[EDITOR_TEMPLATE], "SourceRevision", source_revision
    )
    revision = calculate_infrastructure_revision(
        main, text[VPC_TEMPLATE], text[DATABASE_TEMPLATE], editor
    )
    main = replace_cfn_default(main, "InfrastructureRevision", revision)
    files = {
        MAIN_TEMPLATE: main.encode("utf-8"),
        VPC_TEMPLATE: text[VPC_TEMPLATE].encode("utf-8"),
        DATABASE_TEMPLATE: text[DATABASE_TEMPLATE].encode("utf-8"),
        EDITOR_TEMPLATE: editor.encode("utf-8"),
        STAGING_TEMPLATE: text[STAGING_TEMPLATE].encode("utf-8"),
        "mosaic-bootstrap.sh": bootstrap_body,
    }
    return Release(
        revision,
        source_revision,
        bootstrap_sha,
        launcher_name,
        launcher_sha,
        files,
        launcher,
    )


# --------------------------------------------------------------------------------------
# Source checks: the git facts the deploy depends on.
# --------------------------------------------------------------------------------------
def git(*arguments: str, cwd: Path = REPO) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise Refusal("git is not installed or not on PATH") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip().splitlines()
        raise Refusal(
            f"`git {' '.join(arguments)}` failed in {cwd}: "
            f"{detail[-1] if detail else 'no output'}. Run this from a git checkout of "
            "your fork."
        ) from error
    return result.stdout.rstrip("\n")


def default_repo_url() -> str:
    try:
        return git("remote", "get-url", "origin")
    except Refusal as error:
        raise Refusal(
            "this checkout has no usable 'origin' remote; pass --repo-url with the HTTPS URL "
            f"of your fork ({error})"
        ) from error


def resolve_revision(revision: str) -> str:
    """The full commit id for ``revision`` (HEAD by default)."""
    return git("rev-parse", "--verify", f"{revision}^{{commit}}")


def normalize_repo_url(url: str) -> str:
    """The HTTPS ``.git`` form the stacks accept; SSH and scp-style URLs are rewritten."""
    scp = re.fullmatch(r"git@([^:]+):(.+)", url)
    if scp:
        url = f"https://{scp.group(1)}/{scp.group(2)}"
    return url if url.endswith(".git") else url + ".git"


REPO_URL_PATTERN = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git"
)


def validate_repo_url(url: str) -> str:
    """Refuse a RepoUrl the stacks would reject or the host could not clone anonymously."""
    if not REPO_URL_PATTERN.fullmatch(url):
        raise Refusal(
            f"RepoUrl {url!r} must be an HTTPS GitHub URL ending in .git, such as "
            "https://github.com/<you>/<fork>.git; pass it with --repo-url"
        )
    return url


def require_clean_tree() -> None:
    dirty = git("status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise Refusal(
            "the working tree has uncommitted changes:\n"
            + "\n".join(f"  {line}" for line in dirty.splitlines()[:10])
            + "\nCommit them (the stacks clone a commit, not your files), then rerun."
        )


def require_head(source_revision: str) -> None:
    head = git("rev-parse", "HEAD")
    if source_revision != head:
        raise Refusal(
            f"--source-revision {source_revision} is not the checked-out commit {head}; the "
            f"templates and bootstrap are read from this checkout. Run: git checkout "
            f"{source_revision}"
        )


def probe_anonymous_fetch(repo_url: str, source_revision: str) -> str | None:
    """Return None when ``repo_url`` serves the commit without credentials, else why not.

    The user's git configuration is ignored: a ``url.insteadOf`` rule could rewrite the
    fork to SSH and pass here with credentials the host will never have.
    """
    env = {**os.environ, **GIT_PROBE_ENV}
    with tempfile.TemporaryDirectory() as scratch:
        steps = (
            ["git", "init", "-q", scratch],
            ["git", "-C", scratch, "remote", "add", "origin", repo_url],
            ["git", "-C", scratch, "-c", "credential.helper=", "fetch", "--depth", "1"]
            + ["origin", source_revision],
        )
        for command in steps:
            try:
                result = subprocess.run(
                    command,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=GIT_PROBE_TIMEOUT_SECONDS,
                )
            except FileNotFoundError:
                return "git is not installed or not on PATH"
            except subprocess.TimeoutExpired:
                return f"timed out after {GIT_PROBE_TIMEOUT_SECONDS} s"
            if result.returncode != 0:
                lines = result.stderr.strip().splitlines()
                return lines[-1] if lines else "failed"
    return None


# --------------------------------------------------------------------------------------
# Catalog bundle: the files `publish` syncs, tied to the committed contract files.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class BundleFile:
    key: str
    path: Path
    sha256: str
    size: int


def expected_bundle(
    catalog: dict | None = None, vocabulary: dict | None = None
) -> list[tuple[str, str, int]]:
    """(relative key, sha256, bytes) for each file the two contracts describe.

    Reads the committed contract files unless parsed documents are passed in.
    """
    if catalog is None:
        catalog = json.loads(REAL_CATALOG_CONTRACT.read_text(encoding="utf-8"))
    if vocabulary is None:
        vocabulary = json.loads(VOCABULARY_CONTRACT.read_text(encoding="utf-8"))
    try:
        entries = [
            (f"real-catalog/{part['name']}", part["sha256"], part["bytes"])
            for part in catalog["parts"]
        ]
        for schema, entry in sorted(vocabulary["schemas"].items()):
            for table, table_entry in sorted(entry["tables"].items()):
                key = f"real-catalog/vocabulary/{schema}.{table}.csv.gz"
                entries.append((key, table_entry["sha256"], table_entry["bytes"]))
    except (KeyError, TypeError) as error:
        raise Refusal(f"a catalog contract is malformed: missing {error}") from error
    return entries


def collect_bundle(assets_dir: Path) -> list[BundleFile]:
    """Return the bundle files, refusing when any differs from the committed contracts."""
    problems: list[str] = []
    found: list[BundleFile] = []
    for key, expected_sha, expected_size in expected_bundle():
        path = assets_dir / key
        if not path.is_file():
            problems.append(f"missing {path}")
            continue
        size = path.stat().st_size
        digest = sha256_file(path) if size == expected_size else "size mismatch"
        if digest != expected_sha:
            problems.append(
                f"{key}: bundle has {size} bytes/{digest[:16]}, contract wants "
                f"{expected_size} bytes/{expected_sha[:16]}"
            )
            continue
        found.append(BundleFile(key, path, digest, size))
    if problems:
        raise Refusal(
            "the catalog bundle does not match db/config/real-catalog-cache.json and "
            "db/config/corpus-vocabulary-cache.json in this checkout:\n  "
            + "\n  ".join(problems)
            + "\nBuild the bundle with `make catalog-bundle` on the staging builder, copy "
            "the two rewritten contract files into your fork, commit them, and rerun."
        )
    return found


# --------------------------------------------------------------------------------------
# Context and plan model.
# --------------------------------------------------------------------------------------
@dataclass
class Context:
    region: str
    profile: str | None
    bucket: str
    stack_name: str
    dry_run: bool
    repo_url: str
    source_revision: str
    assets_dir: Path
    account: str = "<account-id>"
    clients: dict[str, Any] = field(default_factory=dict)
    client_factory: Callable[[str], Any] | None = None
    uploaded: list[str] = field(default_factory=list)
    discovered: dict[str, list[str]] = field(default_factory=dict)
    partition: str = "aws"
    bucket_explicit: bool = False
    pending: list[str] = field(default_factory=list)
    out: Callable[[str], None] = print

    def client(self, service: str, region: str | None = None) -> Any:
        key = f"{service}@{region}" if region else service
        if key not in self.clients:
            self.clients[key] = self._make_client(service, region or self.region)
        return self.clients[key]

    def _make_client(self, service: str, region: str) -> Any:
        if self.client_factory:
            return self.client_factory(service)
        import boto3

        session = boto3.Session(profile_name=self.profile, region_name=region)
        return session.client(service)

    def session_credentials(self) -> Any:
        import boto3

        session = boto3.Session(profile_name=self.profile, region_name=self.region)
        return session.get_credentials()


@dataclass
class Step:
    """One unit of work. ``calls`` lists the AWS calls; a step without ``run`` makes them."""

    description: str
    calls: tuple[tuple[str, str, dict[str, Any]], ...] = ()
    tolerate: tuple[str, ...] = ()
    run: Callable[[Context], None] | None = None


def default_bucket(account: str, region: str) -> str:
    return f"mosaic-own-account-{account}-{region}"


def error_code(error: Exception) -> str:
    response = getattr(error, "response", None) or {}
    return response.get("Error", {}).get("Code", "")


def execute_calls(ctx: Context, step: Step) -> None:
    for service, operation, params in step.calls:
        method = getattr(ctx.client(service), to_snake(operation))
        try:
            method(**params)
        except Exception as error:
            if error_code(error) not in step.tolerate:
                raise


def to_snake(operation: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", operation).lower()


def render_step(number: int, step: Step) -> list[str]:
    lines = [f"{number:>2}. {step.description}"]
    for service, operation, params in step.calls:
        shown = json.dumps(params, default=str, sort_keys=True)
        lines.append(f"      aws {service}.{operation} {shown}")
    return lines


def run_plan(plan: list[Step], ctx: Context) -> None:
    """Print the plan (dry run) or execute it in order."""
    for number, step in enumerate(plan, 1):
        if ctx.dry_run:
            for line in render_step(number, step):
                ctx.out(line)
            continue
        ctx.out(f"[{number}/{len(plan)}] {step.description}")
        if step.run:
            step.run(ctx)
        else:
            execute_calls(ctx, step)
    if ctx.dry_run:
        ctx.out("dry run: no AWS call was made")


# --------------------------------------------------------------------------------------
# Plans: publish.
# --------------------------------------------------------------------------------------
def tls_only_policy(bucket: str, partition: str = "aws") -> str:
    arn = f"arn:{partition}:s3:::{bucket}"
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyInsecureTransport",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "s3:*",
                    "Resource": [arn, f"{arn}/*"],
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                }
            ],
        }
    )


def bucket_has_owner_tag(s3: Any, bucket: str) -> bool:
    try:
        tags = s3.get_bucket_tagging(Bucket=bucket)["TagSet"]
    except Exception as error:
        if error_code(error) == "NoSuchTagSet":
            return False
        raise
    return OWNER_TAG in [{"Key": t["Key"], "Value": t["Value"]} for t in tags]


def ensure_bucket(ctx: Context, create: dict[str, Any]) -> None:
    """Create and tag the bucket, or accept an existing one only if this tool made it."""
    s3 = ctx.client("s3")
    try:
        s3.head_bucket(Bucket=ctx.bucket)
    except Exception as error:
        if error_code(error) not in NOT_FOUND_CODES:
            raise
        s3.create_bucket(**create)
        s3.put_bucket_tagging(Bucket=ctx.bucket, Tagging={"TagSet": [OWNER_TAG]})
        ctx.out(f"    created bucket {ctx.bucket}")
        return
    if not bucket_has_owner_tag(s3, ctx.bucket):
        raise Refusal(
            f"bucket {ctx.bucket} exists but lacks the tag {OWNER_TAG['Key']}="
            f"{OWNER_TAG['Value']}, so this tool will not write to it. Use a bucket this tool "
            "created, or choose a new --bucket name. If you made it with this tool and the "
            "tagging step failed: aws s3api put-bucket-tagging --bucket "
            f"{ctx.bucket} --tagging 'TagSet=[{{Key={OWNER_TAG['Key']},Value=true}}]'"
        )
    ctx.out(f"    bucket {ctx.bucket} exists and is tagged")


def bucket_steps(ctx: Context) -> list[Step]:
    create: dict[str, Any] = {"Bucket": ctx.bucket}
    if ctx.region != "us-east-1":
        create["CreateBucketConfiguration"] = {"LocationConstraint": ctx.region}
    block = {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    encryption = {
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
    }
    return [
        Step(
            f"create private bucket {ctx.bucket} if missing, tagged {OWNER_TAG['Key']}=true "
            "(versioning stays off); refuse an existing bucket without the tag",
            (
                ("s3", "HeadBucket", {"Bucket": ctx.bucket}),
                ("s3", "CreateBucket", create),
                (
                    "s3",
                    "PutBucketTagging",
                    {"Bucket": ctx.bucket, "Tagging": {"TagSet": [OWNER_TAG]}},
                ),
            ),
            run=lambda c: ensure_bucket(c, create),
        ),
        Step(
            "block all public access",
            (
                (
                    "s3",
                    "PutPublicAccessBlock",
                    {"Bucket": ctx.bucket, "PublicAccessBlockConfiguration": block},
                ),
            ),
        ),
        Step(
            "default encryption SSE-S3",
            (
                (
                    "s3",
                    "PutBucketEncryption",
                    {
                        "Bucket": ctx.bucket,
                        "ServerSideEncryptionConfiguration": encryption,
                    },
                ),
            ),
        ),
        Step(
            "bucket policy: deny non-TLS requests",
            (
                (
                    "s3",
                    "PutBucketPolicy",
                    {
                        "Bucket": ctx.bucket,
                        "Policy": tls_only_policy(ctx.bucket, ctx.partition),
                    },
                ),
            ),
        ),
    ]


@dataclass(frozen=True)
class Asset:
    key: str
    sha256: str
    size: int
    data: bytes | None = None
    path: Path | None = None
    #: Immutable keys are named by their content; a different object there is a conflict.
    immutable: bool = True


def release_assets(release: Release) -> list[Asset]:
    prefix = f"releases/{release.revision}/"
    assets = [
        Asset(
            prefix + name,
            sha256_bytes(body),
            len(body),
            data=body,
            immutable=name != STAGING_TEMPLATE,
        )
        for name, body in sorted(release.files.items())
    ]
    description = release.description()
    assets.append(
        Asset(
            prefix + "RELEASE.json",
            sha256_bytes(description),
            len(description),
            data=description,
            immutable=False,
        )
    )
    assets.append(
        Asset(
            release.launcher_name,
            sha256_bytes(release.launcher),
            len(release.launcher),
            data=release.launcher,
        )
    )
    return assets


def head_sha256(client: Any, bucket: str, key: str) -> tuple[str | None, int | None]:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception as error:
        if error_code(error) in NOT_FOUND_CODES:
            return None, None
        raise
    return head.get("Metadata", {}).get("sha256"), head.get("ContentLength")


def upload_asset(ctx: Context, asset: Asset) -> None:
    client = ctx.client("s3")
    existing, size = head_sha256(client, ctx.bucket, asset.key)
    if size is not None and existing == asset.sha256 and size == asset.size:
        ctx.out(f"    unchanged: {asset.key}")
        return
    if size is not None and asset.immutable:
        raise Refusal(
            f"s3://{ctx.bucket}/{asset.key} already exists with {size} bytes and sha256 "
            f"metadata {str(existing)[:16] or 'missing'}, not the {asset.size} bytes/"
            f"{asset.sha256[:16]} of this release. Release keys are immutable: change the "
            "inputs to get a new revision, or delete the key yourself if you are sure."
        )
    extra = {"Metadata": {"sha256": asset.sha256}}
    if asset.data is not None:
        client.put_object(Bucket=ctx.bucket, Key=asset.key, Body=asset.data, **extra)
    else:
        client.upload_file(str(asset.path), ctx.bucket, asset.key, ExtraArgs=extra)
    ctx.uploaded.append(asset.key)
    ctx.out(f"    uploaded: {asset.key} ({asset.size} bytes)")


def verify_asset(ctx: Context, asset: Asset) -> None:
    """Download the object and compare its SHA-256 with the local file's."""
    if asset.key not in ctx.uploaded:
        return
    body = ctx.client("s3").get_object(Bucket=ctx.bucket, Key=asset.key)["Body"]
    digest = hashlib.sha256()
    for chunk in iter(lambda: body.read(8 * 1024 * 1024), b""):
        digest.update(chunk)
    if digest.hexdigest() != asset.sha256:
        raise Refusal(
            f"s3://{ctx.bucket}/{asset.key} hashes to {digest.hexdigest()} after upload, "
            f"local file is {asset.sha256}. Rerun publish."
        )
    ctx.out(f"    verified: {asset.key}")


def asset_steps(ctx: Context, assets: Iterable[Asset]) -> list[Step]:
    steps: list[Step] = []
    for asset in assets:
        target = {
            "Bucket": ctx.bucket,
            "Key": asset.key,
            "Metadata": {"sha256": asset.sha256},
        }
        steps.append(
            Step(
                f"upload s3://{ctx.bucket}/{asset.key}",
                (("s3", "PutObject", target),),
                run=lambda c, a=asset: upload_asset(c, a),
            )
        )
    for asset in assets:
        key = {"Bucket": ctx.bucket, "Key": asset.key}
        steps.append(
            Step(
                f"verify sha256 of s3://{ctx.bucket}/{asset.key}",
                (("s3", "GetObject", key),),
                run=lambda c, a=asset: verify_asset(c, a),
            )
        )
    return steps


def prepare_source(ctx: Context) -> Release:
    """Check the tree and build the release; a dry run warns instead of refusing."""
    try:
        require_clean_tree()
        require_head(ctx.source_revision)
    except Refusal as refusal:
        if not ctx.dry_run:
            raise
        ctx.out(f"warning (dry run, a real run would refuse): {refusal}")
    return build_release(ctx.source_revision)


def local_bundle_present(ctx: Context) -> bool:
    return (ctx.assets_dir / "real-catalog").is_dir()


def bundle_problems(ctx: Context, entries: list[tuple[str, str, int]]) -> list[str]:
    """Differences between the bucket's objects and the (key, sha256, size) entries."""
    s3 = ctx.client("s3")
    problems: list[str] = []
    for key, sha256, size in entries:
        found_sha, found_size = head_sha256(s3, ctx.bucket, key)
        if found_size is None:
            problems.append(f"{key}: not in the bucket")
        elif found_size != size:
            problems.append(
                f"{key}: bucket has {found_size} bytes, contract says {size}"
            )
        elif found_sha != sha256:
            problems.append(
                f"{key}: bucket metadata sha256 is {str(found_sha)[:16]}, contract says "
                f"{sha256[:16]}"
            )
    return problems


def verify_bucket_bundle(ctx: Context) -> None:
    """Check the bundle in the bucket against the committed contracts, without downloading."""
    entries = expected_bundle()
    problems = bundle_problems(ctx, entries)
    if problems:
        raise Refusal(
            f"the bundle in s3://{ctx.bucket}/ does not match the committed contracts "
            "(db/config/real-catalog-cache.json, db/config/corpus-vocabulary-cache.json):\n  "
            + "\n  ".join(problems)
            + "\nRun `contracts pull`, commit and push the two files, then rerun publish. If "
            "the bundle is missing, build it on the staging builder first."
        )
    ctx.out(f"    bundle verified: {len(entries)} objects match the contracts")


def plan_publish(ctx: Context) -> list[Step]:
    release = prepare_source(ctx)
    assets = release_assets(release)
    if local_bundle_present(ctx):
        assets += [
            Asset(f.key, f.sha256, f.size, path=f.path, immutable=False)
            for f in collect_bundle(ctx.assets_dir)
        ]
    ctx.out(f"InfrastructureRevision {release.revision}")
    verify = Step(
        "verify the bundle in the bucket against the committed contracts (size and sha256 "
        "metadata, no download)",
        tuple(
            ("s3", "HeadObject", {"Bucket": ctx.bucket, "Key": k})
            for k, _, _ in expected_bundle()
        ),
        run=verify_bucket_bundle,
    )
    return [
        *bucket_steps(ctx),
        *asset_steps(ctx, assets),
        verify,
        global_endpoint_step(ctx, release),
    ]


# --------------------------------------------------------------------------------------
# Plans: contracts pull.
# --------------------------------------------------------------------------------------
CONTRACT_FILES = {
    "contracts/real-catalog-cache.json": REAL_CATALOG_CONTRACT,
    "contracts/corpus-vocabulary-cache.json": VOCABULARY_CONTRACT,
}


def fetch_contract(ctx: Context, key: str) -> bytes:
    s3 = ctx.client("s3")
    try:
        obj = s3.get_object(Bucket=ctx.bucket, Key=key)
    except Exception as error:
        if error_code(error) in NOT_FOUND_CODES:
            raise Refusal(
                f"s3://{ctx.bucket}/{key} does not exist. Run `mosaic-catalog-bundle` on the "
                "staging builder; its upload step writes the contracts."
            ) from error
        raise
    body = obj["Body"].read()
    recorded = obj.get("Metadata", {}).get("sha256")
    if not recorded:
        raise Refusal(
            f"s3://{ctx.bucket}/{key} has no sha256 metadata, so its origin is unknown; "
            "rebuild it with the staging builder's upload step"
        )
    if recorded != sha256_bytes(body):
        raise Refusal(f"s3://{ctx.bucket}/{key} does not hash to its recorded sha256")
    try:
        json.loads(body)
    except ValueError as error:
        raise Refusal(f"s3://{ctx.bucket}/{key} is not valid JSON: {error}") from error
    return body


def pull_contracts(ctx: Context) -> None:
    """Fetch and validate both contracts and the bundle they describe, then write both."""
    fetched = {key: fetch_contract(ctx, key) for key in CONTRACT_FILES}
    entries = expected_bundle(
        json.loads(fetched["contracts/real-catalog-cache.json"]),
        json.loads(fetched["contracts/corpus-vocabulary-cache.json"]),
    )
    problems = bundle_problems(ctx, entries)
    if problems:
        raise Refusal(
            "the contracts in the bucket describe a bundle the bucket does not hold; nothing "
            "was written:\n  " + "\n  ".join(problems)
        )
    pending: dict[Path, Path] = {}
    try:
        for key, body in fetched.items():
            destination = CONTRACT_FILES[key]
            name = destination.relative_to(REPO)
            if destination.exists() and destination.read_bytes() == body:
                ctx.out(f"    unchanged: {name}")
                continue
            temporary = destination.with_name(destination.name + ".tmp")
            pending[temporary] = destination
            temporary.write_bytes(body)
        for temporary, destination in pending.items():
            os.replace(temporary, destination)
            ctx.out(f"    updated:   {destination.relative_to(REPO)}")
    finally:
        for temporary in pending:
            temporary.unlink(missing_ok=True)
    ctx.out(
        "next: git add db/config/real-catalog-cache.json db/config/corpus-vocabulary-cache.json "
        '&& git commit -m "Pin the catalog bundle" && git push, then run publish'
    )


def plan_contracts_pull(ctx: Context) -> list[Step]:
    return [
        Step(
            f"download the two contract files from s3://{ctx.bucket}/ into db/config/",
            tuple(
                ("s3", "GetObject", {"Bucket": ctx.bucket, "Key": k})
                for k in CONTRACT_FILES
            ),
            run=pull_contracts,
        )
    ]


# --------------------------------------------------------------------------------------
# Plans: check.
# --------------------------------------------------------------------------------------
def verdict(ctx: Context, ok: bool, name: str, fix: str = "") -> bool:
    ctx.out(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"\n     fix: {fix}"))
    return ok


def check_identity(ctx: Context) -> None:
    identity = ctx.client("sts").get_caller_identity()
    ctx.account = identity["Account"]
    verdict(
        ctx,
        True,
        f"account {identity['Account']} in {ctx.region}; caller {identity['Arn']}",
    )
    ctx.out(
        "     note: the deploy creates IAM roles, VPCs, Aurora and CloudFront; use an "
        "administrator role."
    )


def check_models(ctx: Context) -> None:
    command = [
        sys.executable,
        str(REPO / "scripts" / "checks" / "check_model_access.py"),
        "--chat",
        CHAT_MODEL,
        "--embed",
        EMBED_MODEL,
        "--rerank",
        RERANK_MODEL,
        "--region",
        ctx.region,
    ]
    env = {**os.environ, "AWS_REGION": ctx.region, "AWS_DEFAULT_REGION": ctx.region}
    if ctx.profile:
        env["AWS_PROFILE"] = ctx.profile
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, check=False
    )
    verdict(
        ctx,
        result.returncode == 0,
        f"Bedrock access to {CHAT_MODEL}, {EMBED_MODEL}, {RERANK_MODEL}",
        "request model access in the Bedrock console for this Region, then rerun; "
        "details:\n" + (result.stdout + result.stderr).strip()[-1500:],
    )


def role_exists(iam: Any, role_name: str) -> bool:
    """Whether the role exists; any error other than NoSuchEntity propagates."""
    try:
        iam.get_role(RoleName=role_name)
    except Exception as error:
        if error_code(error) == "NoSuchEntity":
            return False
        raise
    return True


def check_service_linked_roles(ctx: Context) -> None:
    """Report missing service-linked roles; `staging up` and `deploy` create them."""
    iam = ctx.client("iam")
    for service, role_name in SERVICE_LINKED_ROLES.items():
        try:
            present = role_exists(iam, role_name)
        except Exception as error:  # noqa: BLE001 - reported as a FAIL line
            verdict(
                ctx,
                False,
                f"service-linked role {role_name}",
                f"{error_code(error)}: the caller needs iam:GetRole",
            )
            continue
        verdict(
            ctx,
            present,
            f"service-linked role {role_name} ({service})",
            "run `staging up` or `deploy` (they create it), or: aws iam "
            f"create-service-linked-role --aws-service-name {service}",
        )


def ensure_service_linked_roles(ctx: Context) -> None:
    """Create each missing service-linked role; safe to repeat."""
    iam = ctx.client("iam")
    for service, role_name in SERVICE_LINKED_ROLES.items():
        if role_exists(iam, role_name):
            ctx.out(f"    {role_name} exists")
            continue
        try:
            iam.create_service_linked_role(AWSServiceName=service)
            ctx.out(f"    created {role_name}")
        except Exception as error:
            if error_code(error) != "InvalidInput" or not role_exists(iam, role_name):
                raise


def service_linked_role_step() -> Step:
    calls: list[tuple[str, str, dict[str, Any]]] = []
    for service, role_name in SERVICE_LINKED_ROLES.items():
        calls.append(("iam", "GetRole", {"RoleName": role_name}))
        calls.append(("iam", "CreateServiceLinkedRole", {"AWSServiceName": service}))
    return Step(
        "create the service-linked roles for RDS and CloudFront VPC origins if missing",
        tuple(calls),
        run=ensure_service_linked_roles,
    )


def instance_vcpus(instance_type: str) -> int:
    return SIZE_VCPUS.get(instance_type.split(".")[-1], 0)


def check_quota(ctx: Context) -> None:
    main = (CLOUDFORMATION / MAIN_TEMPLATE).read_text(encoding="utf-8")
    staging = (CLOUDFORMATION / STAGING_TEMPLATE).read_text(encoding="utf-8")
    editor = cfn_default(main, "CodeEditorInstanceType")
    builder = cfn_default(staging, "BuilderInstanceType")
    try:
        quota = quota_value(ctx, "ec2", STANDARD_VCPU_QUOTA)
    except Exception as error:  # noqa: BLE001 - advisory check only
        ctx.out(
            f"warn quota lookup failed ({error_code(error) or error}); not blocking"
        )
        return
    need = max(instance_vcpus(editor), instance_vcpus(builder))
    ctx.out(
        f"{'ok  ' if quota >= need else 'WARN'} EC2 standard vCPU quota {quota:g}; staging "
        f"builder {builder} needs {instance_vcpus(builder)}, Code Editor host {editor} needs "
        f"{instance_vcpus(editor)}. They are not up together (run `staging down` before "
        f"`deploy`), so the peak is {need} (report only)"
    )


def quota_value(ctx: Context, service_code: str, quota_code: str) -> float:
    """The account's applied quota, or AWS's default when it was never changed."""
    quotas = ctx.client("service-quotas")
    try:
        return quotas.get_service_quota(ServiceCode=service_code, QuotaCode=quota_code)[
            "Quota"
        ]["Value"]
    except Exception as error:
        if error_code(error) != "NoSuchResourceException":
            raise
    return quotas.get_aws_default_service_quota(
        ServiceCode=service_code, QuotaCode=quota_code
    )["Quota"]["Value"]


def network_capacity(
    ctx: Context,
) -> list[tuple[str, int, float, str, tuple[str, str]]]:
    """(name, in use, quota, fix) for each resource one stack needs one more of."""
    ec2 = ctx.client("ec2")
    return [
        (
            "VPCs",
            len(ec2.describe_vpcs()["Vpcs"]),
            quota_value(ctx, *VPC_QUOTA),
            "request a VPC quota increase (Service Quotas, L-F678F1CE) or delete an unused VPC",
            VPC_QUOTA,
        ),
        (
            "Elastic IPs",
            len(ec2.describe_addresses()["Addresses"]),
            quota_value(ctx, *ELASTIC_IP_QUOTA),
            (
                "request an Elastic IP quota increase (Service Quotas, L-0263D0A3) or "
                "release an unused address"
            ),
            ELASTIC_IP_QUOTA,
        ),
    ]


RECENT_RAISE = timedelta(hours=1)


def utc_now() -> datetime:
    return datetime.now(UTC)


def note_recent_quota_raise(ctx: Context, quota_id: tuple[str, str]) -> None:
    """Say so when a quota increase was approved in the last hour.

    Service Quotas reports the new limit before EC2 enforces it, so a stack can still roll
    back on the old one for a few minutes. A denied lookup is silent: this is only a hint.
    """
    service_code, quota_code = quota_id
    try:
        history = ctx.client(
            "service-quotas"
        ).list_requested_service_quota_change_history_by_quota(
            ServiceCode=service_code, QuotaCode=quota_code
        )
    except Exception:  # noqa: BLE001 - an advisory hint must never fail the check
        return
    cutoff = utc_now() - RECENT_RAISE
    for request in history.get("RequestedQuotas", []):
        approved = "APPROVED" in (request.get("Status"), request.get("CaseStatus"))
        updated = request.get("LastUpdated")
        if approved and updated is not None and updated >= cutoff:
            ctx.out(
                f"     note: quota raised at {updated:%Y-%m-%d %H:%M} UTC; EC2 can take a "
                "while to enforce it, retry if the stack rolls back on the VPC"
            )
            return


def capacity_line(name: str, used: int, quota: float) -> str:
    return (
        f"{name}: {used} in use of {quota:g}; the staging stack and the main stack each need "
        "one (a VPC, and a NAT gateway with an Elastic IP) and are not up together"
    )


def check_network_capacity(ctx: Context) -> None:
    try:
        capacity = network_capacity(ctx)
    except Exception as error:  # noqa: BLE001 - advisory when the lookup itself is denied
        ctx.out(
            f"warn network quota lookup failed ({error_code(error) or error}); not blocking"
        )
        return
    for name, used, quota, fix, quota_id in capacity:
        verdict(ctx, used < quota, capacity_line(name, used, quota), fix)
        note_recent_quota_raise(ctx, quota_id)


def require_network_capacity(ctx: Context) -> None:
    """Refuse before CreateStack when a VPC or Elastic IP would exceed its quota."""
    try:
        capacity = network_capacity(ctx)
    except Exception as error:  # noqa: BLE001 - the stack itself will report a real limit
        ctx.out(
            f"    network quota lookup failed ({error_code(error) or error}); continuing"
        )
        return
    full = [(n, u, q, f) for n, u, q, f, _ in capacity if u >= q]
    if full:
        raise Refusal(
            "; ".join(f"{n}: {u} in use of {q:g}, none free" for n, u, q, _ in full)
            + f". The stack needs one of each. Fix: {full[0][3]}."
        )
    ctx.out("    a VPC and an Elastic IP are free")
    for *_, quota_id in capacity:
        note_recent_quota_raise(ctx, quota_id)


def network_capacity_step() -> Step:
    return Step(
        "refuse if the account has no free VPC or Elastic IP for this stack",
        (
            ("ec2", "DescribeVpcs", {}),
            (
                "service-quotas",
                "GetServiceQuota",
                {"ServiceCode": VPC_QUOTA[0], "QuotaCode": VPC_QUOTA[1]},
            ),
            ("ec2", "DescribeAddresses", {}),
            (
                "service-quotas",
                "GetServiceQuota",
                {"ServiceCode": ELASTIC_IP_QUOTA[0], "QuotaCode": ELASTIC_IP_QUOTA[1]},
            ),
        ),
        run=require_network_capacity,
    )


#: AWS::WAFv2::WebACL names are unique per account and scope; CloudFront ACLs live in
#: us-east-1 whatever Region the stack is in.
WAF_REGION = "us-east-1"
WORKSHOP_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,40}")


def validate_workshop_name(name: str) -> str:
    """The stack name becomes WorkshopName, which the templates restrict."""
    if not WORKSHOP_NAME_PATTERN.fullmatch(name):
        raise Refusal(
            f"--stack-name {name!r} becomes the WorkshopName, which must be 3-41 characters: "
            "lowercase letters, digits and hyphens, starting with a letter or digit"
        )
    return name


def cloudfront_acl_names(ctx: Context) -> list[str]:
    """Names of the account's CLOUDFRONT-scope web ACLs, always read from us-east-1."""
    wafv2 = ctx.client("wafv2", WAF_REGION)
    names: list[str] = []
    marker: str | None = None
    while True:
        arguments: dict[str, Any] = {"Scope": "CLOUDFRONT", "Limit": 100}
        if marker:
            arguments["NextMarker"] = marker
        page = wafv2.list_web_acls(**arguments)
        names += [acl["Name"] for acl in page.get("WebACLs", [])]
        marker = page.get("NextMarker")
        if not marker:
            return names


def acl_collision(ctx: Context) -> str | None:
    """A problem statement when the web ACL this stack would create already exists."""
    if ctx.region != WAF_REGION:
        return None
    name = f"{ctx.stack_name}-mosaic-api"
    if name not in cloudfront_acl_names(ctx):
        return None
    return (
        f"a CloudFront web ACL named {name} already exists in this account (another "
        f"deployment used the WorkshopName {ctx.stack_name}); pass a different --stack-name"
    )


def root_stacks(ctx: Context) -> list[dict[str, Any]]:
    """Every non-nested stack in the Region."""
    cloudformation = ctx.client("cloudformation")
    stacks: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        page = cloudformation.describe_stacks(**({"NextToken": token} if token else {}))
        stacks += [s for s in page["Stacks"] if "ParentId" not in s]
        token = page.get("NextToken")
        if not token:
            return stacks


def check_name_collisions(ctx: Context) -> None:
    """Report what an earlier deployment in this account would collide with."""
    problem = acl_collision(ctx)
    verdict(
        ctx,
        problem is None,
        f"no CloudFront web ACL named {ctx.stack_name}-mosaic-api"
        + ("" if ctx.region == WAF_REGION else f" (only created in {WAF_REGION})"),
        f"{problem}",
    )
    stacks = root_stacks(ctx)
    names = {stack["StackName"] for stack in stacks}
    verdict(
        ctx,
        ctx.stack_name not in names,
        f"no stack named {ctx.stack_name} in {ctx.region}",
        "run `status`, then `teardown`, or pass a different --stack-name",
    )
    if STAGING_STACK_NAME in names:
        ctx.out(
            f"     note: the staging stack {STAGING_STACK_NAME} is up (`staging down` after the build)"
        )
    tagged = sorted(
        stack["StackName"]
        for stack in stacks
        if stack["StackName"] not in (ctx.stack_name, STAGING_STACK_NAME)
        and {"Key": "Workshop", "Value": ctx.stack_name} in stack.get("Tags", [])
    )
    if tagged:
        ctx.out(
            f"     note: other stacks tagged Workshop={ctx.stack_name}: {', '.join(tagged)}"
        )


def require_free_workshop_name(ctx: Context) -> None:
    """Refuse before CreateStack when the WorkshopName's web ACL is already taken."""
    problem = acl_collision(ctx)
    if problem:
        raise Refusal(problem)
    ctx.out(f"    WorkshopName {ctx.stack_name} is free")


def workshop_name_step(ctx: Context) -> Step:
    return Step(
        f"refuse if the web ACL {ctx.stack_name}-mosaic-api already exists",
        (("wafv2", "ListWebACLs", {"Scope": "CLOUDFRONT", "Limit": 100}),),
        run=require_free_workshop_name,
    )


def check_source(ctx: Context) -> None:
    ctx.out(f"RepoUrl {ctx.repo_url} @ {ctx.source_revision}")
    problems = []
    try:
        require_clean_tree()
        require_head(ctx.source_revision)
    except Refusal as refusal:
        problems.append(str(refusal))
    ok = not problems
    verdict(ctx, ok, f"source tree clean at {ctx.source_revision}", "; ".join(problems))
    template = (CLOUDFORMATION / MAIN_TEMPLATE).read_text(encoding="utf-8")
    pattern = re.search(
        r"^  RepoUrl:\n(?:^    .*\n)*?^    AllowedPattern: '(.*)'",
        template,
        re.MULTILINE,
    )
    if pattern and not re.fullmatch(pattern.group(1), ctx.repo_url):
        verdict(
            ctx,
            False,
            f"RepoUrl {ctx.repo_url} satisfies the main template's AllowedPattern",
            f"the template only accepts {pattern.group(1)}; relax the pattern in "
            "deploy/cloudformation/hybrid-retrieval-main.yml before deploying a fork",
        )
    reason = probe_anonymous_fetch(ctx.repo_url, ctx.source_revision)
    verdict(
        ctx,
        reason is None,
        f"anonymous fetch of {ctx.repo_url}@{ctx.source_revision[:12]}",
        f"{reason}; push the commit and make the repository public (the host clones "
        "without credentials)",
    )


def plan_check(ctx: Context) -> list[Step]:
    probe = (("git", "fetch --depth 1 origin <sha>", {"repo": ctx.repo_url}),)
    return [
        Step("identity", (("sts", "GetCallerIdentity", {}),), run=check_identity),
        Step(
            "Bedrock model access (scripts/checks/check_model_access.py)",
            run=check_models,
        ),
        Step(
            "service-linked roles",
            tuple(
                ("iam", "GetRole", {"RoleName": role})
                for role in SERVICE_LINKED_ROLES.values()
            ),
            run=check_service_linked_roles,
        ),
        Step(
            "EC2 vCPU quota",
            (
                (
                    "service-quotas",
                    "GetServiceQuota",
                    {"ServiceCode": "ec2", "QuotaCode": STANDARD_VCPU_QUOTA},
                ),
            ),
            run=check_quota,
        ),
        Step(
            "VPC and Elastic IP capacity",
            network_capacity_step().calls,
            run=check_network_capacity,
        ),
        Step(
            "WorkshopName collisions with earlier deployments",
            (
                ("wafv2", "ListWebACLs", {"Scope": "CLOUDFRONT", "Limit": 100}),
                ("cloudformation", "DescribeStacks", {}),
            ),
            run=check_name_collisions,
        ),
        Step("clean source tree and anonymous fetch", probe, run=check_source),
    ]


def run_check(ctx: Context) -> int:
    """Run every check, never stopping at the first failure; non-zero when any FAIL."""
    failures: list[str] = []
    original = ctx.out

    def tracking(line: str) -> None:
        if line.startswith("FAIL"):
            failures.append(line)
        original(line)

    ctx.out = tracking
    run_plan(plan_check(ctx), ctx)
    ctx.out = original
    return 1 if failures else 0


# --------------------------------------------------------------------------------------
# Plans: stacks.
# --------------------------------------------------------------------------------------
def template_url(ctx: Context, release: Release, name: str) -> str:
    return f"https://{ctx.bucket}.s3.{ctx.region}.amazonaws.com/releases/{release.revision}/{name}"


def stack_parameters(values: dict[str, str]) -> list[dict[str, str]]:
    return [{"ParameterKey": k, "ParameterValue": v} for k, v in values.items()]


def stack_info(ctx: Context) -> dict[str, Any] | None:
    """The stack's description, or None once it no longer exists."""
    try:
        stacks = ctx.client("cloudformation").describe_stacks(StackName=ctx.stack_name)
    except Exception as error:
        if "does not exist" in str(error):
            return None
        raise
    return stacks["Stacks"][0]


def stack_status(ctx: Context) -> str | None:
    """The stack's status, or None once it no longer exists."""
    info = stack_info(ctx)
    return info["StackStatus"] if info else None


#: wait_for_stack(update_from=...) default: the wait is not for an update.
NOT_UPDATING = object()


def wait_for_stack(ctx: Context, goal: str, *, update_from: Any = NOT_UPDATING) -> None:
    """Poll until the stack reaches ``goal`` (CREATE_, UPDATE_ or DELETE_COMPLETE).

    Only statuses ending in _COMPLETE or _FAILED are terminal, so a rollback is waited
    out; ROLLBACK_COMPLETE or DELETE_FAILED then ends the wait as a failure. For an
    update, ``update_from`` is the stack's LastUpdatedTime before the change set ran, so
    an UPDATE_COMPLETE left over from an earlier update is not mistaken for this one.
    """
    started = time.monotonic()
    last = ""
    deleting = goal != "DELETE_COMPLETE"
    try:
        while True:
            info = stack_info(ctx)
            status = info["StackStatus"] if info else None
            deleting = deleting or status == "DELETE_IN_PROGRESS"
            if status is None and goal == "DELETE_COMPLETE":
                break
            if status is None:
                raise Refusal(
                    f"stack {ctx.stack_name} disappeared while waiting for {goal}"
                )
            idle_update = (
                update_from is not NOT_UPDATING
                and info.get("LastUpdatedTime") == update_from
            )
            stale = idle_update or (not deleting and status != "DELETE_FAILED")
            if status == goal and not idle_update:
                break
            if stale and time.monotonic() - started > STALE_DELETE_SECONDS:
                verb = "updating" if idle_update else "deleting"
                raise Refusal(
                    f"stack {ctx.stack_name} stayed {status} and never began {verb}; "
                    "CloudFormation did not accept the request. Check the stack's events."
                )
            if status.endswith(("_COMPLETE", "_FAILED")) and not stale:
                report_failed_events(ctx)
                raise Refusal(
                    f"stack {ctx.stack_name} ended in {status}, not {goal}. The first failed "
                    "resource is above; fix it, run `teardown` (or `staging down`), then retry."
                )
            if time.monotonic() - started > MAX_WAIT_SECONDS:
                raise Refusal(f"stack {ctx.stack_name} is still {status} after 3 hours")
            if status != last:
                ctx.out(f"    {status} ...")
                last = status
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        ctx.out(
            f"\ninterrupted: stack {ctx.stack_name} keeps going in CloudFormation. Check it "
            "with: deploy.py status (add --stack-name mosaic-staging for staging)"
        )
        raise
    elapsed = time.monotonic() - started
    ctx.out(f"    {goal} after {int(elapsed // 60)} min {int(elapsed % 60)} s")


EMBEDDED_STACK = re.compile(r"arn:[\w-]+:cloudformation:[\w-]+:\d+:stack/[^\s,\]\[]+")
MAX_NESTING = 4


def failed_events(ctx: Context, stack: str) -> list[dict[str, Any]]:
    """The stack's *_FAILED events, earliest first; empty when they cannot be read."""
    try:
        events = ctx.client("cloudformation").describe_stack_events(StackName=stack)
    except Exception:  # noqa: BLE001 - diagnostics must not hide the original failure
        return []
    failed = [
        e
        for e in events["StackEvents"]
        if str(e.get("ResourceStatus", "")).endswith("FAILED")
    ]
    return list(reversed(failed))


def report_failed_events(
    ctx: Context, stack: str | None = None, depth: int = 0, seen: set[str] | None = None
) -> None:
    """Print the earliest failed events, following embedded stacks to the real cause.

    A parent's reason only says "Embedded stack <arn> was not successfully created"; the
    nested stack's own events (still readable after rollback) hold the cause.
    """
    seen = seen if seen is not None else set()
    stack = stack or ctx.stack_name
    seen.add(stack)
    indent = "    " * (depth + 1)
    for event in failed_events(ctx, stack)[:5]:
        reason = event.get("ResourceStatusReason", "")
        ctx.out(
            f"{indent}{event['LogicalResourceId']}: {event['ResourceStatus']}: {reason}"
        )
        for nested in EMBEDDED_STACK.findall(reason):
            nested = nested.rstrip(".:")
            if nested not in seen and depth < MAX_NESTING:
                ctx.out(f"{indent}  in embedded stack {nested.split('/')[1]}:")
                report_failed_events(ctx, nested, depth + 1, seen)


TOKEN = re.compile(r"(tkn=)[^&\s]+")


def print_outputs(ctx: Context, *, show_token: bool) -> None:
    stack = ctx.client("cloudformation").describe_stacks(StackName=ctx.stack_name)[
        "Stacks"
    ][0]
    ctx.out(f"stack {stack['StackName']}: {stack['StackStatus']}")
    for output in stack.get("Outputs", []):
        value = output["OutputValue"]
        if not show_token:
            value = TOKEN.sub(r"\1<redacted; pass --show-token>", value)
        ctx.out(f"  {output['OutputKey']}: {value}")


def refuse_existing_stack(ctx: Context) -> None:
    status = stack_status(ctx)
    if status is not None:
        raise Refusal(
            f"stack {ctx.stack_name} already exists ({status}). Run `status` to inspect it, "
            "`teardown` (or `staging down`) to remove it, or pass a different --stack-name."
        )


def require_published_release(ctx: Context, release: Release) -> None:
    """Refuse to create the stack unless `publish` already uploaded this release."""
    s3 = ctx.client("s3")
    missing = [
        key
        for key in published_release_keys(release)
        if head_sha256(s3, ctx.bucket, key)[1] is None
    ]
    if missing:
        raise Refusal(
            f"s3://{ctx.bucket}/ lacks {', '.join(missing)}. Run publish first (same "
            "--region, --bucket and commit), then rerun."
        )
    ctx.out("    the release is published")


def published_release_keys(release: Release) -> list[str]:
    prefix = f"releases/{release.revision}/"
    return [
        prefix + "RELEASE.json",
        prefix + "mosaic-bootstrap.sh",
        prefix + MAIN_TEMPLATE,
        release.launcher_name,
    ]


def published_release_step(ctx: Context, release: Release) -> Step:
    return Step(
        "refuse unless publish already uploaded this release (RELEASE.json, bootstrap, main "
        "template, launcher package)",
        tuple(
            ("s3", "HeadObject", {"Bucket": ctx.bucket, "Key": key})
            for key in published_release_keys(release)
        ),
        run=lambda c: require_published_release(c, release),
    )


def stack_absent_step(ctx: Context) -> Step:
    return Step(
        f"refuse if stack {ctx.stack_name} already exists",
        (("cloudformation", "DescribeStacks", {"StackName": ctx.stack_name}),),
        run=refuse_existing_stack,
    )


def probe_step(ctx: Context) -> Step:
    def run(c: Context) -> None:
        reason = probe_anonymous_fetch(c.repo_url, c.source_revision)
        if reason:
            raise Refusal(
                f"the host could not clone {c.repo_url}@{c.source_revision[:12]} anonymously "
                f"({reason}). Push the commit and make the repository public."
            )
        c.out("    anonymous clone works")

    return Step(
        "confirm the host can clone the fork anonymously (git fetch --depth 1)",
        (("git", "fetch", {"repo": ctx.repo_url, "revision": ctx.source_revision}),),
        run=run,
    )


def signed_status(ctx: Context, url: str) -> int:
    """HTTP status of a SigV4-signed GET that never follows a redirect."""
    import urllib.error
    import urllib.request

    from botocore.auth import S3SigV4Auth
    from botocore.awsrequest import AWSRequest

    request = AWSRequest(method="GET", url=url)
    S3SigV4Auth(ctx.session_credentials(), "s3", ctx.region).add_auth(request)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(NoRedirect)
    prepared = urllib.request.Request(url, headers=dict(request.headers.items()))
    try:
        with opener.open(prepared, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:  # URLError, timeouts and resets while DNS or TLS settles
        return NETWORK_ERROR


def wait_for_global_endpoint(ctx: Context, release: Release) -> None:
    """Wait until the bucket's global S3 name answers directly, not with a redirect.

    The main template loads its nested stacks from ``<bucket>.s3.amazonaws.com``, which
    redirects (307) for a new bucket outside us-east-1 until DNS catches up.
    """
    if ctx.region == "us-east-1":
        return
    url = f"https://{ctx.bucket}.s3.amazonaws.com/releases/{release.revision}/RELEASE.json"
    deadline = time.monotonic() + 15 * 60
    while True:
        code = signed_status(ctx, url)
        if code == 200:
            ctx.out("    the bucket's global endpoint answers")
            return
        if code not in (301, 307, 400, NETWORK_ERROR):
            raise Refusal(
                f"{url} answered HTTP {code}; check the bucket policy and keys"
            )
        if time.monotonic() > deadline:
            answer = "no HTTP answer" if code == NETWORK_ERROR else f"HTTP {code}"
            raise Refusal(
                f"{url} last gave {answer} (or a redirect) after 15 minutes; wait a few "
                "minutes and rerun publish"
            )
        ctx.out("    waiting for the bucket's global endpoint ...")
        time.sleep(15)


def global_endpoint_step(ctx: Context, release: Release) -> Step:
    url = f"https://{ctx.bucket}.s3.amazonaws.com/releases/{release.revision}/RELEASE.json"
    return Step(
        "wait for the bucket's global endpoint to serve the release without a redirect",
        (("https", "GET", {"url": url}),),
        run=lambda c: wait_for_global_endpoint(c, release),
    )


def create_stack_step(
    ctx: Context,
    release: Release,
    template: str,
    values: dict[str, str],
    capabilities: bool,
) -> Step:
    params: dict[str, Any] = {
        "StackName": ctx.stack_name,
        "TemplateURL": template_url(ctx, release, template),
        "Parameters": stack_parameters(values),
        "Capabilities": [
            "CAPABILITY_IAM",
            "CAPABILITY_NAMED_IAM",
            "CAPABILITY_AUTO_EXPAND",
        ]
        if capabilities
        else [],
        "Tags": [{"Key": "Workshop", "Value": ctx.stack_name}],
    }
    return Step(
        f"create stack {ctx.stack_name}", (("cloudformation", "CreateStack", params),)
    )


def plan_deploy(ctx: Context) -> list[Step]:
    validate_workshop_name(ctx.stack_name)
    release = prepare_source(ctx)
    values = {
        "WorkshopName": ctx.stack_name,
        "RepoUrl": ctx.repo_url,
        **release.parameters(),
        "AssetsBucketName": ctx.bucket,
        "AssetsBucketPrefix": "",
        "PublicAssetsBucketName": "",
        "PublicAssetsBucketPrefix": "",
    }
    started: list[float] = []

    def create(c: Context) -> None:
        started.append(time.monotonic())
        execute_calls(c, create_step)

    create_step = create_stack_step(
        ctx, release, MAIN_TEMPLATE, values, capabilities=True
    )
    create_step.run = create

    def finish(c: Context) -> None:
        wait_for_stack(c, "CREATE_COMPLETE")
        elapsed = time.monotonic() - started[0]
        c.out(f"deploy took {int(elapsed // 60)} min {int(elapsed % 60)} s")
        print_outputs(c, show_token=True)

    wait = Step(
        "wait for CREATE_COMPLETE and print outputs (the CodeEditorURL token prints once)",
        (("cloudformation", "DescribeStacks", {"StackName": ctx.stack_name}),),
        run=finish,
    )
    return [
        stack_absent_step(ctx),
        published_release_step(ctx, release),
        workshop_name_step(ctx),
        network_capacity_step(),
        service_linked_role_step(),
        probe_step(ctx),
        global_endpoint_step(ctx, release),
        create_step,
        wait,
    ]


def plan_status(ctx: Context, *, show_token: bool) -> list[Step]:
    return [
        Step(
            f"describe stack {ctx.stack_name}",
            (("cloudformation", "DescribeStacks", {"StackName": ctx.stack_name}),),
            run=lambda c: print_outputs(c, show_token=show_token),
        )
    ]


def plan_staging_up(ctx: Context) -> list[Step]:
    validate_workshop_name(ctx.stack_name)
    release = prepare_source(ctx)
    values = {
        "WorkshopName": ctx.stack_name,
        "RepoUrl": ctx.repo_url,
        "SourceRevision": release.source_revision,
        "InfrastructureRevision": release.revision,
        "AssetsBucketName": ctx.bucket,
        "AssetsBucketPrefix": "",
    }
    assets = [a for a in release_assets(release) if "/" in a.key]
    create = create_stack_step(
        ctx, release, STAGING_TEMPLATE, values, capabilities=True
    )

    def finish(c: Context) -> None:
        wait_for_stack(c, "CREATE_COMPLETE")
        print_outputs(c, show_token=True)
        c.out(
            "next: open the SessionCommand shell and run `mosaic-catalog-bundle`; its upload "
            "step writes the bundle and contracts to the bucket. Then `staging down` and "
            "`contracts pull`"
        )

    wait = Step(
        "wait for CREATE_COMPLETE, print the Session Manager command",
        (("cloudformation", "DescribeStacks", {"StackName": ctx.stack_name}),),
        run=finish,
    )
    return [
        stack_absent_step(ctx),
        *bucket_steps(ctx),
        *asset_steps(ctx, assets),
        network_capacity_step(),
        service_linked_role_step(),
        probe_step(ctx),
        create,
        wait,
    ]


UPDATABLE = ("CREATE_COMPLETE", "UPDATE_COMPLETE")
NO_CHANGES = ("didn't contain changes", "No updates are to be performed")


def staging_template_bytes() -> bytes:
    return (CLOUDFORMATION / STAGING_TEMPLATE).read_bytes()


def current_staging_parameters(ctx: Context) -> dict[str, str]:
    """The running staging stack's parameters; it must exist and be settled."""
    info = stack_info(ctx)
    if info is None:
        raise Refusal(f"stack {ctx.stack_name} does not exist; run `staging up` first")
    if info["StackStatus"] not in UPDATABLE:
        raise Refusal(
            f"stack {ctx.stack_name} is {info['StackStatus']}; wait for it to settle, or "
            "`staging down` and `staging up` again"
        )
    return {p["ParameterKey"]: p.get("ParameterValue", "") for p in info["Parameters"]}


def wait_for_change_set(ctx: Context, name: str) -> dict[str, Any]:
    cloudformation = ctx.client("cloudformation")
    while True:
        described = cloudformation.describe_change_set(
            StackName=ctx.stack_name, ChangeSetName=name
        )
        if described["Status"] in ("CREATE_COMPLETE", "FAILED"):
            return described
        time.sleep(5)


def discard_change_set(ctx: Context, name: str) -> None:
    ctx.client("cloudformation").delete_change_set(
        StackName=ctx.stack_name, ChangeSetName=name
    )


def replaced_resources(change_set: dict[str, Any]) -> list[str]:
    """Logical ids of resources the change set would replace or remove."""
    risky = []
    for change in change_set.get("Changes", []):
        resource = change.get("ResourceChange", {})
        if resource.get("Replacement") == "True" or resource.get("Action") == "Remove":
            risky.append(resource.get("LogicalResourceId", "?"))
    return risky


def update_staging(ctx: Context) -> None:
    """Re-upload the staging template and update the running stack in place."""
    parameters = current_staging_parameters(ctx)
    revision = parameters["InfrastructureRevision"]
    body = staging_template_bytes()
    key = f"releases/{revision}/{STAGING_TEMPLATE}"
    published, size = head_sha256(ctx.client("s3"), ctx.bucket, key)
    if size is not None and published == sha256_bytes(body):
        raise Refusal(
            f"nothing changed: s3://{ctx.bucket}/{key} already holds this staging template"
        )
    asset = Asset(key, sha256_bytes(body), len(body), data=body, immutable=False)
    upload_asset(ctx, asset)
    name = f"update-{asset.sha256[:12]}-{int(time.time())}"
    cloudformation = ctx.client("cloudformation")
    cloudformation.create_change_set(
        StackName=ctx.stack_name,
        ChangeSetName=name,
        ChangeSetType="UPDATE",
        TemplateURL=(f"https://{ctx.bucket}.s3.{ctx.region}.amazonaws.com/{key}"),
        Parameters=[{"ParameterKey": k, "UsePreviousValue": True} for k in parameters],
        Capabilities=[
            "CAPABILITY_IAM",
            "CAPABILITY_NAMED_IAM",
            "CAPABILITY_AUTO_EXPAND",
        ],
    )
    described = wait_for_change_set(ctx, name)
    reason = described.get("StatusReason", "")
    if described["Status"] == "FAILED":
        discard_change_set(ctx, name)
        if any(marker in reason for marker in NO_CHANGES):
            raise Refusal(
                "nothing changed: CloudFormation found no difference to apply"
            )
        raise Refusal(f"CloudFormation rejected the update: {reason}")
    risky = replaced_resources(described)
    if risky:
        discard_change_set(ctx, name)
        raise Refusal(
            f"the update would replace or remove {', '.join(risky)}, which would lose the "
            "builder's /workshop work directory. Nothing was applied; use `staging down` "
            "and `staging up` if you accept that."
        )
    before = stack_info(ctx).get("LastUpdatedTime")
    cloudformation.execute_change_set(StackName=ctx.stack_name, ChangeSetName=name)
    wait_for_stack(ctx, "UPDATE_COMPLETE", update_from=before)
    ctx.out(
        "    the running builder has the new template; its work directory is untouched"
    )


def plan_staging_update(ctx: Context) -> list[Step]:
    validate_workshop_name(ctx.stack_name)
    try:
        require_clean_tree()
    except Refusal as refusal:
        if not ctx.dry_run:
            raise
        ctx.out(f"warning (dry run, a real run would refuse): {refusal}")
    stack = {"StackName": ctx.stack_name}
    return [
        Step(
            "re-upload the staging template and update the running stack in place (a change "
            "set first; refuse when nothing changed or the builder would be replaced)",
            (
                ("cloudformation", "DescribeStacks", stack),
                (
                    "s3",
                    "HeadObject",
                    {
                        "Bucket": ctx.bucket,
                        "Key": "releases/<rev>/hybrid-retrieval-staging.yml",
                    },
                ),
                (
                    "s3",
                    "PutObject",
                    {
                        "Bucket": ctx.bucket,
                        "Key": "releases/<rev>/hybrid-retrieval-staging.yml",
                    },
                ),
                (
                    "cloudformation",
                    "CreateChangeSet",
                    {**stack, "ChangeSetType": "UPDATE"},
                ),
                ("cloudformation", "DescribeChangeSet", stack),
                ("cloudformation", "ExecuteChangeSet", stack),
            ),
            run=update_staging,
        )
    ]


def require_bundle_uploaded(ctx: Context, *, force: bool) -> None:
    """Refuse to delete the builder before its upload finished, unless forced.

    The build uploads the bundle first and the two contracts last, so their presence with
    sha256 metadata proves completion. The committed contracts are not consulted: they
    still describe the previous bundle, which may have had a different part count.
    """
    s3 = ctx.client("s3")
    missing = []
    for key in CONTRACT_FILES:
        sha256, size = head_sha256(s3, ctx.bucket, key)
        if size is None or not sha256:
            missing.append(key)
    if missing and not force:
        raise Refusal(
            f"the builder's upload has not finished; s3://{ctx.bucket}/ lacks (or has no "
            f"sha256 metadata on): {', '.join(missing)}. Follow `tail -f "
            "/workshop/catalog-bundle.log` on the builder, or pass --force to delete it anyway."
        )
    if missing:
        ctx.out(f"    --force: deleting although {', '.join(missing)} is not uploaded")
    else:
        ctx.out("    both contracts are in the bucket; the builder is expendable")


def plan_staging_down(ctx: Context, *, force: bool = False) -> list[Step]:
    check = Step(
        f"confirm the build finished: both contracts are in s3://{ctx.bucket}/ with sha256 "
        "metadata (they are uploaded last, and the bucket is not owned by this stack, so "
        "deleting the builder is safe once they are)",
        tuple(
            ("s3", "HeadObject", {"Bucket": ctx.bucket, "Key": k})
            for k in CONTRACT_FILES
        ),
        run=lambda c: require_bundle_uploaded(c, force=force),
    )
    return [check, discover_step(ctx), *plan_delete(ctx), report_step(staging=True)]


def plan_delete(ctx: Context) -> list[Step]:
    delete = Step(
        f"delete stack {ctx.stack_name}, first deleting what an earlier teardown set aside "
        "once AgentCore's interface no longer holds it",
        (
            ("cloudformation", "ListStackResources", {"StackName": ctx.stack_name}),
            ("cloudformation", "DeleteStack", {"StackName": ctx.stack_name}),
        ),
        run=delete_stack_root,
    )
    wait = Step(
        "wait for DELETE_COMPLETE; if only an AgentCore network interface blocks it, "
        "delete everything else and say when to finish",
        (
            ("cloudformation", "DescribeStacks", {"StackName": ctx.stack_name}),
            ("ec2", "DescribeNetworkInterfaces", {"Filters": "<the stack's groups>"}),
        ),
        run=wait_for_delete,
    )
    return [delete, wait]


AGENTCORE_INTERFACE_TYPE = "agentic_ai"
AGENTCORE_MANAGED_TAG = "AmazonBedrockAgentCoreManaged"
AGENTCORE_RELEASE_HOURS = 8
NESTED_STACK_TYPE = "AWS::CloudFormation::Stack"
SECURITY_GROUP_TYPE = "AWS::EC2::SecurityGroup"


def security_groups_by_root_resource(ctx: Context) -> dict[str, list[str]]:
    """Each root-level resource that is, or holds, a security group not yet deleted."""
    cloudformation = ctx.client("cloudformation")
    groups: dict[str, list[str]] = {}

    def walk(stack: str, owner: str | None) -> None:
        pages = cloudformation.get_paginator("list_stack_resources").paginate(
            StackName=stack
        )
        for page in pages:
            for resource in page["StackResourceSummaries"]:
                if resource.get("ResourceStatus") == "DELETE_COMPLETE":
                    continue
                physical = resource.get("PhysicalResourceId", "")
                logical = owner or resource["LogicalResourceId"]
                if resource["ResourceType"] == NESTED_STACK_TYPE and physical:
                    walk(physical, logical)
                elif resource["ResourceType"] == SECURITY_GROUP_TYPE and physical:
                    groups.setdefault(logical, []).append(physical)

    walk(ctx.stack_name, None)
    return groups


def held_by_agentcore(ctx: Context) -> tuple[list[str], list[str]]:
    """Root-level resources whose security groups an AgentCore interface still uses.

    Returns:
        The root logical IDs to set aside, and the interfaces that hold them.
    """
    groups = security_groups_by_root_resource(ctx)
    group_ids = sorted({group for ids in groups.values() for group in ids})
    if not group_ids:
        return [], []
    found = ctx.client("ec2").describe_network_interfaces(
        Filters=[{"Name": "group-id", "Values": group_ids}]
    )["NetworkInterfaces"]
    interfaces = [
        interface
        for interface in found
        if interface.get("InterfaceType") == AGENTCORE_INTERFACE_TYPE
        or any(
            tag.get("Key") == AGENTCORE_MANAGED_TAG
            for tag in interface.get("TagSet", [])
        )
    ]
    used = {
        g["GroupId"] for interface in interfaces for g in interface.get("Groups", [])
    }
    held = sorted(logical for logical, ids in groups.items() if used & set(ids))
    return held, sorted(interface["NetworkInterfaceId"] for interface in interfaces)


def set_aside_by_earlier_teardown(ctx: Context) -> list[dict[str, Any]]:
    """Root stacks and security groups an earlier teardown set aside.

    A delete with RetainResources leaves them DELETE_SKIPPED, and a later DeleteStack
    retries only DELETE_FAILED resources, so CloudFormation never deletes them again
    and the VPC around them never empties.
    """
    paginator = ctx.client("cloudformation").get_paginator("list_stack_resources")
    try:
        summaries = [
            summary
            for page in paginator.paginate(StackName=ctx.stack_name)
            for summary in page["StackResourceSummaries"]
        ]
    except Exception as error:
        if "does not exist" in str(error):
            return []
        raise
    return [
        summary
        for summary in summaries
        if summary.get("ResourceStatus") == "DELETE_SKIPPED"
        and summary["ResourceType"] in (NESTED_STACK_TYPE, SECURITY_GROUP_TYPE)
        and summary.get("PhysicalResourceId")
    ]


def delete_stack_root(ctx: Context) -> None:
    """Delete the stack, first finishing what an earlier teardown set aside.

    While AgentCore's interface still uses their security groups they stay aside, and
    `wait_for_delete` sets them aside again and says when to come back.
    """
    set_aside = set_aside_by_earlier_teardown(ctx)
    if set_aside:
        held, interfaces = held_by_agentcore(ctx)
        if held:
            ctx.out(
                f"    {', '.join(held)} stay set aside: AgentCore's interface "
                f"({', '.join(interfaces)}) still uses their security groups"
            )
        else:
            delete_set_aside(ctx, set_aside)
    ctx.client("cloudformation").delete_stack(StackName=ctx.stack_name)


def delete_set_aside(ctx: Context, set_aside: list[dict[str, Any]]) -> None:
    """Nested stacks first, because their groups may refer to the root's groups."""
    for summary in set_aside:
        if summary["ResourceType"] != NESTED_STACK_TYPE:
            continue
        ctx.out(
            f"    deleting {summary['LogicalResourceId']}, set aside by an earlier teardown"
        )
        nested = replace(ctx, stack_name=summary["PhysicalResourceId"])
        nested.client("cloudformation").delete_stack(StackName=nested.stack_name)
        wait_for_stack(nested, "DELETE_COMPLETE")
    for summary in set_aside:
        if summary["ResourceType"] != SECURITY_GROUP_TYPE:
            continue
        ctx.out(
            f"    deleting {summary['LogicalResourceId']}, set aside by an earlier teardown"
        )
        try:
            ctx.client("ec2").delete_security_group(
                GroupId=summary["PhysicalResourceId"]
            )
        except Exception as error:
            if error_code(error) != "InvalidGroup.NotFound":
                raise


def wait_for_delete(ctx: Context) -> None:
    """Wait for the delete; when AgentCore's interface blocks it, remove what bills.

    AgentCore keeps a VPC runtime's network interface for up to 8 hours after the runtime
    is deleted, and only AWS can remove it, so the security groups it uses (and the VPC
    around them) cannot be deleted until then. The rest is deleted now by a second delete
    that sets those resources aside; a later `teardown` finishes once the interface goes.
    """
    try:
        wait_for_stack(ctx, "DELETE_COMPLETE")
        return
    except Refusal:
        held, interfaces = held_by_agentcore(ctx)
        if not held:
            raise
    ctx.out(
        f"    an AgentCore network interface ({', '.join(interfaces)}) still uses the "
        f"security groups in {', '.join(held)}; AWS removes it up to "
        f"{AGENTCORE_RELEASE_HOURS} hours after the runtimes are deleted, and only AWS can"
    )
    ctx.out("    deleting everything else now, setting those resources aside")
    ctx.client("cloudformation").delete_stack(
        StackName=ctx.stack_name, RetainResources=held
    )
    try:
        wait_for_stack(ctx, "DELETE_COMPLETE")
    except Refusal:
        pass
    ctx.pending.append(
        f"teardown is not finished: what remains costs nothing (the VPC, a private subnet, "
        f"the security groups and AWS's interface), and the database, host, NAT gateway, "
        f"distributions and runtimes are gone. Run `teardown` again after the interface "
        f"is gone (up to {AGENTCORE_RELEASE_HOURS} hours) to delete the rest; check with: "
        f"aws ec2 describe-network-interfaces --network-interface-ids {' '.join(interfaces)}"
    )


# --------------------------------------------------------------------------------------
# Plans: teardown.
# --------------------------------------------------------------------------------------
def collect_resources(ctx: Context, stack: str, found: dict[str, list[str]]) -> None:
    """Gather cluster and runtime identifiers from a stack and its nested stacks."""
    cloudformation = ctx.client("cloudformation")
    pages = cloudformation.get_paginator("list_stack_resources").paginate(
        StackName=stack
    )
    for page in pages:
        for resource in page["StackResourceSummaries"]:
            kind = resource["ResourceType"]
            physical = resource.get("PhysicalResourceId", "")
            if kind == NESTED_STACK_TYPE and physical:
                collect_resources(ctx, physical, found)
            elif kind in ("AWS::RDS::DBCluster", "AWS::BedrockAgentCore::Runtime"):
                found.setdefault(kind, []).append(physical.rsplit("/", 1)[-1])


def discover_resources(ctx: Context) -> None:
    """Record what teardown must look for afterwards; the stack's resources vanish."""
    found: dict[str, list[str]] = {}
    try:
        collect_resources(ctx, ctx.stack_name, found)
    except Exception as error:  # noqa: BLE001 - a stack already gone has nothing to record
        ctx.out(f"    could not list stack resources ({error_code(error) or error})")
    ctx.discovered = found
    for cluster in found.get("AWS::RDS::DBCluster", []):
        try:
            described = ctx.client("rds").describe_db_clusters(
                DBClusterIdentifier=cluster
            )
            resource_id = described["DBClusters"][0]["DbClusterResourceId"]
        except Exception as error:  # noqa: BLE001 - must not abort the teardown
            ctx.out(
                f"    could not describe cluster {cluster} ({error_code(error) or error})"
            )
            continue
        ctx.discovered.setdefault("DbClusterResourceId", []).append(resource_id)


def leftover_log_groups(ctx: Context) -> list[str]:
    prefixes = [f"/mosaic/{ctx.stack_name}/", f"{ctx.stack_name}-BuilderLogs-"]
    prefixes += [
        f"/aws/rds/cluster/{c}/" for c in ctx.discovered.get("AWS::RDS::DBCluster", [])
    ]
    prefixes += [
        f"/aws/bedrock-agentcore/runtimes/{r}"
        for r in ctx.discovered.get("AWS::BedrockAgentCore::Runtime", [])
    ]
    logs = ctx.client("logs")
    names: list[str] = []
    for prefix in prefixes:
        for page in logs.get_paginator("describe_log_groups").paginate(
            logGroupNamePrefix=prefix
        ):
            names += [group["logGroupName"] for group in page["logGroups"]]
    return names


def transaction_search_state(ctx: Context) -> str:
    """One line on the account-wide trace setting the stack's deletion puts back."""
    try:
        current = ctx.client("xray").get_trace_segment_destination()
    except Exception as error:  # noqa: BLE001 - a report line must not fail the teardown
        return f"  Transaction Search: not read ({type(error).__name__}); check it yourself"
    destination = current.get("Destination", "unknown")
    groups = ("aws/spans", "/aws/application-signals/data")
    try:
        logs = ctx.client("logs")
        remaining = [
            name
            for name in groups
            if any(
                group["logGroupName"] == name
                for group in logs.describe_log_groups(logGroupNamePrefix=name)[
                    "logGroups"
                ]
            )
        ]
    except Exception:  # noqa: BLE001 - a report line must not fail the teardown
        remaining = ["(not read)"]
    kept = (
        f"; the {' and '.join(remaining)} log group(s) remain with the traces recorded"
        if remaining
        else "; the two trace log groups are gone"
    )
    if destination == "CloudWatchLogs":
        return (
            "  Transaction Search: still on (destination CloudWatchLogs); it was on before "
            "the stack, or the stack's restore did not run" + kept
        )
    return (
        f"  Transaction Search: destination {destination}, as before the stack" + kept
    )


def report_staging_leftovers(ctx: Context) -> None:
    """The staging environment's leftovers; it never touches Transaction Search."""
    report_leftovers(ctx, transaction_search=False)


def report_leftovers(ctx: Context, *, transaction_search: bool = True) -> None:
    ctx.out("what the stack does not delete (report only; nothing below is removed):")
    for name in leftover_log_groups(ctx) or ["(no matching log groups)"]:
        ctx.out(
            f"  log group {name}  ->  aws logs delete-log-group --log-group-name {name}"
        )
    for resource_id in ctx.discovered.get("DbClusterResourceId", []):
        ctx.out(
            f"  RDSOSMetrics streams starting {resource_id}: delete only those streams "
            "(other databases share the group)"
        )
    if transaction_search:
        ctx.out(transaction_search_state(ctx))
    ctx.out(
        "  the staging PostgreSQL log group (/aws/rds/cluster/<id>/postgresql) and the\n"
        "  retained builder log group appear above when they exist\n"
        "  the encryption key is in its 7-day deletion window\n"
        f"  the bucket {ctx.bucket} and your fork are separate and remain"
    )


def empty_and_delete_bucket(ctx: Context) -> None:
    s3 = ctx.client("s3")
    if not bucket_has_owner_tag(s3, ctx.bucket):
        raise Refusal(
            f"bucket {ctx.bucket} lacks the tag {OWNER_TAG['Key']}={OWNER_TAG['Value']}, so "
            "this tool did not create it and will not empty it"
        )
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=ctx.bucket):
        objects = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for item in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
        ]
        if not objects:
            continue
        result = s3.delete_objects(Bucket=ctx.bucket, Delete={"Objects": objects})
        errors = result.get("Errors", [])
        if errors:
            raise Refusal(
                "S3 refused to delete "
                + ", ".join(f"{e['Key']} ({e['Code']})" for e in errors[:5])
            )
    try:
        s3.delete_bucket(Bucket=ctx.bucket)
    except Exception as error:
        if error_code(error) == "BucketNotEmpty":
            raise Refusal(
                f"bucket {ctx.bucket} is not empty: something wrote to it during the delete. "
                "Rerun `teardown --delete-bucket`."
            ) from error
        raise
    ctx.out(f"    deleted bucket {ctx.bucket}")


def discover_step(ctx: Context) -> Step:
    return Step(
        "record the database cluster and runtimes so leftovers can be found",
        (
            ("cloudformation", "ListStackResources", {"StackName": ctx.stack_name}),
            ("rds", "DescribeDBClusters", {}),
        ),
        run=discover_resources,
    )


def report_step(*, staging: bool = False) -> Step:
    return Step(
        "report what the stack leaves behind",
        (("logs", "DescribeLogGroups", {"logGroupNamePrefix": "<recorded prefixes>"}),),
        run=report_staging_leftovers if staging else report_leftovers,
    )


def plan_teardown(ctx: Context, *, delete_bucket: bool) -> list[Step]:
    if delete_bucket and not (
        ctx.bucket_explicit or ctx.bucket.startswith(BUCKET_PREFIX)
    ):
        raise Refusal(
            f"--delete-bucket will only empty a bucket named {BUCKET_PREFIX}* or one you "
            f"name with --bucket; {ctx.bucket!r} is neither"
        )
    plan = [discover_step(ctx), *plan_delete(ctx), report_step()]
    if delete_bucket:
        bucket = {"Bucket": ctx.bucket}
        plan.append(
            Step(
                f"empty and delete bucket {ctx.bucket} (only if tagged "
                f"{OWNER_TAG['Key']}=true)",
                (
                    ("s3", "GetBucketTagging", bucket),
                    ("s3", "ListObjectVersions", bucket),
                    ("s3", "DeleteObjects", bucket),
                    ("s3", "DeleteBucket", bucket),
                ),
                run=empty_and_delete_bucket,
            )
        )
    else:
        plan.append(
            Step(f"keep bucket {ctx.bucket} (pass --delete-bucket to remove it)")
        )
    return plan


# --------------------------------------------------------------------------------------
# Command line.
# --------------------------------------------------------------------------------------
def shared_flags() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--region",
        help="default: AWS_REGION, AWS_DEFAULT_REGION, then the profile's region",
    )
    shared.add_argument(
        "--bucket", help="default: mosaic-own-account-<account>-<region>"
    )
    shared.add_argument(
        "--stack-name",
        help="default: mosaic-hybrid-retrieval (staging: mosaic-staging)",
    )
    shared.add_argument("--profile", help="AWS CLI profile")
    shared.add_argument(
        "--dry-run", action="store_true", help="print every AWS call, make none"
    )
    shared.add_argument("--repo-url", help="HTTPS URL of your fork (default: origin)")
    shared.add_argument("--source-revision", help="commit to deploy (default: HEAD)")
    shared.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS_DIR)
    return shared


def build_parser() -> argparse.ArgumentParser:
    shared = shared_flags()
    parser = argparse.ArgumentParser(
        description="Deploy Mosaic into your own AWS account."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "check", parents=[shared], help="verify account, models and source"
    )
    commands.add_parser(
        "publish", parents=[shared], help="upload the release and verify the bundle"
    )
    staging = commands.add_parser(
        "staging", parents=[shared], help="manage the staging stack"
    )
    staging.add_argument("action", choices=["up", "update", "down", "status"])
    staging.add_argument(
        "--force",
        action="store_true",
        help="staging down: delete even if the bundle upload is incomplete",
    )
    contracts = commands.add_parser(
        "contracts", parents=[shared], help="sync the catalog contract files"
    )
    contracts.add_argument("action", choices=["pull"])
    commands.add_parser("deploy", parents=[shared], help="create the main stack")
    status = commands.add_parser("status", parents=[shared], help="show the main stack")
    status.add_argument(
        "--show-token", action="store_true", help="print the Code Editor token"
    )
    teardown = commands.add_parser(
        "teardown", parents=[shared], help="delete the main stack"
    )
    teardown.add_argument(
        "--delete-bucket", action="store_true", help="also empty and delete the bucket"
    )
    return parser


def resolve_region(args: argparse.Namespace) -> str:
    """--region, then AWS_REGION, AWS_DEFAULT_REGION, the profile's region, us-east-1."""
    explicit = (
        args.region
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )
    if explicit:
        return explicit
    import boto3

    return boto3.Session(profile_name=args.profile).region_name or "us-east-1"


def needs_source(args: argparse.Namespace) -> bool:
    """Whether the command deploys from the checkout and so needs a repo URL and commit."""
    return args.command in ("check", "publish", "deploy") or (
        args.command == "staging" and args.action == "up"
    )


def make_context(args: argparse.Namespace) -> Context:
    staging = args.command == "staging"
    stack = args.stack_name or (STAGING_STACK_NAME if staging else MAIN_STACK_NAME)
    repo_url = source_revision = ""
    if needs_source(args):
        repo_url = validate_repo_url(
            args.repo_url or normalize_repo_url(default_repo_url())
        )
        source_revision = resolve_revision(args.source_revision or "HEAD")
    ctx = Context(
        region=resolve_region(args),
        profile=args.profile,
        bucket=args.bucket or "",
        stack_name=stack,
        dry_run=args.dry_run,
        repo_url=repo_url,
        source_revision=source_revision,
        assets_dir=args.assets_dir,
        bucket_explicit=bool(args.bucket),
    )
    if not ctx.dry_run:
        identity = ctx.client("sts").get_caller_identity()
        ctx.account = identity["Account"]
        ctx.partition = identity["Arn"].split(":")[1]
    if not ctx.bucket:
        ctx.bucket = default_bucket(ctx.account, ctx.region)
    return ctx


def plan_for(args: argparse.Namespace, ctx: Context) -> list[Step]:
    if args.command == "publish":
        return plan_publish(ctx)
    if args.command == "deploy":
        return plan_deploy(ctx)
    if args.command == "status":
        return plan_status(ctx, show_token=args.show_token)
    if args.command == "teardown":
        return plan_teardown(ctx, delete_bucket=args.delete_bucket)
    if args.command == "contracts":
        return plan_contracts_pull(ctx)
    if args.action == "up":
        return plan_staging_up(ctx)
    if args.action == "update":
        return plan_staging_update(ctx)
    if args.action == "down":
        return plan_staging_down(ctx, force=args.force)
    return plan_status(ctx, show_token=True)


CLIENT_ERROR_FIXES = {
    (
        "HeadObject",
        "403",
    ): "check that the caller has s3:ListBucket and s3:GetObject, and "
    "that the bucket belongs to this account",
    (
        "HeadBucket",
        "403",
    ): "the bucket exists but is not yours or you lack s3:ListBucket; "
    "pass a different --bucket",
    ("CreateStack", "AlreadyExistsException"): "run `status`, then `teardown` (or "
    "`staging down`), or pass a different --stack-name",
    (
        "CreateBucket",
        "BucketAlreadyExists",
    ): "another account owns that name; pass --bucket",
}
CREDENTIAL_CODES = ("ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId")


def explain_client_error(error: ClientError) -> str:
    detail = error.response.get("Error", {})
    code = detail.get("Code", "")
    operation = error.operation_name
    fix = CLIENT_ERROR_FIXES.get((operation, code))
    if fix is None and code in CREDENTIAL_CODES:
        fix = "refresh your AWS credentials (aws sso login, or set --profile)"
    if fix is None and code in ("AccessDenied", "AccessDeniedException", "403"):
        fix = "the caller lacks the permission named in the message; use an administrator role"
    text = f"{operation} {code}: {detail.get('Message', '')}"
    return text + (f"\n     fix: {fix}" if fix else "")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ctx = make_context(args)
        if args.command == "check":
            return run_check(ctx)
        run_plan(plan_for(args, ctx), ctx)
        for message in ctx.pending:
            print(f"NOT FINISHED: {message}", file=sys.stderr)
        if ctx.pending:
            return 2
    except Refusal as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return 2
    except ClientError as error:
        print(f"REFUSED: {explain_client_error(error)}", file=sys.stderr)
        return 2
    except NoCredentialsError:
        print(
            "REFUSED: no AWS credentials found\n     fix: run `aws sso login` or pass "
            "--profile",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
