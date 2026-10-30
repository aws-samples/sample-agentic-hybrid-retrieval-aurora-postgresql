"""The bundle builder plans the documented sequence and keeps its own bookkeeping."""

import gzip
import json
import subprocess
from pathlib import Path

import pytest

from scripts.catalog import build_bundle
from scripts.catalog.build_bundle import (
    ARCHIVE_NAME,
    STEPS,
    Config,
    layout_problems,
    load_state,
    main,
    part_names,
    record_step,
    select_steps,
    vocabulary_names,
)


@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a dry run must not start a process")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def dry_run(tmp_path, capsys, *extra):
    argv = [
        "--assets-dir",
        str(tmp_path / "assets"),
        "--work-dir",
        str(tmp_path / "work"),
    ]
    assert main([*argv, "--dry-run", *extra]) == 0
    return capsys.readouterr().out


def commands(output):
    return [line.strip()[2:] for line in output.splitlines() if line.startswith("  $ ")]


def index_of(lines, needle):
    return next(i for i, line in enumerate(lines) if needle in line)


def test_full_plan_runs_steps_in_documented_order(tmp_path, capsys):
    output = dry_run(tmp_path, capsys)
    headers = [line[3:-3] for line in output.splitlines() if line.startswith("== ")]
    assert headers == list(STEPS)
    lines = commands(output)
    for category in ("Electronics", "Office_Products", "Home_and_Kitchen"):
        assert any(f"fetch_catalog_metadata.py {category} " in line for line in lines)
    assert sum("build_bundle.py download" in line for line in lines) == 5
    assert "--plan" in lines[index_of(lines, "prepare_real_catalog.py")]
    assert (
        "real-catalog-plan-v2.json" in lines[index_of(lines, "prepare_real_catalog.py")]
    )
    order = [
        "embed_real_catalog.py",
        "make db-bootstrap-schema",
        "--phase records",
        "--phase embeddings",
        "--phase verify --require-complete",
        "derive-parents",
        "scan_catalog_reviews.py Electronics",
        "filter_catalog_reviews.py",
        "fetch_product_questions.py stage",
        "real_catalog_cache.py export",
        "real_catalog_cache.py split",
        "copy-parts",
        "real_catalog_cache.py join",
        "real_catalog_cache.py restore",
        "make db-verify-bootstrap",
        "corpus_vocabulary.py export",
        "corpus_vocabulary.py verify",
    ]
    positions = [index_of(lines, needle) for needle in order]
    assert positions == sorted(positions)
    # The schema installs twice: into the empty staging database, then again as the
    # event bootstrap replay between join and restore.
    schema_runs = [
        i for i, line in enumerate(lines) if line == "make db-bootstrap-schema"
    ]
    assert len(schema_runs) == 2
    assert (
        index_of(lines, "real_catalog_cache.py join")
        < schema_runs[1]
        < index_of(lines, "real_catalog_cache.py restore")
    )


def test_single_region_embedding_is_the_default(tmp_path, capsys):
    embed = commands(dry_run(tmp_path, capsys, "--only", "embed"))[0]
    assert "--regions" not in embed and "--adaptive-pacing" not in embed
    assert "--workers 4" in embed


def test_regions_select_the_documented_adaptive_configuration(tmp_path, capsys):
    regions = ["us-east-1", "us-east-2", "us-west-2"]
    embed = commands(
        dry_run(tmp_path, capsys, "--only", "embed", "--regions", *regions)
    )[0]
    assert "--regions us-east-1 us-east-2 us-west-2" in embed
    assert "--adaptive-pacing" in embed and "--workers 12" in embed


def test_embedding_options_pass_through(tmp_path, capsys):
    out = dry_run(
        tmp_path,
        capsys,
        "--only",
        "embed",
        "--workers",
        "6",
        "--tokens-per-minute",
        "200000",
    )
    embed = commands(out)[0]
    assert "--workers 6" in embed and "--tokens-per-minute 200000" in embed


def test_from_runs_that_step_onward(tmp_path, capsys):
    output = dry_run(tmp_path, capsys, "--from", "restore-check")
    headers = [line[3:-3] for line in output.splitlines() if line.startswith("== ")]
    assert headers == ["restore-check", "vocabulary", "upload", "summary"]


def test_only_runs_one_step(tmp_path, capsys):
    output = dry_run(tmp_path, capsys, "--only", "export")
    headers = [line[3:-3] for line in output.splitlines() if line.startswith("== ")]
    assert headers == ["export"]
    assert len(commands(output)) == 2


def test_from_and_only_together_are_rejected(tmp_path):
    with pytest.raises(SystemExit):
        main(["--assets-dir", str(tmp_path), "--from", "embed", "--only", "stage"])


def test_restore_check_copies_parts_before_join_deletes_them(tmp_path, capsys):
    lines = commands(dry_run(tmp_path, capsys, "--only", "restore-check"))
    assert index_of(lines, "copy-parts") < index_of(lines, "real_catalog_cache.py join")
    join = lines[index_of(lines, "real_catalog_cache.py join")]
    assert str(tmp_path / "assets") not in join
    verify = lines[index_of(lines, "make db-verify-bootstrap")]
    assert verify.startswith("MOSAIC_CATALOG_DATASET=")


def test_default_dataset_id_is_the_contracts(tmp_path, capsys):
    contract = json.loads(build_bundle.CONTRACT.read_text())
    lines = commands(dry_run(tmp_path, capsys, "--only", "stage"))
    assert all(f"--dataset-id {contract['dataset_id']}" in line for line in lines)


def test_real_run_without_database_url_fails_before_work(tmp_path):
    argv = [
        "--assets-dir",
        str(tmp_path),
        "--work-dir",
        str(tmp_path / "w"),
        "--only",
        "stage",
    ]
    with pytest.raises(ValueError, match="DATABASE_URL rule"):
        main(argv)
    assert not (tmp_path / "w").exists()


def make_config(tmp_path):
    return Config(
        work_dir=tmp_path / "work",
        assets_dir=tmp_path / "assets",
        dataset_id="reviews-2023-v2",
        plan_path=build_bundle.DEFAULT_PLAN,
    )


def test_default_selection_skips_finished_steps(tmp_path):
    config = make_config(tmp_path)
    state = load_state(config)
    record_step(config, state, "fetch", 12.34)
    record_step(config, state, "prepare", 5.0)
    state = load_state(config)
    assert select_steps(None, None, state) == list(STEPS[2:])
    assert select_steps("fetch", None, state) == list(STEPS)
    assert select_steps(None, "fetch", state) == ["fetch"]


def test_record_step_writes_state_and_timings(tmp_path):
    config = make_config(tmp_path)
    state = load_state(config)
    record_step(config, state, "embed", 3600.04)
    record_step(config, state, "summary", 0.2)
    assert (
        json.loads((config.work_dir / "state.json").read_text())["steps"]["embed"][
            "seconds"
        ]
        == 3600.0
    )
    rows = (config.work_dir / "timings.tsv").read_text().splitlines()
    assert [row.split("\t")[0] for row in rows] == ["embed", "summary"]
    assert "summary" not in load_state(config)["steps"]


def test_state_for_another_dataset_is_refused(tmp_path):
    config = make_config(tmp_path)
    record_step(config, load_state(config), "fetch", 1)
    other = Config(**{**config.__dict__, "dataset_id": "reviews-2023-own"})
    with pytest.raises(ValueError, match="Dataset rule"):
        load_state(other)


def test_unknown_step_is_rejected():
    with pytest.raises(ValueError, match="Step rule"):
        select_steps("nope", None, {"steps": {}})


def test_part_and_vocabulary_names():
    assert part_names(3) == [
        "real-catalog.tar.gz.part-000",
        "real-catalog.tar.gz.part-001",
        "real-catalog.tar.gz.part-002",
    ]
    assert vocabulary_names() == [
        "mosaic_search.corpus_lexeme.csv.gz",
        "mosaic_search.corpus_surface_lexeme.csv.gz",
    ]


def lay_out(config, sizes):
    config.vocabulary_dir.mkdir(parents=True)
    parts = []
    for name, size in zip(part_names(len(sizes)), sizes, strict=True):
        (config.bundle_dir / name).write_bytes(b"x" * size)
        parts.append({"name": name, "bytes": size, "sha256": "0" * 64})
    for name in vocabulary_names():
        (config.vocabulary_dir / name).write_bytes(b"v")
    return {"parts": parts}


def test_complete_layout_has_no_problems(tmp_path):
    config = make_config(tmp_path)
    assert layout_problems(config, lay_out(config, [5, 5, 2])) == []


def test_layout_reports_missing_stale_and_wrong_sized_files(tmp_path):
    config = make_config(tmp_path)
    contract = lay_out(config, [5, 5, 2])
    (config.bundle_dir / part_names(3)[1]).unlink()
    (config.bundle_dir / part_names(3)[2]).write_bytes(b"too long")
    (config.bundle_dir / f"{ARCHIVE_NAME}.part-003").write_bytes(b"old")
    (config.vocabulary_dir / vocabulary_names()[0]).unlink()
    text = "\n".join(layout_problems(config, contract))
    assert "missing" in text and "part-001" in text
    assert "part-002 is 8 bytes" in text
    assert "stale file real-catalog.tar.gz.part-003" in text
    assert "corpus_lexeme" in text


def test_layout_rejects_a_part_over_the_studio_limit(tmp_path):
    config = make_config(tmp_path)
    contract = lay_out(config, [4])
    contract["parts"][0]["bytes"] = build_bundle.PART_BYTES + 1
    assert any("part-000" in line for line in layout_problems(config, contract))


def test_review_seed_keeps_only_catalog_products_in_plan_leaves(tmp_path):
    rows = [
        ("A", "Electronics", ["Electronics", "Monitors"]),
        ("B", "Electronics", ["Electronics", "Cables"]),
        ("C", "Home_and_Kitchen", ["Home", "Gaming Chairs"]),
        ("D", "Home_and_Kitchen", ["Home", "Monitors"]),
        ("E", "Office_Products", []),
    ]
    with gzip.open(tmp_path / "catalog.jsonl.gz", "wt") as stream:
        for asin, department, categories in rows:
            record = {"source_department": department, "parent_asin": asin}
            stream.write(
                json.dumps({**record, "original": {"categories": categories}}) + "\n"
            )
    plan = {
        "sources": [
            {"category": "Electronics", "leaves": ["Monitors"]},
            {"category": "Home_and_Kitchen", "leaves": ["Gaming Chairs"]},
            {"category": "Office_Products", "leaves": ["Task Chairs"]},
        ]
    }
    assert build_bundle.derive_review_parents(tmp_path, plan) == {
        "Electronics": ["A"],
        "Home_and_Kitchen": ["C"],
        "Office_Products": [],
    }


def test_copy_parts_leaves_the_originals(tmp_path):
    config = make_config(tmp_path)
    contract = lay_out(config, [3, 2])
    copied = build_bundle.copy_parts(contract, config.bundle_dir, config.restore_dir)
    assert copied == 2
    assert (config.bundle_dir / part_names(2)[0]).read_bytes() == b"xxx"
    assert (config.restore_dir / part_names(2)[1]).read_bytes() == b"xx"


class FakeS3:
    """Stands in for the boto3 client at the boundary."""

    def __init__(self, stored=None):
        self.stored = stored or {}
        self.uploads = []

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.stored:
            raise ClientError({"Error": {"Code": "404", "Message": "no"}}, "HeadObject")
        return {"Metadata": {"sha256": self.stored[Key]}}

    def upload_file(self, path, bucket, key, ExtraArgs):
        self.uploads.append((path, bucket, key, ExtraArgs["Metadata"]["sha256"]))


def upload_config(tmp_path, prefix=""):
    config = make_config(tmp_path)
    return Config(**{**config.__dict__, "bucket": "my-bucket", "prefix": prefix})


def test_upload_plan_keys(tmp_path):
    config = upload_config(tmp_path, "mosaic")
    contract = {"parts": [{}, {}, {}]}
    keys = [key for _, key in build_bundle.upload_plan(config, contract)]
    assert keys == [
        "mosaic/real-catalog/real-catalog.tar.gz.part-000",
        "mosaic/real-catalog/real-catalog.tar.gz.part-001",
        "mosaic/real-catalog/real-catalog.tar.gz.part-002",
        "mosaic/real-catalog/vocabulary/mosaic_search.corpus_lexeme.csv.gz",
        "mosaic/real-catalog/vocabulary/mosaic_search.corpus_surface_lexeme.csv.gz",
        "mosaic/contracts/real-catalog-cache.json",
        "mosaic/contracts/corpus-vocabulary-cache.json",
    ]


def test_empty_prefix_adds_no_leading_slash(tmp_path):
    keys = [
        k for _, k in build_bundle.upload_plan(upload_config(tmp_path), {"parts": [{}]})
    ]
    assert keys[0] == "real-catalog/real-catalog.tar.gz.part-000"
    assert keys[-1] == "contracts/corpus-vocabulary-cache.json"


def test_dry_run_prints_exact_keys(tmp_path, capsys):
    out = dry_run(
        tmp_path, capsys, "--only", "upload", "--bucket", "b1", "--prefix", "p/"
    )
    assert "s3://b1/p/real-catalog/real-catalog.tar.gz.part-000" in out
    assert "s3://b1/p/contracts/real-catalog-cache.json" in out


def test_upload_without_bucket_fails_before_work(tmp_path, monkeypatch):
    monkeypatch.delenv(build_bundle.BUCKET_ENV, raising=False)
    argv = [
        "--assets-dir",
        str(tmp_path),
        "--work-dir",
        str(tmp_path / "w"),
        "--only",
        "upload",
    ]
    with pytest.raises(ValueError, match="Bucket rule"):
        main(argv)


def test_bucket_comes_from_environment(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(build_bundle.BUCKET_ENV, "env-bucket")
    assert "s3://env-bucket/" in dry_run(tmp_path, capsys, "--only", "upload")


def fake_layout(tmp_path, monkeypatch):
    config = upload_config(tmp_path)
    contract = json.loads(build_bundle.CONTRACT.read_text())
    lay_out(config, [3] * len(contract["parts"]))
    return config


def test_upload_sends_every_object_with_sha256_metadata(tmp_path, monkeypatch):
    config = fake_layout(tmp_path, monkeypatch)
    client = FakeS3()
    results = build_bundle.upload_files(config, client)
    assert set(results.values()) == {"uploaded"}
    assert len(client.uploads) == len(results) == 7
    first = client.uploads[0]
    assert first[1] == "my-bucket" and first[3] == build_bundle.file_sha256(
        Path(first[0])
    )


def test_upload_skips_objects_whose_stored_sha256_matches(tmp_path, monkeypatch):
    config = fake_layout(tmp_path, monkeypatch)
    contract = json.loads(build_bundle.CONTRACT.read_text())
    path, key = build_bundle.upload_plan(config, contract)[0]
    client = FakeS3({key: build_bundle.file_sha256(path)})
    results = build_bundle.upload_files(config, client)
    assert results[key] == "skipped"
    assert key not in [upload[2] for upload in client.uploads]
    assert len(client.uploads) == 6


def test_upload_replaces_an_object_with_different_metadata(tmp_path, monkeypatch):
    config = fake_layout(tmp_path, monkeypatch)
    contract = json.loads(build_bundle.CONTRACT.read_text())
    _, key = build_bundle.upload_plan(config, contract)[0]
    client = FakeS3({key: "0" * 64})
    assert build_bundle.upload_files(config, client)[key] == "uploaded"


def test_upload_refuses_a_missing_file(tmp_path):
    with pytest.raises(ValueError, match="Upload rule"):
        build_bundle.upload_files(upload_config(tmp_path), FakeS3())


def test_summary_prints_laptop_commands_in_order(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(build_bundle, "layout_problems", lambda config, contract: [])
    config = Config(**{**upload_config(tmp_path).__dict__, "region": "us-west-2"})
    build_bundle.summarize(config, {"steps": {}})
    out = capsys.readouterr().out
    pull = "deploy.py contracts pull --bucket my-bucket --region us-west-2"
    commit = 'git commit -m "Pin my catalog bundle" && git push'
    order = [pull, commit, "deploy.py publish", "deploy.py deploy"]
    positions = [out.index(item) for item in order]
    assert positions == sorted(positions)


# --- review items -----------------------------------------------------------------


def write_catalog(directory, rows):
    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / "catalog.jsonl.gz", "wt") as stream:
        for asin, department, categories in rows:
            record = {"source_department": department, "parent_asin": asin}
            stream.write(
                json.dumps({**record, "original": {"categories": categories}}) + "\n"
            )


def test_review_seed_adds_lab_parents_that_are_catalog_products(tmp_path):
    write_catalog(
        tmp_path,
        [
            ("A", "Electronics", ["Monitors"]),
            ("LAB", "Electronics", ["Headsets & Microphones"]),
            ("OTHERDEPT", "Home_and_Kitchen", ["Gaming Chairs"]),
        ],
    )
    plan = {
        "sources": [
            {"category": "Electronics", "leaves": ["Monitors"]},
            {"category": "Home_and_Kitchen", "leaves": []},
        ]
    }
    lab = {
        "description": "text, not a list",
        "Electronics": ["LAB", "NOT-IN-CATALOG", "OTHERDEPT"],
    }
    seed = build_bundle.derive_review_parents(tmp_path, plan, lab)
    assert seed == {"Electronics": ["A", "LAB"], "Home_and_Kitchen": []}


def test_evidence_step_passes_the_lab_parents_file(tmp_path, capsys):
    out = dry_run(tmp_path, capsys, "--only", "evidence")
    assert f"--lab-parents {build_bundle.LAB_PARENTS}" in out


def test_evidence_drift_names_every_difference():
    committed = {"review_samples": {"E.json": 10, "H.json": 5}, "question_samples": 7}
    lines = build_bundle.evidence_drift({"E.json": 9, "H.json": 5}, 8, committed)
    assert lines == [
        "review_samples E.json: built 9, committed 10",
        "question_samples: built 8, committed 7",
    ]
    assert build_bundle.evidence_drift({"E.json": 10, "H.json": 5}, 7, committed) == []


def test_drift_is_a_loud_warning_not_a_failure(tmp_path, capsys, monkeypatch):
    config = make_config(tmp_path)
    config.review_dir.mkdir(parents=True)
    for path in config.review_files():
        path.write_text(json.dumps({"reviews": [1, 2]}))
    config.questions.write_text(json.dumps({"questions": [1]}))
    monkeypatch.setattr(
        build_bundle,
        "committed_contract",
        lambda: {
            "review_samples": {"Electronics-reviews.json": 3},
            "question_samples": 1,
        },
    )
    build_bundle.report_evidence_drift(config)
    out = capsys.readouterr().out
    assert "WARN" in out and "Electronics-reviews.json: built 2, committed 3" in out


def selection(tmp_path, sha="aa", products=5):
    config = make_config(tmp_path)
    config.selection_dir.mkdir(parents=True)
    manifest = {"catalog_sha256": sha, "products": products}
    (config.selection_dir / "selection.json").write_text(json.dumps(manifest))
    return config


def test_matching_selection_identity_passes(tmp_path, monkeypatch):
    config = selection(tmp_path)
    monkeypatch.setattr(
        build_bundle,
        "committed_contract",
        lambda: {"catalog_sha256": "aa", "products": 5},
    )
    build_bundle.verify_selection_identity(config)


def test_selection_identity_mismatch_names_zlib_first(tmp_path, monkeypatch):
    config = selection(tmp_path, sha="bb")
    monkeypatch.setattr(
        build_bundle,
        "committed_contract",
        lambda: {"catalog_sha256": "aa", "products": 5},
    )
    with pytest.raises(ValueError, match="zlib") as raised:
        build_bundle.verify_selection_identity(config)
    assert "bb" in str(raised.value) and "aa" in str(raised.value)


def test_identity_check_runs_after_prepare_and_before_embed():
    assert "prepare" in build_bundle.AFTER_STEP and "embed" in build_bundle.BEFORE_STEP


def test_committed_contract_reads_head_not_the_working_copy(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout='{"products": 1}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert build_bundle.committed_contract() == {"products": 1}
    assert seen["argv"] == ["git", "show", "HEAD:db/config/real-catalog-cache.json"]


def client_error(code, headers=None):
    from botocore.exceptions import ClientError

    response = {"Error": {"Code": code, "Message": "x"}}
    response["ResponseMetadata"] = {"HTTPHeaders": headers or {}}
    return ClientError(response, "HeadObject")


class DeniedS3(FakeS3):
    def head_object(self, Bucket, Key):
        raise client_error("403")


def test_403_on_head_means_absent_and_upload_proceeds(tmp_path, monkeypatch):
    config = fake_layout(tmp_path, monkeypatch)
    client = DeniedS3()
    assert set(build_bundle.upload_files(config, client).values()) == {"uploaded"}
    assert len(client.uploads) == 7


def test_head_redirect_names_the_buckets_region():
    class Redirected(FakeS3):
        def head_object(self, Bucket, Key):
            raise client_error("301", {"x-amz-bucket-region": "eu-west-1"})

    with pytest.raises(ValueError, match="eu-west-1"):
        build_bundle.stored_sha256(Redirected(), "b", "k")


def test_other_head_errors_still_raise():
    from botocore.exceptions import ClientError

    class Broken(FakeS3):
        def head_object(self, Bucket, Key):
            raise client_error("500")

    with pytest.raises(ClientError):
        build_bundle.stored_sha256(Broken(), "b", "k")


def checks_for(tmp_path, *steps):
    config = upload_config(tmp_path)
    return [
        label for label, _, _ in build_bundle.environment_checks(list(steps), config)
    ]


def test_preflight_checks_follow_the_selected_steps(tmp_path):
    assert checks_for(tmp_path, "fetch", "prepare") == []
    assert checks_for(tmp_path, "embed") == ["AWS credentials"]
    assert checks_for(tmp_path, "upload") == ["AWS credentials", "bucket my-bucket"]
    assert checks_for(tmp_path, "stage") == ["database"]
    assert checks_for(tmp_path, "schema") == ["database", "make check-python"]
    assert checks_for(tmp_path, "restore-check") == ["database", "make check-python"]


def test_schema_installs_into_the_empty_staging_database_before_stage(tmp_path, capsys):
    output = dry_run(tmp_path, capsys)
    headers = [line[3:-3] for line in output.splitlines() if line.startswith("== ")]
    assert headers.index("schema") == headers.index("stage") - 1
    lines = commands(output)
    assert index_of(lines, "make db-bootstrap-schema") < index_of(
        lines, "--phase records"
    )
    assert "schema" in build_bundle.DATABASE_STEPS


def test_database_probe_failure_stops_the_run_before_any_step(
    tmp_path, capsys, monkeypatch
):
    def refuse(url):
        raise RuntimeError("OperationalError: connection timeout expired")

    monkeypatch.setenv("DATABASE_URL", "postgresql://example/mosaic")
    monkeypatch.setattr(build_bundle, "database_reachable", refuse)
    with pytest.raises(ValueError, match="Preflight rule"):
        build_bundle.run_environment_checks(["stage"], upload_config(tmp_path))
    out = capsys.readouterr().out
    assert "FAIL database: OperationalError" in out and "staging Aurora" in out


class FakeConnection:
    def __init__(self, version, extensions):
        self.version = version
        self.extensions = extensions

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        if statement.startswith("SHOW"):
            return FakeCursor([(self.version,)])
        wanted = params[0]
        return FakeCursor([(name,) for name in self.extensions if name in wanted])


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


def test_database_probe_names_a_missing_extension(monkeypatch):
    import psycopg

    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda url, **kw: FakeConnection("16.6", ["pg_trgm", "unaccent"]),
    )
    with pytest.raises(RuntimeError, match="cannot install vector, pgcrypto"):
        build_bundle.database_reachable("postgresql://example/mosaic")
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda url, **kw: FakeConnection(
            "16.6", list(build_bundle.REQUIRED_EXTENSIONS)
        ),
    )
    assert build_bundle.database_reachable("postgresql://example/mosaic") == (
        "PostgreSQL 16.6, 4 extensions available"
    )


def test_database_probe_reports_a_connection_error_as_a_check_failure(monkeypatch):
    import psycopg

    def fail(url, **kw):
        raise psycopg.OperationalError("connection timeout expired")

    monkeypatch.setattr(psycopg, "connect", fail)
    with pytest.raises(
        RuntimeError, match="OperationalError: connection timeout expired"
    ):
        build_bundle.database_reachable("postgresql://example/mosaic")


def test_preflight_prints_ok_and_fail_lines_and_raises(tmp_path, capsys, monkeypatch):
    class Sts:
        def get_caller_identity(self):
            raise client_error("ExpiredToken")

    class Bucket:
        def head_bucket(self, Bucket):
            return {}

    monkeypatch.setattr(build_bundle, "make_sts_client", lambda region: Sts())
    monkeypatch.setattr(build_bundle, "make_s3_client", lambda region: Bucket())
    with pytest.raises(ValueError, match="Preflight rule"):
        build_bundle.run_environment_checks(["upload"], upload_config(tmp_path))
    out = capsys.readouterr().out
    assert "FAIL AWS credentials" in out and "Fix:" in out
    assert "ok   bucket my-bucket: reachable" in out


def test_preflight_bucket_redirect_fails_with_the_region(tmp_path, capsys, monkeypatch):
    class Sts:
        def get_caller_identity(self):
            return {"Arn": "arn:aws:iam::1:role/r"}

    class Bucket:
        def head_bucket(self, Bucket):
            raise client_error("301", {"x-amz-bucket-region": "us-west-2"})

    monkeypatch.setattr(build_bundle, "make_sts_client", lambda region: Sts())
    monkeypatch.setattr(build_bundle, "make_s3_client", lambda region: Bucket())
    with pytest.raises(ValueError):
        build_bundle.run_environment_checks(["upload"], upload_config(tmp_path))
    assert "us-west-2" in capsys.readouterr().out


def test_rerunning_a_step_forgets_every_later_step(tmp_path):
    config = make_config(tmp_path)
    state = load_state(config)
    for step in ("fetch", "prepare", "embed"):
        record_step(config, state, step, 1)
    assert build_bundle.invalidate_later_steps(config, state, "prepare") == ["embed"]
    assert sorted(load_state(config)["steps"]) == ["fetch"]


def test_run_invalidates_later_steps_before_executing(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    state = load_state(config)
    for step in ("fetch", "prepare"):
        record_step(config, state, step, 1)
    monkeypatch.setattr(build_bundle, "execute", lambda command: None)
    build_bundle.run(config, ["fetch"], state, dry_run=False)
    assert sorted(load_state(config)["steps"]) == ["fetch"]


def test_restore_runs_with_the_vocabulary_cache_variable_removed(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    plan = build_bundle.plan_restore_check(config)
    restore = next(c for c in plan if "restore" in c.argv)
    assert restore.unset == ("MOSAIC_VOCABULARY_CACHE_DIR",)
    assert restore.render().startswith("env -u MOSAIC_VOCABULARY_CACHE_DIR ")
    seen = {}

    def fake_run(argv, cwd, env, check):
        seen["env"] = env

    monkeypatch.setenv("MOSAIC_VOCABULARY_CACHE_DIR", "/stale")
    monkeypatch.setattr(subprocess, "run", fake_run)
    build_bundle.execute(restore)
    assert "MOSAIC_VOCABULARY_CACHE_DIR" not in seen["env"]


def test_interrupted_prepare_output_is_moved_aside_with_a_timestamp(tmp_path, capsys):
    config = make_config(tmp_path)
    config.selection_dir.mkdir(parents=True)
    (config.selection_dir / "catalog.jsonl.gz").write_bytes(b"half")
    build_bundle.move_stale_selection(config)
    names = sorted(p.name for p in config.selection_dir.iterdir())
    assert len(names) == 1 and names[0].startswith("catalog.jsonl.gz.stale-")


def test_finished_selection_is_left_alone(tmp_path):
    config = selection(tmp_path)
    (config.selection_dir / "catalog.jsonl.gz").write_bytes(b"whole")
    build_bundle.move_stale_selection(config)
    assert (config.selection_dir / "catalog.jsonl.gz").exists()


class FakeResponse:
    def __init__(self, data, length="same", fail_after=None):
        self.data = data
        self.fail_after = fail_after
        self.headers = (
            {}
            if length is None
            else {"Content-Length": str(len(data) if length == "same" else length)}
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        if self.fail_after is not None:
            raise self.fail_after
        data, self.data = self.data, b""
        return data


def test_download_retries_transient_errors_with_backoff(tmp_path, monkeypatch):
    import urllib.error

    outcomes = [urllib.error.URLError("reset"), TimeoutError(), FakeResponse(b"data")]

    def fake_urlopen(url, timeout):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(build_bundle.urllib.request, "urlopen", fake_urlopen)
    waits = []
    target = tmp_path / "pqa" / "f.json"
    build_bundle.download("https://x/f.json", target, sleep=waits.append)
    assert target.read_bytes() == b"data" and waits == [2, 4]
    assert not target.with_suffix(".json.partial").exists()


def test_download_gives_up_after_three_attempts(tmp_path, monkeypatch):
    import urllib.error

    def fail(url, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(build_bundle.urllib.request, "urlopen", fail)
    with pytest.raises(ValueError, match="failed 3 times"):
        build_bundle.download("https://x/f", tmp_path / "f", sleep=lambda s: None)
    assert not (tmp_path / "f").exists()


def test_download_does_not_retry_a_missing_file(tmp_path, monkeypatch):
    import urllib.error

    calls = []

    def missing(url, timeout):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "nope", None, None)

    monkeypatch.setattr(build_bundle.urllib.request, "urlopen", missing)
    with pytest.raises(urllib.error.HTTPError):
        build_bundle.download("https://x/f", tmp_path / "f", sleep=lambda s: None)
    assert len(calls) == 1


class Parsed(Exception):
    """Raised after the real parser accepted the arguments."""


def composed_commands(tmp_path):
    configs = [
        make_config(tmp_path),
        Config(
            **{
                **make_config(tmp_path).__dict__,
                "regions": ("us-east-1", "us-east-2"),
                "tokens_per_minute": 1000,
                "workers": 8,
            }
        ),
    ]
    for config in configs:
        for step in STEPS:
            for command in build_bundle.PLANNERS[step](config):
                if command.argv[:3] == ("uv", "run", "python"):
                    yield step, command.argv[3], list(command.argv[4:])


def test_every_composed_argv_parses_with_the_real_script_parser(tmp_path, monkeypatch):
    import argparse
    import importlib
    import sys

    original = argparse.ArgumentParser.parse_args

    def parse_then_stop(self, args=None, namespace=None):
        original(self, args, namespace)
        raise Parsed

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_then_stop)
    seen = set()
    for step, script, argv in composed_commands(tmp_path):
        module = importlib.import_module(script.removesuffix(".py").replace("/", "."))
        monkeypatch.setattr(sys, "argv", [script, *argv])
        with pytest.raises(Parsed):
            module.main()
        seen.add(script.rsplit("/", 1)[1])
    assert {
        "embed_real_catalog.py",
        "scan_catalog_reviews.py",
        "build_bundle.py",
    } <= seen
    assert len(seen) == 10


def test_a_flag_the_real_parser_does_not_know_is_caught(monkeypatch):
    import sys

    from scripts.catalog import stage_real_catalog

    monkeypatch.setattr(sys, "argv", ["stage", "--no-such-flag"])
    with pytest.raises(SystemExit):
        stage_real_catalog.main()


def test_failing_subprocess_names_the_command_and_how_to_resume(monkeypatch):
    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(3, argv)

    monkeypatch.setattr(subprocess, "run", fail)
    command = build_bundle.Command(("make", "db-bootstrap-schema"))
    with pytest.raises(SystemExit) as raised:
        build_bundle.execute(command)
    message = str(raised.value)
    assert "exit 3" in message and "make db-bootstrap-schema" in message
    assert "rerun" in message


def test_failing_step_is_not_recorded_as_done(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    state = load_state(config)

    def fail(command):
        raise SystemExit("boom")

    monkeypatch.setattr(build_bundle, "execute", fail)
    with pytest.raises(SystemExit):
        build_bundle.run(config, ["fetch"], state, dry_run=False)
    assert "fetch" not in load_state(config)["steps"]


@pytest.mark.parametrize("text", ["{not json", "[]", '{"dataset_id": "x"}', ""])
def test_corrupt_state_file_is_reported_with_the_fix(tmp_path, text):
    config = make_config(tmp_path)
    config.work_dir.mkdir(parents=True)
    (config.work_dir / "state.json").write_text(text)
    with pytest.raises(ValueError, match="State rule") as raised:
        load_state(config)
    assert "state.json" in str(raised.value) and "trash" in str(raised.value)


def test_a_step_that_dies_midway_is_not_left_marked_done(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    state = load_state(config)
    for step in ("export", "restore-check"):
        record_step(config, state, step, 1)

    def die_in_split(command):
        raise SystemExit("split died")

    monkeypatch.setattr(build_bundle, "execute", die_in_split)
    with pytest.raises(SystemExit):
        build_bundle.run(config, ["export"], state, dry_run=False)
    assert load_state(config)["steps"] == {}
    assert select_steps(None, None, load_state(config))[0] == "fetch"


def test_invalidating_a_step_with_no_entry_changes_nothing(tmp_path):
    config = make_config(tmp_path)
    state = load_state(config)
    assert build_bundle.invalidate_later_steps(config, state, "export") == []
    assert not (config.work_dir / "state.json").exists()


def test_download_retries_a_failure_while_reading_the_body(tmp_path, monkeypatch):
    import http.client

    outcomes = [
        FakeResponse(b"abc", fail_after=ConnectionResetError("reset")),
        FakeResponse(b"abc", fail_after=http.client.IncompleteRead(b"a", 2)),
        FakeResponse(b"abc"),
    ]
    monkeypatch.setattr(
        build_bundle.urllib.request, "urlopen", lambda url, timeout: outcomes.pop(0)
    )
    waits = []
    build_bundle.download("https://x/f", tmp_path / "f", sleep=waits.append)
    assert (tmp_path / "f").read_bytes() == b"abc" and waits == [2, 4]


def test_a_short_body_is_retried_and_never_kept(tmp_path, monkeypatch):
    short = [FakeResponse(b"abc", length=10) for _ in range(3)]
    monkeypatch.setattr(
        build_bundle.urllib.request, "urlopen", lambda url, timeout: short.pop(0)
    )
    with pytest.raises(ValueError, match="Content-Length"):
        build_bundle.download("https://x/f", tmp_path / "f", sleep=lambda s: None)
    assert not (tmp_path / "f").exists()


def test_a_short_body_then_a_full_one_succeeds(tmp_path, monkeypatch):
    bodies = [FakeResponse(b"ab", length=3), FakeResponse(b"abc")]
    monkeypatch.setattr(
        build_bundle.urllib.request, "urlopen", lambda url, timeout: bodies.pop(0)
    )
    build_bundle.download("https://x/f", tmp_path / "f", sleep=lambda s: None)
    assert (tmp_path / "f").read_bytes() == b"abc"


def test_a_response_without_content_length_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(
        build_bundle.urllib.request,
        "urlopen",
        lambda url, timeout: FakeResponse(b"abc", length=None),
    )
    build_bundle.download("https://x/f", tmp_path / "f", sleep=lambda s: None)
    assert (tmp_path / "f").read_bytes() == b"abc"


def bucket_client(code, headers=None):
    class Bucket:
        def head_bucket(self, Bucket):
            raise client_error(code, headers)

    return Bucket()


def test_head_bucket_403_warns_and_continues(tmp_path, capsys, monkeypatch):
    class Sts:
        def get_caller_identity(self):
            return {"Arn": "arn"}

    monkeypatch.setattr(build_bundle, "make_sts_client", lambda region: Sts())
    monkeypatch.setattr(
        build_bundle, "make_s3_client", lambda region: bucket_client("403")
    )
    build_bundle.run_environment_checks(["upload"], upload_config(tmp_path))
    out = capsys.readouterr().out
    assert "WARN bucket my-bucket" in out and "FAIL" not in out


def test_head_bucket_301_is_still_a_failure(tmp_path, capsys, monkeypatch):
    class Sts:
        def get_caller_identity(self):
            return {"Arn": "arn"}

    client = bucket_client("301", {"x-amz-bucket-region": "eu-west-1"})
    monkeypatch.setattr(build_bundle, "make_sts_client", lambda region: Sts())
    monkeypatch.setattr(build_bundle, "make_s3_client", lambda region: client)
    with pytest.raises(ValueError, match="Preflight rule"):
        build_bundle.run_environment_checks(["upload"], upload_config(tmp_path))
    assert "FAIL bucket my-bucket" in capsys.readouterr().out


@pytest.mark.parametrize("stdout", ["", "\n"])
def test_check_python_with_empty_output_gets_a_generic_message(monkeypatch, stdout):
    result = subprocess.CompletedProcess(["make"], 2, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
    with pytest.raises(RuntimeError, match="exited 2"):
        build_bundle.python_version_ok()


def test_stale_selection_note_says_it_can_be_trashed(tmp_path, capsys):
    config = make_config(tmp_path)
    config.selection_dir.mkdir(parents=True)
    (config.selection_dir / "catalog.jsonl.gz").write_bytes(b"half")
    build_bundle.move_stale_selection(config)
    out = capsys.readouterr().out
    assert "2.5 GB" in out and "trash" in out


def test_committed_contract_error_includes_gits_stderr(monkeypatch):
    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(
            128, argv, stderr="fatal: bad revision 'HEAD'\n"
        )

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match="fatal: bad revision"):
        build_bundle.committed_contract()


def test_identity_failure_names_the_flags_that_make_it_expected(tmp_path, monkeypatch):
    config = selection(tmp_path, sha="bb")
    monkeypatch.setattr(
        build_bundle,
        "committed_contract",
        lambda: {"catalog_sha256": "aa", "products": 5},
    )
    with pytest.raises(ValueError) as raised:
        build_bundle.verify_selection_identity(config)
    assert "--plan" in str(raised.value) and "--dataset-id" in str(raised.value)


def test_missing_evidence_files_warn_instead_of_failing(tmp_path, capsys, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(build_bundle, "committed_contract", dict)
    build_bundle.report_evidence_drift(config)
    assert "WARN could not compare" in capsys.readouterr().out
