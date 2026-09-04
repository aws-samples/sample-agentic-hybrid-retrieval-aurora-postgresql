"""The HNSW instrument's endpoints, and the safety properties of its probe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.hnsw import MEASURED_ARTIFACT, measured, neighborhood_band

ROOT = Path(__file__).resolve().parents[1]

HALFVEC_INDEX = "product_document_embedding_hnsw_halfvec_idx"
BINARY_INDEX = "product_document_embedding_hnsw_binary_idx"


def _stub_index_states(monkeypatch, states: dict[str, str]) -> None:
    """Answer the representation gate's catalog read without a cluster.

    Every `measured()` call reaches this gate. Left unstubbed with DATABASE_URL
    exported, the test opens a real connection to whatever that DSN names and
    hangs there until the pool times out, which is not what any of these tests
    are asserting.
    """
    monkeypatch.setattr("service.hnsw.index_states", lambda names: dict(states))


def _stub_quantized_indexes_valid(monkeypatch) -> None:
    """The state in which `measured()` serves the artifact unmodified."""
    _stub_index_states(monkeypatch, {HALFVEC_INDEX: "valid", BINARY_INDEX: "valid"})


def test_measured_artifact_is_the_committed_path():
    assert MEASURED_ARTIFACT == ROOT / "data" / "benchmarks" / "hnsw_measured.json"
    assert MEASURED_ARTIFACT.exists(), (
        "the instrument has no measurements to replay; fix: run `make benchmark-hnsw`"
    )


def test_measured_serves_the_committed_artifact_with_provenance(monkeypatch):
    _stub_quantized_indexes_valid(monkeypatch)

    payload = measured()

    assert payload["kind"] == "measured"
    for key in (
        "source_revision",
        "dataset_manifest_sha256",
        "database_instance_id",
        "instance_class",
        "query_sample_sha256",
    ):
        assert payload["provenance"].get(key), key


def test_measured_refuses_a_projection_shaped_payload(tmp_path, monkeypatch):
    """An artifact whose kind is not `measured` must not be served as measured.

    The page labels this payload measured in its own chrome. Serving a projection
    through it would put a projected number under a MEASURED badge, which is the one
    failure this whole rebuild exists to remove.
    """
    fake = tmp_path / "hnsw_measured.json"
    fake.write_text(json.dumps({"kind": "simulated_calibrated"}), encoding="utf-8")
    monkeypatch.setattr("service.hnsw.MEASURED_ARTIFACT", fake)

    with pytest.raises(RuntimeError) as raised:
        measured()

    assert "simulated_calibrated" in str(raised.value)
    assert "fix:" in str(raised.value)


def test_measured_refuses_a_missing_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("service.hnsw.MEASURED_ARTIFACT", tmp_path / "absent.json")

    with pytest.raises(RuntimeError) as raised:
        measured()

    assert "fix:" in str(raised.value)


def test_band_width_is_the_distance_span_of_the_returned_ranks():
    band = neighborhood_band([0.0, 0.3374, 0.3512, 0.3697])

    assert band == {"nearest": 0.3374, "kth": 0.3697, "width": 0.0323}


def test_band_ignores_the_anchors_own_zero_distance():
    """An anchor is its own nearest neighbour at distance exactly 0.

    Including it would report a band width of 0.3697 instead of 0.0323 and destroy
    the point: neighbours 2 through k sit inside a 0.03-wide annulus.
    """
    assert neighborhood_band([0.0, 0.5, 0.6])["nearest"] == 0.5


def test_band_of_a_single_neighbour_has_zero_width():
    assert neighborhood_band([0.0, 0.42]) == {
        "nearest": 0.42,
        "kth": 0.42,
        "width": 0.0,
    }


def test_band_of_no_neighbours_is_none():
    assert neighborhood_band([0.0]) is None
    assert neighborhood_band([]) is None


def test_missing_probe_ground_truth_is_refused_instead_of_reporting_zero_recall():
    from scripts.seed_exact_neighbors import StaleGroundTruth
    from service.hnsw import require_probe_ground_truth

    with pytest.raises(StaleGroundTruth) as raised:
        require_probe_ground_truth(
            {},
            anchor_product_id=1,
            preset_key="none",
            k=10,
            manifest_sha256="current-manifest",
        )

    message = str(raised.value)
    assert "current-manifest" in message
    assert "make db-seed-exact-neighbors" in message


def test_probe_ground_truth_keeps_exact_rank_order():
    from service.hnsw import require_probe_ground_truth

    assert require_probe_ground_truth(
        {(1, "none"): [1, 10, 20]},
        anchor_product_id=1,
        preset_key="none",
        k=2,
        manifest_sha256="current-manifest",
    ) == [1, 10]


def test_hnsw_products_include_the_category_identity_needed_for_photography():
    from service.hnsw import _PRODUCT_COLUMNS

    assert "category_key" in _PRODUCT_COLUMNS


def test_every_preset_probe_sql_repeats_the_partial_index_predicate():
    """The index is partial. Omitting `embedding IS NOT NULL` costs 929x.

    Measured: with the predicate, Index Scan, 2.4 ms, 2,336 buffers. Without it,
    Sort + Seq Scan, 2,182 ms, 2,300,855 buffers — identical output. This assertion
    is why that cannot regress silently.
    """
    from service.hnsw import probe_sql
    from service.hnsw_presets import FILTER_PRESETS

    for preset in FILTER_PRESETS:
        assert "embedding IS NOT NULL" in probe_sql(preset), preset.key


def test_probe_sql_takes_exactly_two_bound_parameters():
    """The vector and the limit. Everything else is a fixed preset predicate."""
    from service.hnsw import probe_sql
    from service.hnsw_presets import FILTER_PRESETS

    for preset in FILTER_PRESETS:
        sql = probe_sql(preset)
        assert sql.count("%s") == 2, preset.key
        assert "ef_search" not in sql
        assert "scan_mem" not in sql
        assert "max_scan_tuples" not in sql


def test_probe_sql_never_selects_more_than_the_product_id():
    """A probe measures retrieval cost. Returning payload columns would inflate it."""
    from service.hnsw import probe_sql
    from service.hnsw_presets import PRESETS_BY_KEY

    assert "SELECT product_id" in probe_sql(PRESETS_BY_KEY["none"])
    assert "embedding," not in probe_sql(PRESETS_BY_KEY["none"])


def test_resolve_preset_refuses_an_unknown_key_and_names_the_alternatives():
    from service.hnsw import resolve_preset

    with pytest.raises(KeyError) as raised:
        resolve_preset("'; DROP TABLE mosaic_search.product_document; --")

    message = str(raised.value)
    assert "fix:" in message
    assert "none" in message


def test_resolve_preset_returns_the_enumerated_preset():
    from service.hnsw import resolve_preset

    assert resolve_preset("domain").predicate_sql == "domain = 'home_office'"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ef_search", 0),
        ("ef_search", 1001),
        ("scan_mem_multiplier", 0.5),
        ("scan_mem_multiplier", 65),
        ("max_scan_tuples", 0),
        ("max_scan_tuples", 2_000_001),
        ("k", 0),
        ("k", 51),
        ("anchor_product_id", 0),
        ("iterative_scan", "sideways"),
        ("filter_preset", ""),
    ],
)
def test_probe_request_rejects_out_of_range_values(field, value):
    from pydantic import ValidationError

    from service.models import HnswProbeRequest

    payload = {"anchor_product_id": 1} | {field: value}

    with pytest.raises(ValidationError):
        HnswProbeRequest.model_validate(payload)


def test_probe_request_forbids_unknown_fields():
    """A caller must not be able to smuggle a planner setting past the contract."""
    from pydantic import ValidationError

    from service.models import HnswProbeRequest

    with pytest.raises(ValidationError):
        HnswProbeRequest.model_validate(
            {"anchor_product_id": 1, "enable_indexscan": False}
        )


def test_probe_request_allows_the_pre_fix_multiplier():
    """1 must stay reachable so the truncation it caused can be reproduced."""
    from service.models import HnswProbeRequest

    assert (
        HnswProbeRequest(anchor_product_id=1, scan_mem_multiplier=1).scan_mem_multiplier
        == 1
    )


def test_probe_applies_settings_only_through_the_production_function():
    """A probe that reached set_config would measure a path requests never take."""
    source = (ROOT / "service" / "hnsw.py").read_text(encoding="utf-8")

    assert "mosaic_search.configure_hnsw" in source
    assert "SELECT set_config" not in source
    assert "PERFORM set_config" not in source
    assert "SET LOCAL statement_timeout" in source


def test_probe_never_disables_a_scan_method():
    """The exact path is precomputed. Nothing here may force a sequential scan."""
    source = (ROOT / "service" / "hnsw.py").read_text(encoding="utf-8")

    assert "enable_indexscan" not in source
    assert "enable_bitmapscan" not in source


@pytest.mark.parametrize("representation", ["fp32", "halfvec", "binary"])
def test_every_representation_repeats_the_partial_index_predicate(representation):
    """All three indexes are partial. Dropping the predicate costs 800x on any of them."""
    from service.hnsw import probe_sql
    from service.hnsw_presets import FILTER_PRESETS

    for preset in FILTER_PRESETS:
        assert "embedding IS NOT NULL" in probe_sql(preset, representation), preset.key


def test_representation_sql_reaches_the_right_operator_family():
    """bit_hamming_ops has no cosine operator, so binary must use `<~>` and rerank."""
    from service.hnsw import probe_sql
    from service.hnsw_presets import PRESETS_BY_KEY

    none = PRESETS_BY_KEY["none"]
    assert "embedding <=> %s" in probe_sql(none, "fp32")
    assert "halfvec(1024) <=> %s::halfvec(1024)" in probe_sql(none, "halfvec")
    binary = probe_sql(none, "binary")
    assert "<~>" in binary
    assert "binary_quantize" in binary
    # The second pass is what recovers ordering; without it binary is a hamming ranking.
    assert "ORDER BY candidates.embedding <=> %s" in binary


def test_binary_takes_four_bound_parameters_and_the_others_two():
    from service.hnsw import probe_parameters, probe_sql
    from service.hnsw_presets import PRESETS_BY_KEY
    from service.models import HnswProbeRequest

    for representation, expected in (("fp32", 2), ("halfvec", 2), ("binary", 4)):
        request = HnswProbeRequest(anchor_product_id=1, representation=representation)
        assert len(probe_parameters(request, None)) == expected, representation
        assert probe_sql(PRESETS_BY_KEY["none"], representation).count("%s") == expected


def test_an_unknown_representation_is_refused_with_the_alternatives():
    from service.hnsw import probe_sql
    from service.hnsw_presets import PRESETS_BY_KEY

    with pytest.raises(KeyError) as raised:
        probe_sql(PRESETS_BY_KEY["none"], "int8")

    assert "fix:" in str(raised.value)
    assert "halfvec" in str(raised.value)


def test_probe_defaults_resolve_from_the_yaml_not_from_literals():
    """A literal default here would be a second copy of a served number.

    config_tripwire caught exactly that: PerformancePage hardcoded scan_mem_multiplier
    and max_scan_tuples while the yaml was the declared single source.
    """
    from scripts.retrieval_profile import load_profile
    from service.models import HnswProbeRequest

    profile = load_profile()
    request = HnswProbeRequest(anchor_product_id=1)

    assert request.ef_search == profile.hnsw_ef_search
    assert request.scan_mem_multiplier == profile.hnsw_scan_mem_multiplier
    assert request.max_scan_tuples == profile.hnsw_max_scan_tuples


def test_the_measured_artifact_separates_its_claim_classes(monkeypatch):
    """Live, replayed, projected and A/B-cluster measurements are different claims.

    The NVMe result carries a stated non-default shared_buffers, so it cannot be read as
    a stock measurement of the workshop cluster and must say so in the artifact itself.
    """
    _stub_quantized_indexes_valid(monkeypatch)

    payload = measured()

    nvme = payload["local_nvme"]
    assert "not on the workshop cluster" in nvme["claim_class"]
    assert nvme["shared_buffers_bytes"] == 2 * 1024**3
    assert "stated deviation" in nvme["caveat"]
    assert nvme["instrumentation_limit"]
    assert nvme["index_build"]["verdict"] == "no measurable difference"
    assert len(nvme["cold_runs"]) >= 2, "one cold run is not a measurement"


# --- Attribution: whose corpus and whose worktree these numbers describe -------


class _FakeSettings:
    """The three identity fields `measured()` compares against the artifact."""

    def __init__(
        self,
        *,
        manifest: str,
        revision: str = "b" * 40,
        dirty: bool = False,
        database_url: str | None = None,
    ) -> None:
        self.dataset_manifest_sha256 = manifest
        self.source_revision = revision
        self.source_worktree_dirty = dirty
        self.database_url = database_url


RUNTIME_MANIFEST = "d5abc2c047f73726926260bb6a5364b50295acc4c6b2a3e9e35d47e93eb5c464"


def _stub_settings(monkeypatch, settings) -> None:
    monkeypatch.setattr("service.hnsw.get_settings", lambda: settings)


def test_measured_refuses_to_claim_an_artifact_measured_on_another_corpus(monkeypatch):
    """The committed artifact was measured elsewhere, and must say so.

    Its provenance records manifest 7cd7a5ae and `source_worktree_dirty: true`,
    while the connected corpus reports d5abc2c0. Serving that under an
    unqualified MEASURED badge is the exact failure the badge exists to prevent.
    """
    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))
    _stub_quantized_indexes_valid(monkeypatch)

    attribution = measured()["attribution"]

    assert attribution["attributed"] is False
    assert "different dataset manifest" in attribution["attribution_note"]
    assert "dirty worktree" in attribution["attribution_note"]
    assert "make benchmark-hnsw" in attribution["attribution_note"]
    assert attribution["measured_source_revision"].startswith("e5b10ef")
    assert attribution["measured_source_worktree_dirty"] is True
    assert attribution["measured_dataset_manifest_sha256"].startswith("7cd7a5ae")
    assert attribution["current_dataset_manifest_sha256"] == RUNTIME_MANIFEST
    assert attribution["current_source_revision"] == "b" * 40
    assert attribution["current_source_worktree_dirty"] is False


def test_the_attribution_note_is_prose_not_an_error_message(monkeypatch):
    """The note is rendered as body copy under the badge, not raised anywhere.

    Built with `explain(found, fix)` it read as a fault in the page rather than
    as a statement about which cluster the numbers describe. The scorecard's
    note beside it on the same surface is prose; this one has to match it.
    """
    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))
    _stub_quantized_indexes_valid(monkeypatch)

    note = measured()["attribution"]["attribution_note"]

    assert "found:" not in note
    assert "fix:" not in note
    assert note[0].isupper() and note.endswith(".")


def _clean_artifact(tmp_path, manifest: str):
    payload = json.loads(MEASURED_ARTIFACT.read_text(encoding="utf-8"))
    payload["provenance"] = payload["provenance"] | {
        "dataset_manifest_sha256": manifest,
        "source_worktree_dirty": False,
    }
    fixture = tmp_path / "hnsw_measured.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    return fixture


def test_measured_is_attributed_when_the_corpus_matches_and_the_tree_was_clean(
    tmp_path, monkeypatch
):
    """The positive control for the gate above, byte-identical but for provenance."""
    monkeypatch.setattr(
        "service.hnsw.MEASURED_ARTIFACT", _clean_artifact(tmp_path, RUNTIME_MANIFEST)
    )
    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))
    _stub_quantized_indexes_valid(monkeypatch)

    attribution = measured()["attribution"]

    assert attribution["attributed"] is True
    assert "different dataset manifest" not in attribution["attribution_note"]
    assert "dirty worktree" not in attribution["attribution_note"]


def test_measured_is_not_attributed_when_the_connected_manifest_is_unresolved(
    tmp_path, monkeypatch
):
    """`unknown` matches nothing. Treating it as a match would attribute anything."""
    monkeypatch.setattr(
        "service.hnsw.MEASURED_ARTIFACT", _clean_artifact(tmp_path, "unknown")
    )
    _stub_settings(monkeypatch, _FakeSettings(manifest="unknown"))
    _stub_quantized_indexes_valid(monkeypatch)

    attribution = measured()["attribution"]

    assert attribution["attributed"] is False
    assert "unresolved dataset manifest" in attribution["attribution_note"]


# --- Representations: advertised only while the indexes behind them exist -----


def test_measured_withholds_representations_when_a_quantized_index_is_missing(
    monkeypatch,
):
    """Nothing in the bootstrap builds these two indexes.

    `db/sql/19_indexes_quantized.sql` is the only file that creates them and no
    phase runs it, so on a freshly bootstrapped cluster the halfvec and binary
    rows describe indexes the reader cannot inspect, EXPLAIN, or reproduce.
    """
    _stub_index_states(monkeypatch, {HALFVEC_INDEX: "missing", BINARY_INDEX: "valid"})
    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))

    payload = measured()

    assert "representations" not in payload
    reason = payload["representations_unavailable_reason"]
    assert HALFVEC_INDEX in reason
    assert "missing" in reason
    assert "make db-index-quantized" in reason
    assert "fix:" in reason


def test_measured_withholds_representations_when_a_quantized_index_is_invalid(
    monkeypatch,
):
    """An interrupted CREATE INDEX CONCURRENTLY leaves a relation that is not usable."""
    _stub_index_states(monkeypatch, {HALFVEC_INDEX: "valid", BINARY_INDEX: "invalid"})
    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))

    reason = measured()["representations_unavailable_reason"]

    assert BINARY_INDEX in reason
    assert "invalid" in reason


def test_measured_keeps_representations_when_both_quantized_indexes_are_valid(
    monkeypatch,
):
    _stub_quantized_indexes_valid(monkeypatch)
    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))

    payload = measured()

    assert payload["representations"]["rows"]
    assert "representations_unavailable_reason" not in payload


def test_measured_names_the_cluster_error_when_index_state_cannot_be_read(monkeypatch):
    """No cluster is not the same claim as no index, so the reason says which."""

    def unreachable(names):
        raise RuntimeError("DATABASE_URL is not configured")

    monkeypatch.setattr("service.hnsw.index_states", unreachable)
    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))

    payload = measured()

    assert "representations" not in payload
    assert "RuntimeError" in payload["representations_unavailable_reason"]


def test_index_states_asks_the_catalog_for_validity_and_readiness():
    """`indisvalid` alone is not enough; a not-ready index cannot serve a scan."""
    from service.db import INDEX_STATE_SQL

    assert "indisvalid" in INDEX_STATE_SQL
    assert "indisready" in INDEX_STATE_SQL
    assert "mosaic_search" in INDEX_STATE_SQL


def test_one_module_defines_what_a_usable_index_is():
    """`readiness()` and the representation gate had two copies of the rule.

    Two copies is two places for `indisready` to be forgotten, and the two
    surfaces would then disagree about the same index. Both now read
    `service.db.index_states_on`, so the predicate exists once.
    """
    defining = sorted(
        path.name
        for path in (ROOT / "service").glob("*.py")
        if "indisvalid" in path.read_text(encoding="utf-8")
    )

    assert defining == ["db.py"]


# --- Probe: refuse a representation whose index is not there ------------------


class _FakeConnection:
    """Answers the index-state query with canned catalog rows, nothing else."""

    def __init__(self, states: dict[str, str]) -> None:
        self.states = states

    def execute(self, sql, parameters=None):
        names = list(parameters[0]) if parameters else []
        rows = [
            {"name": name, "state": self.states.get(name, "missing")} for name in names
        ]
        return _FakeCursor(rows)


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_probe_refuses_a_representation_whose_index_was_never_built():
    from service.hnsw import RepresentationUnavailable, require_representation_index

    connection = _FakeConnection({})

    with pytest.raises(RepresentationUnavailable) as raised:
        require_representation_index(connection, "halfvec")

    message = str(raised.value)
    assert HALFVEC_INDEX in message
    assert "make db-index-quantized" in message
    assert "fix:" in message


def test_probe_runs_when_the_representation_index_is_valid():
    from service.hnsw import require_representation_index

    require_representation_index(_FakeConnection({HALFVEC_INDEX: "valid"}), "halfvec")


def test_probe_points_fp32_at_its_own_recovery_target():
    """The cosine index is bootstrap's, so its fix is not the quantized target."""
    from service.hnsw import RepresentationUnavailable, require_representation_index

    with pytest.raises(RepresentationUnavailable) as raised:
        require_representation_index(_FakeConnection({}), "fp32")

    assert "make db-drop-invalid-indexes" in str(raised.value)
    assert "make db-index-quantized" not in str(raised.value)


# --- The probe runs the statement twice, and now says so ----------------------


class _FakePlanConnection:
    def __init__(self):
        self.statements: list[str] = []

    def execute(self, sql, parameters=None):
        self.statements.append(sql)
        return _FakePlanCursor()


class _FakePlanCursor:
    def fetchone(self):
        return {
            "QUERY PLAN": [
                {
                    "Execution Time": 2.5,
                    "Plan": {
                        "Node Type": "Index Scan",
                        "Index Name": "product_document_embedding_hnsw_cosine_idx",
                        "Shared Hit Blocks": 514,
                        "Shared Read Blocks": 0,
                        "Total Cost": 1317.49,
                        "Plan Rows": 10,
                    },
                }
            ]
        }


def test_explain_labels_itself_as_the_second_execution_of_the_statement():
    """The response mixes two runs: rows from the first, timing from the second.

    `probe()` executes the ANN statement for its rows and then runs it again
    under EXPLAIN (ANALYZE). The second run finds the buffers already warm, so
    `server_ms` and the buffer counts are not the cost of a cold first query.
    """
    from service.hnsw import _explain_probe

    plan = _explain_probe(_FakePlanConnection(), "SELECT 1", [])

    assert "second execution" in plan["execution"]
    assert "first" in plan["execution"]


def test_no_docstring_claims_the_probe_runs_a_single_query():
    """Two docstrings said `one real ANN query` while the code ran two."""
    from service import main
    from service.hnsw import probe

    assert "one real ANN query" not in (probe.__doc__ or "")
    assert "one real ANN query" not in (main.hnsw_probe_route.__doc__ or "")
    # Absence alone would also pass a docstring that dropped the run count
    # entirely; require it to still say what actually happens.
    assert "twice" in (probe.__doc__ or "")


# --- The manifest guard is the ground-truth join, not a self-comparison -------


def test_manifest_refuses_an_unresolved_value(monkeypatch):
    from scripts.seed_exact_neighbors import StaleGroundTruth
    from service.hnsw import _manifest

    _stub_settings(monkeypatch, _FakeSettings(manifest="unknown"))

    with pytest.raises(StaleGroundTruth) as raised:
        _manifest()

    assert "fix:" in str(raised.value)


def test_manifest_returns_a_resolved_value(monkeypatch):
    from service.hnsw import _manifest

    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))

    assert _manifest() == RUNTIME_MANIFEST


def test_manifest_does_not_compare_a_value_against_itself():
    """`assert_manifest_matches(stored=m, connected=m)` can only ever be equal.

    It read as a corpus check and was not one. The real check is the
    `dataset_manifest_sha256 = %s` predicate on the ground-truth join.
    """
    source = (ROOT / "service" / "hnsw.py").read_text(encoding="utf-8")

    assert "stored=manifest, connected=manifest" not in source


def test_the_unreadable_cluster_reason_carries_no_connection_details(monkeypatch):
    """A psycopg connection failure names the host and the user.

    This string is served to every participant on `/api/hnsw/measured`, so it
    follows the rule the substrate handler already follows: the exception type,
    never its message.
    """

    def unreachable(names):
        raise RuntimeError(
            "connection to server at db.internal (10.0.0.4), port 5432 failed"
        )

    monkeypatch.setattr("service.hnsw.index_states", unreachable)
    _stub_settings(monkeypatch, _FakeSettings(manifest=RUNTIME_MANIFEST))

    reason = measured()["representations_unavailable_reason"]

    assert "RuntimeError" in reason
    assert "db.internal" not in reason
    assert "10.0.0.4" not in reason
