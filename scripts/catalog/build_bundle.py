#!/usr/bin/env python3
"""Build the complete real-catalog assets directory from the public source files.

One orchestrator for a builder machine (repository clone, `uv`, `psql`, `make`,
Bedrock InvokeModel rights for Cohere Embed v4, and `DATABASE_URL` naming a
temporary Aurora cluster). It runs the documented operator sequence as
resumable steps and leaves:

    <assets-dir>/real-catalog/real-catalog.tar.gz.part-000 ...
    <assets-dir>/real-catalog/vocabulary/mosaic_search.*.csv.gz

and rewrites the two contract files the restore path verifies against:
`db/config/real-catalog-cache.json` and `db/config/corpus-vocabulary-cache.json`.
The `upload` step copies both to the customer's private bucket; the builder never
touches a git remote.

The contract pins products, catalog_sha256 and embedding_batches, so those are
expected to reproduce (a mismatch right after `prepare` stops the run). Review and
question samples are only approximated, and the archive and vocabulary hashes differ
on every build, because gzip stamps the time. The evidence step prints a WARN with
each count that differs from the committed contract.

Steps: fetch, prepare, embed, schema, stage, evidence, export, restore-check,
vocabulary, upload, summary. `schema` installs the extensions, tables and functions
into the empty staging database, as the event bootstrap does, so `stage` has somewhere
to load. Reviews and product questions come after `stage` because the review scan is
seeded from, and filtered against, the staged catalog. `--dry-run` prints every command
without running it.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog.corpus_vocabulary import CONTRACT as VOCABULARY_CONTRACT
from scripts.catalog.corpus_vocabulary import TABLES as VOCABULARY_TABLES
from scripts.catalog.fetch_product_questions import FILE_URL
from scripts.catalog.fetch_product_questions import FILES as PQA_FILES
from scripts.catalog.real_catalog_cache import CONTRACT, PART_BYTES

STEPS = (
    "fetch",
    "prepare",
    "embed",
    "schema",
    "stage",
    "evidence",
    "export",
    "restore-check",
    "vocabulary",
    "upload",
    "summary",
)
HELPERS = ("derive-parents", "copy-parts", "download")
DATABASE_STEPS = frozenset(
    {"schema", "stage", "evidence", "restore-check", "vocabulary"}
)
# The extensions db/sql/00_extensions.sql installs; a cluster without them cannot stage.
REQUIRED_EXTENSIONS = ("vector", "pg_trgm", "unaccent", "pgcrypto")
DEFAULT_PLAN = ROOT / "data/real-catalog-plan-v2.json"
DEFAULT_WORK_DIR = ROOT / ".local/real-products/own-account"
ARCHIVE_NAME = "real-catalog.tar.gz"
VOCABULARY_SCHEMA = "mosaic_search"
MULTI_REGION_WORKERS = 12
SINGLE_REGION_WORKERS = 4
SCRIPTS = "scripts/catalog/"
DEPLOY = "uv run python deploy/own-account/deploy.py"
BUCKET_ENV = "MOSAIC_OWN_ACCOUNT_BUCKET"
LAB_PARENTS = ROOT / "data/lab-review-parents.json"
CONTRACT_RELATIVE = "db/config/real-catalog-cache.json"
VOCABULARY_CACHE_ENV = "MOSAIC_VOCABULARY_CACHE_DIR"
DOWNLOAD_ATTEMPTS = 3
S3_ABSENT_CODES = frozenset(
    {"404", "NoSuchKey", "NotFound", "403", "AccessDenied", "Forbidden"}
)
S3_WRONG_REGION_CODES = frozenset({"301", "PermanentRedirect"})


@dataclass(frozen=True)
class Command:
    """One subprocess the orchestrator runs, with the environment it adds."""

    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()
    creates: Path | None = None
    unset: tuple[str, ...] = ()

    def render(self) -> str:
        """Return the shell form, with removed and added environment first."""
        assignments = [f"{key}={shlex.quote(value)}" for key, value in self.env]
        words = " ".join([*assignments, shlex.join(self.argv)])
        if not self.unset:
            return words
        removals = [arg for name in self.unset for arg in ("-u", name)]
        return f"{shlex.join(['env', *removals])} {words}"


@dataclass(frozen=True)
class Config:
    """Everything a step plan depends on."""

    work_dir: Path
    assets_dir: Path
    dataset_id: str
    plan_path: Path
    workers: int | None = None
    regions: tuple[str, ...] = ()
    adaptive_pacing: bool = False
    tokens_per_minute: int | None = None
    reviews_per_group: int = 5
    review_parts: int = 6
    bucket: str | None = None
    prefix: str = ""
    region: str = "us-east-1"

    @property
    def categories(self) -> tuple[str, ...]:
        """Departments the plan selects from, in plan order."""
        plan = json.loads(self.plan_path.read_text())
        return tuple(item["category"] for item in plan["sources"])

    @property
    def metadata_dir(self) -> Path:
        return self.work_dir / "metadata"

    @property
    def selection_dir(self) -> Path:
        return self.work_dir / "catalog"

    @property
    def pqa_dir(self) -> Path:
        return self.work_dir / "pqa"

    @property
    def review_dir(self) -> Path:
        return self.work_dir / "reviews"

    @property
    def archive(self) -> Path:
        return self.work_dir / ARCHIVE_NAME

    @property
    def bundle_dir(self) -> Path:
        return self.assets_dir / "real-catalog"

    @property
    def vocabulary_dir(self) -> Path:
        return self.bundle_dir / "vocabulary"

    @property
    def restore_dir(self) -> Path:
        return self.work_dir / "restore-check"

    @property
    def questions(self) -> Path:
        return self.work_dir / "questions.json"

    @property
    def parents_file(self) -> Path:
        return self.work_dir / "review-parents.json"

    def review_files(self) -> list[Path]:
        """Release review samples, named as the contract's `review_samples` keys."""
        return [
            self.review_dir / f"{name}-reviews.json" for name in sorted(self.categories)
        ]


def uv_python(script: str, *args: str) -> tuple[str, ...]:
    """Build an `uv run python` argv for a script path relative to the repository."""
    return ("uv", "run", "python", script, *args)


def helper(name: str, *args: str) -> tuple[str, ...]:
    """Build the argv that runs one of this file's own helper subcommands."""
    return uv_python(f"{SCRIPTS}build_bundle.py", name, *args)


def plan_fetch(config: Config) -> list[Command]:
    """Metadata for every plan department, and the Amazon PQA question files."""
    commands = [
        Command(
            uv_python(
                f"{SCRIPTS}fetch_catalog_metadata.py",
                category,
                "--destination",
                str(config.metadata_dir),
            )
        )
        for category in config.categories
    ]
    for name in PQA_FILES:
        target = config.pqa_dir / name
        commands.append(
            Command(
                helper(
                    "download",
                    "--url",
                    FILE_URL.format(name=name),
                    "--output",
                    str(target),
                ),
                creates=target,
            )
        )
    return commands


def plan_prepare(config: Config) -> list[Command]:
    """Select the catalog. The v2 plan, not the script's v1 default, matches the contract."""
    return [
        Command(
            uv_python(
                f"{SCRIPTS}prepare_real_catalog.py",
                "--source-root",
                str(config.metadata_dir),
                "--output",
                str(config.selection_dir),
                "--plan",
                str(config.plan_path),
            ),
            creates=config.selection_dir / "selection.json",
        )
    ]


def plan_embed(config: Config) -> list[Command]:
    """Embed with Cohere Embed v4; multi-Region adaptive pacing only when asked for."""
    workers = config.workers or (
        MULTI_REGION_WORKERS if config.regions else SINGLE_REGION_WORKERS
    )
    argv = ["--selection", str(config.selection_dir), "--workers", str(workers)]
    if config.regions:
        argv += ["--regions", *config.regions]
    if config.adaptive_pacing or config.regions:
        argv.append("--adaptive-pacing")
    if config.tokens_per_minute:
        argv += ["--tokens-per-minute", str(config.tokens_per_minute)]
    return [Command(uv_python(f"{SCRIPTS}embed_real_catalog.py", *argv))]


def plan_schema(config: Config) -> list[Command]:
    """Install the schema into the empty staging database, as the event bootstrap does."""
    return [Command(("make", "db-bootstrap-schema"))]


def plan_stage(config: Config) -> list[Command]:
    """Load records and vectors into Aurora staging, then require completeness."""
    base = ("--selection", str(config.selection_dir), "--dataset-id", config.dataset_id)
    phases = (("records",), ("embeddings",), ("verify", "--require-complete"))
    return [
        Command(uv_python(f"{SCRIPTS}stage_real_catalog.py", *base, "--phase", *phase))
        for phase in phases
    ]


def plan_evidence(config: Config) -> list[Command]:
    """Review samples seeded from the staged leaves, filtered to the catalog, plus questions."""
    commands = [
        Command(
            helper(
                "derive-parents",
                "--selection",
                str(config.selection_dir),
                "--plan",
                str(config.plan_path),
                "--lab-parents",
                str(LAB_PARENTS),
                "--output",
                str(config.parents_file),
            )
        )
    ]
    group = str(config.reviews_per_group)
    for category in config.categories:
        commands.append(
            Command(
                uv_python(
                    f"{SCRIPTS}scan_catalog_reviews.py",
                    category,
                    "--parents",
                    str(config.parents_file),
                    "--work",
                    str(config.work_dir / "review-scan" / category),
                    "--destination",
                    str(config.review_dir),
                    "--parts",
                    str(config.review_parts),
                    "--reviews-per-rating-group",
                    group,
                    "--release-per-rating-group",
                    group,
                )
            )
        )
    samples = [str(path) for path in config.review_files()]
    commands.append(
        Command(
            uv_python(
                f"{SCRIPTS}filter_catalog_reviews.py",
                "--dataset-id",
                config.dataset_id,
                "--samples",
                *samples,
            )
        )
    )
    commands.append(
        Command(
            uv_python(
                f"{SCRIPTS}fetch_product_questions.py",
                "stage",
                "--dataset-id",
                config.dataset_id,
                "--directory",
                str(config.pqa_dir),
                "--report",
                str(config.work_dir / "questions-report.json"),
                "--export",
                str(config.questions),
            )
        )
    )
    return commands


def plan_export(config: Config) -> list[Command]:
    """Write the archive and its contract, then split it into the Studio part layout."""
    cache = f"{SCRIPTS}real_catalog_cache.py"
    archive = str(config.archive)
    samples = [str(path) for path in config.review_files()]
    return [
        Command(
            uv_python(
                cache,
                "export",
                "--archive",
                archive,
                "--selection",
                str(config.selection_dir),
                "--dataset-id",
                config.dataset_id,
                "--reviews",
                *samples,
                "--questions",
                str(config.questions),
            )
        ),
        Command(
            uv_python(
                cache,
                "split",
                "--archive",
                archive,
                "--parts-dir",
                str(config.bundle_dir),
            )
        ),
    ]


def plan_restore_check(config: Config) -> list[Command]:
    """Replay the event bootstrap on a copy of the parts, because `join` deletes its inputs."""
    cache = f"{SCRIPTS}real_catalog_cache.py"
    joined = str(config.restore_dir / ARCHIVE_NAME)
    environment = (("MOSAIC_CATALOG_DATASET", config.dataset_id),)
    return [
        Command(
            helper(
                "copy-parts",
                "--source",
                str(config.bundle_dir),
                "--destination",
                str(config.restore_dir),
            )
        ),
        Command(
            uv_python(
                cache,
                "join",
                "--archive",
                joined,
                "--parts-dir",
                str(config.restore_dir),
            )
        ),
        Command(("make", "db-bootstrap-schema")),
        Command(
            uv_python(
                cache,
                "restore",
                "--archive",
                joined,
                "--selection",
                str(config.restore_dir / "selection"),
                "--report",
                str(config.work_dir / "restore-report.json"),
            ),
            unset=(VOCABULARY_CACHE_ENV,),
        ),
        Command(("make", "db-verify-bootstrap"), env=environment),
    ]


def plan_vocabulary(config: Config) -> list[Command]:
    """Export the vocabulary from the restored live schema, then verify the files."""
    vocabulary = f"{SCRIPTS}corpus_vocabulary.py"
    directory = str(config.vocabulary_dir)
    return [
        Command(
            uv_python(
                vocabulary,
                "export",
                "--schema",
                VOCABULARY_SCHEMA,
                "--directory",
                directory,
                "--contract",
                str(VOCABULARY_CONTRACT),
            )
        ),
        Command(
            uv_python(
                vocabulary,
                "verify",
                "--directory",
                directory,
                "--schema",
                VOCABULARY_SCHEMA,
            )
        ),
    ]


PLANNERS = {
    "fetch": plan_fetch,
    "prepare": plan_prepare,
    "embed": plan_embed,
    "schema": plan_schema,
    "stage": plan_stage,
    "evidence": plan_evidence,
    "export": plan_export,
    "restore-check": plan_restore_check,
    "vocabulary": plan_vocabulary,
    "upload": lambda config: [],
    "summary": lambda config: [],
}


def part_names(count: int) -> list[str]:
    """Part file names in the layout Workshop Studio and the bootstrap sync expect."""
    return [f"{ARCHIVE_NAME}.part-{index:03d}" for index in range(count)]


def vocabulary_names() -> list[str]:
    """The two vocabulary files the bootstrap syncs and verifies."""
    return [f"{VOCABULARY_SCHEMA}.{table}.csv.gz" for table in VOCABULARY_TABLES]


def layout_problems(config: Config, contract: dict) -> list[str]:
    """Compare the assets directory with the contract; return one line per defect."""
    problems = []
    parts = contract.get("parts") or []
    expected = part_names(len(parts))
    if [part["name"] for part in parts] != expected:
        problems.append(
            f"contract part names {[p['name'] for p in parts]} != {expected}"
        )
    for part in parts:
        path = config.bundle_dir / part["name"]
        if not path.is_file():
            problems.append(f"missing {path}")
        elif path.stat().st_size != part["bytes"] or part["bytes"] > PART_BYTES:
            problems.append(
                f"{path.name} is {path.stat().st_size} bytes; contract {part['bytes']}"
            )
    on_disk = sorted(p.name for p in config.bundle_dir.glob(f"{ARCHIVE_NAME}.part-*"))
    problems += [
        f"stale file {name}; trash it" for name in on_disk if name not in expected
    ]
    for name in vocabulary_names():
        if not (config.vocabulary_dir / name).is_file():
            problems.append(f"missing {config.vocabulary_dir / name}")
    return problems


def derive_review_parents(
    selection: Path, plan: dict, lab_parents: dict | None = None
) -> dict[str, list[str]]:
    """Approximate the review scan's seed.

    The seed is every catalog product whose taxonomy leaf the plan targets, plus the
    lab-pool parents in `lab_parents` that are catalog products of that department.
    The shipped bundle's seed also held parents outside the plan's leaves and came
    from a list no committed script writes, so this approximates it.
    """
    leaves = {item["category"]: set(item["leaves"]) for item in plan["sources"]}
    parents: dict[str, set[str]] = {category: set() for category in leaves}
    in_catalog: dict[str, set[str]] = {category: set() for category in leaves}
    with gzip.open(selection / "catalog.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            categories = row["original"].get("categories") or [""]
            department = row["source_department"]
            in_catalog.setdefault(department, set()).add(row["parent_asin"])
            if categories[-1] in leaves.get(department, ()):
                parents[department].add(row["parent_asin"])
    for category, asins in (lab_parents or {}).items():
        if category in parents and isinstance(asins, list):
            parents[category] |= set(asins) & in_catalog[category]
    return {category: sorted(found) for category, found in parents.items()}


def copy_parts(contract: dict, source: Path, destination: Path) -> int:
    """Copy the contract's parts so that `join`, which deletes parts, spares the originals."""
    destination.mkdir(parents=True, exist_ok=True)
    for part in contract["parts"]:
        shutil.copyfile(source / part["name"], destination / part["name"])
    return len(contract["parts"])


class ShortBodyError(OSError):
    """The response ended before the length the server announced."""


def fetch_to(url: str, partial: Path) -> None:
    """Write one response body to `partial`, rejecting a body shorter than Content-Length."""
    with (
        urllib.request.urlopen(url, timeout=60) as response,
        partial.open("wb") as target,
    ):
        shutil.copyfileobj(response, target, 1024 * 1024)
        announced = response.headers.get("Content-Length")
    if announced is not None and partial.stat().st_size != int(announced):
        raise ShortBodyError(
            f"got {partial.stat().st_size} bytes, Content-Length said {announced}"
        )


def download(
    url: str, output: Path, attempts: int = DOWNLOAD_ATTEMPTS, sleep=time.sleep
) -> None:
    """Fetch one file to a partial name, then rename; retry transient failures with backoff.

    Mid-read failures and short bodies are retried too, so a truncated file is never
    renamed into place (where the `creates` skip would keep it forever).
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    for attempt in range(1, attempts + 1):
        try:
            fetch_to(url, partial)
            break
        except urllib.error.HTTPError as error:
            if error.code < 500:
                raise
            failure = error
        except (OSError, http.client.HTTPException) as error:
            failure = error
        if attempt == attempts:
            raise ValueError(
                f"Download rule: {url} failed {attempts} times ({failure}); check the "
                "network and rerun the fetch step."
            ) from failure
        sleep(2**attempt)
    partial.replace(output)


def run_helper(argv: list[str]) -> int:
    """Dispatch the internal subcommands the step plans call."""
    parser = argparse.ArgumentParser(prog=f"build_bundle.py {argv[0]}")
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--lab-parents", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--url")
    args = parser.parse_args(argv[1:])
    if argv[0] == "derive-parents":
        lab = json.loads(args.lab_parents.read_text()) if args.lab_parents else None
        parents = derive_review_parents(
            args.selection, json.loads(args.plan.read_text()), lab
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(parents) + "\n")
        print(json.dumps({key: len(value) for key, value in parents.items()}))
    elif argv[0] == "copy-parts":
        print(
            json.dumps(
                {
                    "copied": copy_parts(
                        json.loads(CONTRACT.read_text()), args.source, args.destination
                    )
                }
            )
        )
    else:
        download(args.url, args.output)
    return 0


def load_state(config: Config) -> dict:
    """Read completed-step bookkeeping; refuse a state written for another dataset."""
    path = config.work_dir / "state.json"
    if not path.exists():
        return {"dataset_id": config.dataset_id, "steps": {}}
    try:
        state = json.loads(path.read_text())
        found = state["dataset_id"]
        steps = state["steps"]
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(
            f"State rule: {path} is not a valid state file ({error!r}); move it aside "
            "with trash and rerun. Finished artefacts are reused; steps run again."
        ) from error
    if found != config.dataset_id or not isinstance(steps, dict):
        raise ValueError(
            f"Dataset rule: {path} was built for {found!r}, not "
            f"{config.dataset_id!r}; pass the same --dataset-id or a new --work-dir."
        )
    return state


def save_state(config: Config, state: dict) -> None:
    config.work_dir.mkdir(parents=True, exist_ok=True)
    (config.work_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n")


def record_step(config: Config, state: dict, step: str, seconds: float) -> None:
    """Mark a step done and append its wall-clock time to the timings file."""
    finished = datetime.now(UTC).isoformat(timespec="seconds")
    config.work_dir.mkdir(parents=True, exist_ok=True)
    if step != "summary":
        state["steps"][step] = {"seconds": round(seconds, 1), "finished": finished}
        save_state(config, state)
    with (config.work_dir / "timings.tsv").open("a") as stream:
        stream.write(f"{step}\t{seconds:.1f}\t{finished}\n")


def invalidate_later_steps(config: Config, state: dict, step: str) -> list[str]:
    """Forget this step and every later one, so a stop mid-step cannot leave it marked done.

    Returns:
        The later steps that were forgotten.
    """
    stale = [name for name in STEPS[STEPS.index(step) + 1 :] if name in state["steps"]]
    own = state["steps"].pop(step, None)
    for name in stale:
        del state["steps"][name]
    if stale or own:
        save_state(config, state)
    if stale:
        print(f"  note: rerunning {step} invalidates {', '.join(stale)}", flush=True)
    return stale


def select_steps(first: str | None, only: str | None, state: dict) -> list[str]:
    """Pick steps: --only one, --from onward, or whatever the state has not finished."""
    for name in (first, only):
        if name is not None and name not in STEPS:
            raise ValueError(
                f"Step rule: unknown step {name!r}; choose from {', '.join(STEPS)}."
            )
    if only:
        return [only]
    if first:
        return list(STEPS[STEPS.index(first) :])
    return [step for step in STEPS if step == "summary" or step not in state["steps"]]


def execute(command: Command) -> None:
    """Run one command from the repository root, naming it on failure."""
    if command.creates and command.creates.exists():
        print(f"  skip, exists: {command.creates}", flush=True)
        return
    environment = {**os.environ, **dict(command.env)}
    for name in command.unset:
        environment.pop(name, None)
    try:
        subprocess.run(command.argv, cwd=ROOT, env=environment, check=True)
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Step command failed (exit {error.returncode}): {command.render()}\n"
            "Fix the cause and rerun the same command; finished steps are skipped."
        ) from error


def make_sts_client(region: str):
    """Boundary for the credential check; tests replace it."""
    import boto3

    return boto3.client("sts", region_name=region)


def wrong_region_error(error, bucket: str) -> ValueError:
    """Name the bucket's Region from the redirect response."""
    headers = error.response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
    region = headers.get("x-amz-bucket-region", "unknown")
    return ValueError(
        f"Bucket Region rule: {bucket} is in {region}, not the client's Region; "
        f"rerun with --region {region}."
    )


def aws_identity(region: str) -> str:
    return make_sts_client(region).get_caller_identity()["Arn"]


class CheckWarning(Exception):
    """A check that could not confirm its subject but must not stop the run."""


def bucket_reachable(config: Config) -> str:
    from botocore.exceptions import ClientError

    try:
        make_s3_client(config.region).head_bucket(Bucket=config.bucket)
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code in S3_WRONG_REGION_CODES:
            raise wrong_region_error(error, config.bucket) from error
        if code in S3_ABSENT_CODES - {"404", "NoSuchKey", "NotFound"}:
            raise CheckWarning(
                "head_bucket was denied (403); the upload path tolerates this, so "
                "continuing. Grant s3:ListBucket to confirm the bucket."
            ) from error
        raise
    return "reachable"


def database_reachable(url: str) -> str:
    """Connect once and confirm the cluster can install the extensions the schema needs.

    Raises:
        RuntimeError: when the connection fails or an extension is unavailable, so a
            database problem stops the run before hours of embedding are spent.
    """
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=10) as connection:
            version = connection.execute("SHOW server_version").fetchone()[0]
            rows = connection.execute(
                "SELECT name FROM pg_available_extensions WHERE name = ANY(%s)",
                (list(REQUIRED_EXTENSIONS),),
            ).fetchall()
    except psycopg.Error as error:
        raise RuntimeError(f"{type(error).__name__}: {error}".strip()) from error
    missing = [
        name for name in REQUIRED_EXTENSIONS if name not in {row[0] for row in rows}
    ]
    if missing:
        raise RuntimeError(
            f"PostgreSQL {version} cannot install {', '.join(missing)}; use Aurora "
            "PostgreSQL with pgvector"
        )
    return f"PostgreSQL {version}, {len(REQUIRED_EXTENSIONS)} extensions available"


def python_version_ok() -> str:
    result = subprocess.run(
        ["make", "check-python"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(
            lines[-1] if lines else f"make check-python exited {result.returncode}"
        )
    return "Python 3.13"


def environment_checks(
    steps: list[str], config: Config
) -> list[tuple[str, Callable[[], str], str]]:
    """Label, probe and fix for each environment check the selected steps need."""
    wanted = set(steps)
    checks = []
    if wanted & {"embed", "upload"}:
        checks.append(
            (
                "AWS credentials",
                lambda: aws_identity(config.region),
                "run aws sso login, or attach the instance role",
            )
        )
    if "upload" in wanted:
        checks.append(
            (
                f"bucket {config.bucket}",
                lambda: bucket_reachable(config),
                "check the name, pass --region, and grant s3:ListBucket",
            )
        )
    if DATABASE_STEPS & wanted:
        checks.append(
            (
                "database",
                lambda: database_reachable(os.environ["DATABASE_URL"]),
                "point DATABASE_URL at the staging Aurora cluster this host can reach",
            )
        )
    if wanted & {"schema", "restore-check"}:
        checks.append(
            (
                "make check-python",
                python_version_ok,
                "install Python 3.13, then run make setup",
            )
        )
    return checks


def run_environment_checks(steps: list[str], config: Config) -> None:
    """Print one ok/FAIL line per check; raise if any failed."""
    from botocore.exceptions import BotoCoreError, ClientError

    failures = 0
    for label, probe, fix in environment_checks(steps, config):
        try:
            print(f"  ok   {label}: {probe()}", flush=True)
        except CheckWarning as warning:
            print(f"  WARN {label}: {warning}", flush=True)
        except (BotoCoreError, ClientError, RuntimeError, ValueError, OSError) as error:
            print(f"  FAIL {label}: {error}. Fix: {fix}", flush=True)
            failures += 1
    if failures:
        raise ValueError(f"Preflight rule: {failures} environment check(s) failed.")


def preflight(steps: list[str], config: Config) -> None:
    """Fail before any work if the environment cannot finish the selected steps."""
    if DATABASE_STEPS & set(steps) and not os.environ.get("DATABASE_URL"):
        raise ValueError(
            "DATABASE_URL rule: not set; point it at the temporary Aurora cluster "
            "(there is no local database; see ARTIFACTS.md)."
        )
    if "upload" in steps and not config.bucket:
        raise ValueError(
            f"Bucket rule: pass --bucket or set {BUCKET_ENV}; the upload step needs the "
            "private bucket name."
        )
    needed = [
        "uv",
        *(["make", "psql"] if {"schema", "restore-check"} & set(steps) else []),
    ]
    missing = [tool for tool in needed if shutil.which(tool) is None]
    if missing:
        raise ValueError(
            f"Tool rule: {', '.join(missing)} not on PATH; install it first."
        )
    run_environment_checks(steps, config)


def normalize_prefix(prefix: str) -> str:
    """Return the key prefix with exactly one trailing slash, or empty."""
    return prefix.strip("/") + "/" if prefix.strip("/") else ""


def upload_plan(config: Config, contract: dict) -> list[tuple[Path, str]]:
    """Local file and S3 key for every object: parts, vocabulary files, both contracts."""
    prefix = normalize_prefix(config.prefix)
    bundle = [
        *part_names(len(contract.get("parts") or [])),
        *(f"vocabulary/{name}" for name in vocabulary_names()),
    ]
    items = [
        (config.bundle_dir / name, f"{prefix}real-catalog/{name}") for name in bundle
    ]
    for path in (CONTRACT, VOCABULARY_CONTRACT):
        items.append((path, f"{prefix}contracts/{path.name}"))
    return items


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def make_s3_client(region: str):
    """The only place boto3 is touched; tests replace it."""
    import boto3

    return boto3.client("s3", region_name=region)


def stored_sha256(client, bucket: str, key: str) -> str | None:
    """The sha256 metadata of an existing object, or None when it is absent.

    Without s3:ListBucket a missing key answers 403, so 403 counts as absent; a denied
    PutObject then fails clearly in `upload_file`.
    """
    from botocore.exceptions import ClientError

    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code in S3_ABSENT_CODES:
            return None
        if code in S3_WRONG_REGION_CODES:
            raise wrong_region_error(error, bucket) from error
        raise
    return head.get("Metadata", {}).get("sha256")


def upload_files(config: Config, client) -> dict[str, str]:
    """Upload each planned object with sha256 metadata; skip those already matching.

    Returns:
        Map of key to "uploaded" or "skipped".
    """
    contract = json.loads(CONTRACT.read_text())
    results = {}
    for path, key in upload_plan(config, contract):
        if not path.is_file():
            raise ValueError(
                f"Upload rule: {path} is missing; run the earlier steps first."
            )
        digest = file_sha256(path)
        if stored_sha256(client, config.bucket, key) == digest:
            results[key] = "skipped"
        else:
            client.upload_file(
                str(path),
                config.bucket,
                key,
                ExtraArgs={"Metadata": {"sha256": digest}},
            )
            results[key] = "uploaded"
        print(f"  {results[key]}: s3://{config.bucket}/{key}", flush=True)
    return results


def print_upload_plan(config: Config) -> None:
    """Dry-run output: the exact destination keys."""
    bucket = config.bucket or "<bucket>"
    for _, key in upload_plan(config, json.loads(CONTRACT.read_text())):
        print(f"  s3://{bucket}/{key}")


def summarize(config: Config, state: dict) -> None:
    """Check the layout and print what to commit, where the assets are, and what to run next."""
    contract = json.loads(CONTRACT.read_text())
    problems = layout_problems(config, contract)
    if problems:
        raise ValueError("Bundle layout rule:\n  " + "\n  ".join(problems))
    print("\nTimings (seconds per step):")
    for step, entry in state["steps"].items():
        print(f"  {step:<14}{entry['seconds']:>10}")
    print(f"\nAssets directory: {config.assets_dir}")
    print(
        f"  {config.bundle_dir.relative_to(config.assets_dir)}/ "
        f"{len(contract['parts'])} parts, {contract['bytes']} bytes, sha256 {contract['sha256']}"
    )
    print("\nCommit these two contract files:")
    for path in (CONTRACT, VOCABULARY_CONTRACT):
        print(f"  {path.relative_to(ROOT)}")
    bucket = config.bucket or "<bucket>"
    print("\nOn your laptop, in your fork, in this order:")
    print(f"  {DEPLOY} contracts pull --bucket {bucket} --region {config.region}")
    print(
        "  git add db/config/real-catalog-cache.json db/config/corpus-vocabulary-cache.json"
        ' && git commit -m "Pin my catalog bundle" && git push'
    )
    print(f"  {DEPLOY} publish")
    print(f"  {DEPLOY} deploy")


def move_stale_selection(config: Config) -> None:
    """Set aside a catalog file left by an interrupted prepare, which would block a redo."""
    stale = config.selection_dir / "catalog.jsonl.gz"
    if stale.exists() and not (config.selection_dir / "selection.json").exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = stale.with_name(f"catalog.jsonl.gz.stale-{stamp}")
        stale.rename(target)
        print(
            f"  note: moved the unfinished selection to {target}; it is about 2.5 GB "
            "when complete, so trash it when you are done.",
            flush=True,
        )


def committed_contract() -> dict:
    """The contract as committed at HEAD; export overwrites the working copy."""
    try:
        text = subprocess.run(
            ["git", "show", f"HEAD:{CONTRACT_RELATIVE}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        detail = (getattr(error, "stderr", None) or str(error)).strip()
        raise ValueError(
            f"Committed contract rule: git show HEAD:{CONTRACT_RELATIVE} failed "
            f"({detail}); run from a clone that has that commit."
        ) from error
    return json.loads(text)


def verify_selection_identity(config: Config) -> None:
    """Refuse to spend on embeddings when the selection is not the pinned catalog."""
    manifest = json.loads((config.selection_dir / "selection.json").read_text())
    committed = committed_contract()
    found = (manifest["catalog_sha256"], manifest["products"])
    expected = (committed["catalog_sha256"], committed["products"])
    if found != expected:
        raise ValueError(
            f"Selection identity rule: built catalog_sha256 {found[0]} with {found[1]} "
            f"products, committed contract has {expected[0]} with {expected[1]}. "
            "Investigate the zlib build first: catalog.jsonl.gz is gzip level 1 and its "
            "hash depends on the zlib implementation. Then check the plan and source "
            "revision. A mismatch is expected only if you passed --plan or "
            "--dataset-id for a different catalog; this builder reproduces the "
            "committed one, so rerun without them. Nothing was embedded."
        )
    print(f"  ok   selection matches the committed contract ({found[1]} products)")


def evidence_drift(
    built_reviews: dict[str, int], built_questions: int, committed: dict
) -> list[str]:
    """One line per review file or question count that differs from the committed contract."""
    lines = []
    shipped = committed["review_samples"]
    for name in sorted(set(built_reviews) | set(shipped)):
        built, was = built_reviews.get(name), shipped.get(name)
        if built != was:
            lines.append(f"review_samples {name}: built {built}, committed {was}")
    if built_questions != committed["question_samples"]:
        lines.append(
            f"question_samples: built {built_questions}, "
            f"committed {committed['question_samples']}"
        )
    return lines


def report_evidence_drift(config: Config) -> None:
    """Print a loud WARN for differences from the committed contract; never fail."""
    try:
        built = {
            path.name: len(json.loads(path.read_text())["reviews"])
            for path in config.review_files()
        }
        questions = len(json.loads(config.questions.read_text())["questions"])
        lines = evidence_drift(built, questions, committed_contract())
    except (OSError, KeyError, ValueError) as error:
        print(f"  WARN could not compare evidence counts with the contract: {error}")
        return
    if not lines:
        print("  evidence counts equal the committed contract")
        return
    print("  WARN " + "=" * 60)
    print("  WARN evidence differs from the committed contract (expected: the seed is")
    print("  WARN an approximation). The new contract will pin these counts:")
    for line in lines:
        print(f"  WARN {line}")
    print("  WARN " + "=" * 60, flush=True)


BEFORE_STEP: dict[str, Callable[[Config], None]] = {
    "prepare": move_stale_selection,
    "embed": verify_selection_identity,
}
AFTER_STEP: dict[str, Callable[[Config, dict], None]] = {
    "prepare": lambda config, state: verify_selection_identity(config),
    "evidence": lambda config, state: report_evidence_drift(config),
    "upload": lambda config, state: upload_files(config, make_s3_client(config.region)),
    "summary": summarize,
}


def print_dry_run(config: Config, step: str, commands: list[Command]) -> None:
    for command in commands:
        print(f"  $ {command.render()}")
    if step == "upload":
        print_upload_plan(config)
    if step == "summary":
        print("  (checks the assets layout and prints the laptop commands)")


def run(config: Config, steps: list[str], state: dict, dry_run: bool) -> None:
    """Run or print each selected step in order, timing and recording real runs."""
    for step in steps:
        commands = PLANNERS[step](config)
        print(f"\n== {step} ==", flush=True)
        if dry_run:
            print_dry_run(config, step, commands)
            continue
        invalidate_later_steps(config, state, step)
        started = time.monotonic()
        if step in BEFORE_STEP:
            BEFORE_STEP[step](config)
        for command in commands:
            print(f"  $ {command.render()}", flush=True)
            execute(command)
        if step in AFTER_STEP:
            AFTER_STEP[step](config, state)
        record_step(config, state, step, time.monotonic() - started)
        print(f"  {step}: {time.monotonic() - started:.1f}s", flush=True)


def default_dataset_id() -> str:
    """The id in the committed contract: missions, evals and the stack key on it."""
    return json.loads(CONTRACT.read_text())["dataset_id"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--assets-dir", type=Path, default=os.environ.get("ASSETS_DIR"))
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument(
        "--dataset-id", help="default: the id in db/config/real-catalog-cache.json"
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--from", dest="first", choices=STEPS)
    parser.add_argument("--only", choices=STEPS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--regions", nargs="+", default=[])
    parser.add_argument("--adaptive-pacing", action="store_true")
    parser.add_argument("--tokens-per-minute", type=int)
    parser.add_argument("--reviews-per-rating-group", type=int, default=5)
    parser.add_argument("--review-parts", type=int, default=6)
    parser.add_argument("--bucket", default=os.environ.get(BUCKET_ENV))
    parser.add_argument("--prefix", default="")
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1",
    )
    args = parser.parse_args(argv)
    if args.first and args.only:
        parser.error("use --from or --only, not both")
    if args.assets_dir is None:
        parser.error("--assets-dir (or ASSETS_DIR) is required")
    return args


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit status."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in HELPERS:
        return run_helper(argv)
    args = parse_args(argv)
    config = Config(
        work_dir=args.work_dir.resolve(),
        assets_dir=Path(args.assets_dir).resolve(),
        dataset_id=args.dataset_id or default_dataset_id(),
        plan_path=args.plan.resolve(),
        workers=args.workers,
        regions=tuple(args.regions),
        adaptive_pacing=args.adaptive_pacing,
        tokens_per_minute=args.tokens_per_minute,
        reviews_per_group=args.reviews_per_rating_group,
        review_parts=args.review_parts,
        bucket=args.bucket,
        prefix=args.prefix,
        region=args.region,
    )
    state = load_state(config)
    steps = select_steps(args.first, args.only, state)
    if not args.dry_run:
        preflight(steps, config)
    if config.dataset_id != default_dataset_id():
        print(
            f"Note: dataset id {config.dataset_id!r} differs from the contract's; the "
            "missions manifest and stack pin the contract's id.",
            file=sys.stderr,
        )
    run(config, steps, state, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
