"""The retrieval fingerprint must hash exactly the files it claims to.

House standards rule 7's three proofs (red-at-birth, independence, witness),
plus the five behavioral proofs the owner asked for by name. Every test here
builds a throwaway repository tree (`fake_repo`), so nothing touches the real
files -- the same convention `tests/test_config_tripwire.py` already uses for
exactly this reason.

The fake tree mirrors the real manifest's file *paths* with placeholder
content, so the module's hardcoded `_EXPECTED_CATEGORY_COUNTS` (27 SQL files,
1 config, 4 service, 3 scripts, 2 eval-data files) hold without needing a
test-only override parameter on production code.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from service.models import RetrievalProfile
from service.retrieval_fingerprint import (
    _EXPECTED_CATEGORY_COUNTS,
    _FLOAT_SETTINGS,
    ABLATION_METHODOLOGY_FILES,
    RETRIEVAL_SETTINGS_KEY_COUNT,
    SCORECARD_METHODOLOGY_FILES,
    RetrievalFingerprintError,
    category_counts,
    compute_ablation_methodology_sha256,
    compute_live_retrieval_settings_sha256,
    compute_retrieval_fingerprint,
    compute_retrieval_settings_sha256,
    compute_scorecard_methodology_sha256,
    manifest_files,
    retrieval_settings_payload,
)

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO

# The real db/sql/ filenames, so the fake tree's "sql" category naturally
# matches the real category's expected count (27) rather than needing a
# second, test-only literal.
_SQL_FILENAMES = (
    "00_extensions.sql",
    "01_schemas_and_types.sql",
    "02_reference_data.sql",
    "03_catalog.sql",
    "04_media.sql",
    "05_evidence.sql",
    "06_retrieval_projection.sql",
    "07_indexes.sql",
    "08_indexes_concurrent.sql",
    "09_search_functions.sql",
    "10_agent_audit.sql",
    "11_evaluation.sql",
    "12_telemetry.sql",
    "13_benchmark.sql",
    "14_exact_neighbor.sql",
    "15_load_premium_cohort.sql",
    "16_seed_tool_contracts.sql",
    "17_load_normalized_catalog.sql",
    "18_load_evidence.sql",
    "19_indexes_quantized.sql",
    "20_query_coverage.sql",
    "98_bootstrap_acceptance.sql",
    "99_smoke_test.sql",
    "install.sql",
    "install_labs.sql",
    "lab_01_typo_tolerance.sql",
    "upgrade_snapshot.sql",
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _populate(root: Path) -> None:
    """Write exactly the manifest's files, at their real relative paths."""
    for index, name in enumerate(_SQL_FILENAMES):
        _write(root / "db" / "sql" / name, f"-- sql fixture {index}\n")
    _write(root / "db" / "config" / "retrieval.yaml", "fusion:\n  rrf_k: 60\n")
    _write(root / "service" / "retrieval.py", "# retrieval fixture\n")
    _write(root / "service" / "rerank.py", "# rerank fixture\n")
    _write(root / "service" / "embeddings.py", "# embeddings fixture\n")
    _write(root / "service" / "bedrock.py", "# bedrock fixture\n")
    _write(root / "scripts" / "retrieval_profile.py", "# retrieval_profile fixture\n")
    _write(root / "scripts" / "evaluate.py", "# evaluate fixture\n")
    _write(root / "scripts" / "eval_contract.py", "# eval_contract fixture\n")
    _write(
        root / "data" / "evals" / "canonical_queries.jsonl",
        '{"query_id": "G-001", "judgments": [{"product_id": 1, "grade": 0}]}\n',
    )
    _write(
        root / "data" / "evals" / "mosaic_labs_missions.json",
        '{"missions": [], "supporting_checks": []}\n',
    )


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    _populate(tmp_path)
    return tmp_path


# --- House standards rule 7: red-at-birth, independence, witness -----------


def test_an_empty_sql_glob_is_refused_rather_than_silently_hashed(fake_repo):
    """Red-at-birth: db/sql/ losing every file must not produce a fingerprint
    that still looks valid. This is exactly the vacuous-iteration shape house
    standards rule 7 names."""
    for path in (fake_repo / "db" / "sql").glob("*.sql"):
        path.unlink()

    with pytest.raises(RetrievalFingerprintError, match="category 'sql' has 0"):
        compute_retrieval_fingerprint(repo_root=fake_repo)


def test_a_short_sql_glob_is_also_refused(fake_repo):
    """Not just empty -- one file short of the literal must fail too."""
    (fake_repo / "db" / "sql" / "00_extensions.sql").unlink()

    with pytest.raises(RetrievalFingerprintError, match="category 'sql' has 26"):
        compute_retrieval_fingerprint(repo_root=fake_repo)


def test_a_missing_literal_manifest_file_is_refused(fake_repo):
    """The witness applies to the literal-path categories too, not only the
    glob: deleting `service/bedrock.py` leaves the *count* at 4 (the manifest
    still names four service files), so this must be caught by the per-file
    existence check rather than the count check alone."""
    (fake_repo / "service" / "bedrock.py").unlink()

    with pytest.raises(
        RetrievalFingerprintError,
        match="category 'service' does not exist",
    ):
        compute_retrieval_fingerprint(repo_root=fake_repo)


def test_the_complete_tree_matches_every_expected_category_count_exactly(fake_repo):
    """Independence + witness together: a healthy, complete tree hashes
    exactly the expected file count in every category -- never zero, never
    short -- checked against literals written here, not against a count
    derived from the same glob under test."""
    counts = category_counts(repo_root=fake_repo)

    assert counts == _EXPECTED_CATEGORY_COUNTS
    assert counts["sql"] == 27
    assert counts["config"] == 1
    assert counts["service"] == 4
    assert counts["scripts"] == 3
    assert counts["eval_data"] == 2
    assert sum(counts.values()) == 37


def test_manifest_files_visit_a_representative_of_every_category(fake_repo):
    """Witness: the manifest actually hashed at least one file from every
    required category, not merely that the counts looked right."""
    files = manifest_files(repo_root=fake_repo)
    relative = {path.relative_to(fake_repo).as_posix() for path in files}

    assert len(files) == 37
    assert "db/sql/09_search_functions.sql" in relative
    assert "db/config/retrieval.yaml" in relative
    assert "service/retrieval.py" in relative
    assert "scripts/evaluate.py" in relative
    assert "data/evals/canonical_queries.jsonl" in relative
    assert "data/evals/mosaic_labs_missions.json" in relative


def test_manifest_files_are_sorted_by_repo_relative_path(fake_repo):
    files = manifest_files(repo_root=fake_repo)
    relative = [path.relative_to(fake_repo).as_posix() for path in files]

    assert relative == sorted(relative)


def test_fingerprint_is_deterministic_and_path_independent(tmp_path):
    """Same logical content, two different absolute checkout paths, same
    fingerprint -- proves paths are normalized relative to `repo_root`."""
    first_root = tmp_path / "checkout-a"
    second_root = tmp_path / "checkout-b"
    _populate(first_root)
    _populate(second_root)

    first = compute_retrieval_fingerprint(repo_root=first_root)
    second = compute_retrieval_fingerprint(repo_root=second_root)

    assert first == second
    assert first == compute_retrieval_fingerprint(repo_root=first_root)


# --- The five owner-specified behavioral proofs -----------------------------


def test_proof_1_a_non_manifest_file_change_leaves_the_fingerprint_unchanged(
    fake_repo,
):
    """Proof 1: editing `.gitignore` or a README -- anything outside the
    manifest -- must not move the fingerprint."""
    baseline = compute_retrieval_fingerprint(repo_root=fake_repo)

    _write(fake_repo / "README.md", "This paragraph did not exist before.\n")
    _write(fake_repo / ".gitignore", "*.pyc\n__pycache__/\n")

    assert compute_retrieval_fingerprint(repo_root=fake_repo) == baseline


def test_proof_2_editing_retrieval_py_moves_the_fingerprint(fake_repo):
    """Proof 2: `service/retrieval.py` is the served retrieval path."""
    baseline = compute_retrieval_fingerprint(repo_root=fake_repo)

    _write(fake_repo / "service" / "retrieval.py", "# retrieval fixture, edited\n")

    assert compute_retrieval_fingerprint(repo_root=fake_repo) != baseline


def test_proof_3_editing_rerank_py_moves_the_fingerprint(fake_repo):
    """Proof 3: `service/rerank.py` is the served reranking path."""
    baseline = compute_retrieval_fingerprint(repo_root=fake_repo)

    _write(fake_repo / "service" / "rerank.py", "# rerank fixture, edited\n")

    assert compute_retrieval_fingerprint(repo_root=fake_repo) != baseline


def test_proof_4a_editing_canonical_queries_moves_the_fingerprint(fake_repo):
    """Proof 4: the canonical query/judgment data directly."""
    baseline = compute_retrieval_fingerprint(repo_root=fake_repo)

    _write(
        fake_repo / "data" / "evals" / "canonical_queries.jsonl",
        '{"query_id": "G-001", "judgments": [{"product_id": 1, "grade": 3}]}\n',
    )

    assert compute_retrieval_fingerprint(repo_root=fake_repo) != baseline


def test_proof_4b_editing_mission_backed_filters_moves_the_fingerprint(fake_repo):
    """Proof 4, the gap this module was widened to close: mission-backed
    query text and filters live in `mosaic_labs_missions.json`, substituted
    into the scored population by `scripts/eval_contract.py`, not in
    `canonical_queries.jsonl` itself. A fingerprint that only watched the
    latter would miss a filter edit that changes candidate eligibility for
    every mission-backed query."""
    baseline = compute_retrieval_fingerprint(repo_root=fake_repo)

    _write(
        fake_repo / "data" / "evals" / "mosaic_labs_missions.json",
        '{"missions": [{"id": "typo-recovery", "filters": {"max_price_cents": 1}}], '
        '"supporting_checks": []}\n',
    )

    assert compute_retrieval_fingerprint(repo_root=fake_repo) != baseline


def test_proof_5_a_scorecard_artifact_only_change_leaves_the_fingerprint_unchanged(
    fake_repo,
):
    """Proof 5, the one that proves the off-by-one is dead rather than
    relocated: a change scoped only to `canonical_scorecard.json` -- the file
    the old strict-revision gate effectively forced every release to touch --
    must not move the fingerprint. If it did, the artifact would be hashing
    itself, which is the exact failure this module exists to kill."""
    baseline = compute_retrieval_fingerprint(repo_root=fake_repo)

    _write(
        fake_repo / "data" / "evals" / "canonical_scorecard.json",
        '{"metrics": {"recall@10": 0.99}, "source": {"revision": "deadbeef"}}\n',
    )

    assert compute_retrieval_fingerprint(repo_root=fake_repo) == baseline


# --- Regression guard against the real repository ---------------------------


def test_the_real_repository_computes_a_fingerprint_with_every_category_present():
    """Unlike the fake-tree tests above, this runs against the real checkout,
    so it also serves as the live regression guard: if a real manifest file
    is ever deleted or a category collapses, this fails here first."""
    counts = category_counts()

    assert counts == _EXPECTED_CATEGORY_COUNTS
    fingerprint = compute_retrieval_fingerprint()
    assert len(fingerprint) == 64
    assert fingerprint == compute_retrieval_fingerprint()


# --- Methodology hashes: each owned file must move its own hash --------------


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True)


@pytest.fixture()
def methodology_tree(tmp_path):
    """A real repo copy, so the hashes are computed over actual files.

    Only the directories the two manifests name are copied; a manifest that
    started reading somewhere else would fail the existence check rather than
    quietly hash a shorter list.
    """
    root = tmp_path / "repo"
    for relative in ("scripts", "service", "db/sql", "db/config", "data/evals"):
        _copy_tree(ROOT / relative, root / relative)
    return root


@pytest.mark.parametrize(
    ("relpath", "moves_scorecard"),
    [
        ("scripts/score_evals.py", True),
        ("service/models.py", True),
        ("service/retrieval_fingerprint.py", True),
        # Requirement 2: the ablation harness is in the ablation manifest only.
        ("scripts/ablation_evals.py", False),
    ],
)
def test_editing_an_owned_file_moves_the_right_methodology_hash(
    methodology_tree, relpath, moves_scorecard
):
    """Requirement 1 and 2 together, one file at a time.

    Each of the three shared files must move both hashes; the ablation harness
    must move only the ablation hash. Asserted per file rather than in
    aggregate, so a manifest that dropped one entry cannot hide behind the
    others still moving.
    """
    before_scorecard = compute_scorecard_methodology_sha256(methodology_tree)
    before_ablation = compute_ablation_methodology_sha256(methodology_tree)

    target = methodology_tree / relpath
    target.write_bytes(target.read_bytes() + b"\n# methodology edit\n")

    after_scorecard = compute_scorecard_methodology_sha256(methodology_tree)
    after_ablation = compute_ablation_methodology_sha256(methodology_tree)

    assert (after_scorecard != before_scorecard) is moves_scorecard, relpath
    # Every owned file moves the ablation hash, because it is the superset.
    assert after_ablation != before_ablation, relpath


def test_retrieval_fingerprint_ignores_every_methodology_only_file(
    methodology_tree,
):
    """The separation that makes this design affordable.

    Editing any methodology-only file must leave `retrieval_fingerprint`
    untouched, or a console-output tweak would invalidate a billed measurement --
    which is exactly what folding these into one hash would have caused.
    """
    before = compute_retrieval_fingerprint(methodology_tree)

    for relpath in (
        "scripts/score_evals.py",
        "service/models.py",
        "service/retrieval_fingerprint.py",
        "scripts/ablation_evals.py",
    ):
        target = methodology_tree / relpath
        target.write_bytes(target.read_bytes() + b"\n# methodology edit\n")

    assert compute_retrieval_fingerprint(methodology_tree) == before


def test_methodology_manifest_counts_are_asserted_against_literals():
    """Witness, per rule 7: a manifest that lost an entry must fail loudly
    rather than hash a shorter list under a name that still reads complete.
    Checked against hand-counted literals, never `len()` of the tuple itself.
    """
    assert len(SCORECARD_METHODOLOGY_FILES) == 3
    assert len(ABLATION_METHODOLOGY_FILES) == 4
    assert set(SCORECARD_METHODOLOGY_FILES) < set(ABLATION_METHODOLOGY_FILES)


def test_methodology_hash_refuses_a_missing_manifest_entry(tmp_path):
    """Red-at-birth for the existence check: an empty tree must raise, not
    return a valid-looking digest over zero files."""
    with pytest.raises(RetrievalFingerprintError, match="does not exist"):
        compute_scorecard_methodology_sha256(tmp_path)


# --- The live retrieval settings hash ---------------------------------------
#
# The fingerprint above hashes *files*. Environment overrides
# (`RRF_K`, `FTS_CANDIDATE_LIMIT`, `HNSW_EF_SEARCH`, ...) beat the yaml in
# `scripts/retrieval_profile._resolve`, so they change every served result
# without moving one byte of any manifest file. `RRF_K=1` could therefore serve
# an attributed scorecard. These tests pin the second hash that closes that
# hole: one over the resolved `RetrievalProfile` itself.


_RETRIEVAL_SETTINGS_KEYS = {
    "authorized_limit",
    "ef_search",
    "fts_limit",
    "fused_limit",
    "iterative_scan",
    "max_scan_tuples",
    "result_limit",
    "rrf_k",
    "scan_mem_multiplier",
    "semantic_limit",
    "trigram_limit",
    "trigram_threshold",
    "weight_lexical",
    "weight_semantic",
    "weight_trigram",
}

#: Every setting an environment variable can override behind the fingerprint's
#: back, per `scripts/retrieval_profile.BOUNDS`. Each must move the hash on its
#: own; asserted one at a time so a hash that only reacted to `rrf_k` cannot
#: hide behind the others.
_ENV_OVERRIDABLE_SETTINGS = (
    ("rrf_k", 1),
    ("fts_limit", 1),
    ("trigram_limit", 1),
    ("semantic_limit", 1),
    ("fused_limit", 1),
    ("ef_search", 1),
    ("trigram_threshold", 0.99),
)


def _live_profile() -> dict:
    return RetrievalProfile().model_dump()


def test_the_settings_payload_covers_every_retrieval_profile_field():
    """Exhaustiveness, per house standards rule 5a.

    The hash's domain is `RetrievalProfile` itself, so a field added to the
    model must either be hashed or force a deliberate decision here. Checked
    against a hand-written key set *and* against the model, never against
    `len()` of the production tuple, which would agree with any edit.
    """
    payload = retrieval_settings_payload(_live_profile())

    assert set(payload) == set(RetrievalProfile.model_fields)
    assert set(payload) == _RETRIEVAL_SETTINGS_KEYS
    assert len(payload) == RETRIEVAL_SETTINGS_KEY_COUNT
    assert RETRIEVAL_SETTINGS_KEY_COUNT == 15
    # The float set is derived from the model, so it cannot go stale on its
    # own; pinned here against literals so a field changing type is a decision
    # somebody makes rather than a digest that silently re-renders.
    assert _FLOAT_SETTINGS == {
        "scan_mem_multiplier",
        "trigram_threshold",
        "weight_lexical",
        "weight_semantic",
        "weight_trigram",
    }


def test_the_settings_hash_is_stable_for_the_same_resolved_profile():
    """Witness that the positive branch exists: the hash is a hash."""
    profile = _live_profile()

    first = compute_retrieval_settings_sha256(profile)

    assert len(first) == 64
    assert first == compute_retrieval_settings_sha256(_live_profile())


def test_the_settings_hash_ignores_dict_insertion_order():
    """Independence: canonical JSON sorts keys, so a differently-built dict
    carrying identical values must hash identically."""
    profile = _live_profile()
    reversed_order = {key: profile[key] for key in reversed(list(profile))}

    assert compute_retrieval_settings_sha256(reversed_order) == (
        compute_retrieval_settings_sha256(profile)
    )


@pytest.mark.parametrize(("setting", "value"), _ENV_OVERRIDABLE_SETTINGS)
def test_every_environment_overridable_setting_moves_the_hash(setting, value):
    """Red-at-birth for the audit finding itself.

    Each of these is settable from the environment and invisible to
    `compute_retrieval_fingerprint`, which hashes files. If any one of them
    left this hash still, an attributed scorecard could be served from a
    retrieval configuration nobody measured.
    """
    profile = _live_profile()
    assert profile[setting] != value, setting  # witness: the edit is a real change
    drifted = {**profile, setting: value}

    assert compute_retrieval_settings_sha256(drifted) != (
        compute_retrieval_settings_sha256(profile)
    )


def test_a_missing_settings_key_is_refused_rather_than_hashed_short():
    """Red-at-birth: a 14-key profile must fail loudly, not produce a
    valid-looking digest over a silently shorter key set."""
    profile = _live_profile()
    del profile["rrf_k"]

    with pytest.raises(RetrievalFingerprintError) as error:
        compute_retrieval_settings_sha256(profile)

    message = str(error.value)
    assert "rrf_k" in message  # the offending value
    assert message.startswith("found ")
    assert "; fix: " in message  # the nearest fix, per house standards rule 1


def test_an_unexpected_settings_key_is_refused():
    """The mirror image: a key the model does not declare must not be hashed
    in under a name that reads like a setting."""
    profile = {**_live_profile(), "rrf_k_typo": 60}

    with pytest.raises(RetrievalFingerprintError) as error:
        compute_retrieval_settings_sha256(profile)

    message = str(error.value)
    assert "rrf_k_typo" in message
    assert "; fix: " in message


def test_a_renamed_key_reports_both_halves_of_the_mismatch():
    """A rename keeps the count at 15, so a count-only check would pass it."""
    profile = _live_profile()
    profile["rrf_kk"] = profile.pop("rrf_k")

    with pytest.raises(RetrievalFingerprintError) as error:
        compute_retrieval_settings_sha256(profile)

    message = str(error.value)
    assert "rrf_k" in message
    assert "rrf_kk" in message


def test_float_settings_are_rendered_independently_of_their_python_type():
    """`scan_mem_multiplier: 2` in the yaml becomes `2.0` on the model and
    `2.0` again through JSON. A profile that reached here carrying the integer
    must not hash differently from the float that means the same thing."""
    profile = _live_profile()
    assert profile["scan_mem_multiplier"] == 2.0  # witness: the field is a float

    integral = {**profile, "scan_mem_multiplier": 2}

    assert compute_retrieval_settings_sha256(integral) == (
        compute_retrieval_settings_sha256(profile)
    )


def test_the_float_rendering_still_discriminates_between_different_floats():
    """Independence from the test above: normalizing the *type* must not
    normalize away the *value*."""
    profile = _live_profile()
    changed = {**profile, "scan_mem_multiplier": 4.0}

    assert compute_retrieval_settings_sha256(changed) != (
        compute_retrieval_settings_sha256(profile)
    )


def test_the_live_settings_hash_is_the_hash_of_the_resolved_profile():
    """The single seam both sides of the gate must use.

    `scripts/score_evals.py` records this at measurement time and
    `service/scorecard.py` recomputes it at serve time. If the two ever
    computed it from differently-constructed profiles the gate would read
    pending forever, so both call this one function and this test pins what it
    hashes.
    """
    assert compute_live_retrieval_settings_sha256() == (
        compute_retrieval_settings_sha256(RetrievalProfile().model_dump())
    )


def test_the_live_settings_hash_follows_an_environment_override(monkeypatch):
    """The end-to-end proof of the finding: `RRF_K=1` changes what is served,
    touches no manifest file, and must therefore move this hash."""
    baseline = compute_live_retrieval_settings_sha256()
    assert compute_retrieval_fingerprint() == compute_retrieval_fingerprint()
    fingerprint_before = compute_retrieval_fingerprint()

    monkeypatch.setenv("RRF_K", "1")

    assert compute_live_retrieval_settings_sha256() != baseline
    # Witness for the whole mechanism: the file fingerprint really is blind to
    # this, which is why the settings hash has to exist.
    assert compute_retrieval_fingerprint() == fingerprint_before
