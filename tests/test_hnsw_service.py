"""The HNSW instrument's endpoints, and the safety properties of its probe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.hnsw import MEASURED_ARTIFACT, measured, neighborhood_band

ROOT = Path(__file__).resolve().parents[1]


def test_measured_artifact_is_the_committed_path():
    assert MEASURED_ARTIFACT == ROOT / "data" / "benchmarks" / "hnsw_measured.json"
    assert MEASURED_ARTIFACT.exists(), (
        "the instrument has no measurements to replay; fix: run `make benchmark-hnsw`"
    )


def test_measured_serves_the_committed_artifact_with_provenance():
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


def test_the_measured_artifact_separates_its_claim_classes():
    """Live, replayed, projected and A/B-cluster measurements are different claims.

    The NVMe result carries a stated non-default shared_buffers, so it cannot be read as
    a stock measurement of the workshop cluster and must say so in the artifact itself.
    """
    payload = measured()

    nvme = payload["local_nvme"]
    assert "not on the workshop cluster" in nvme["claim_class"]
    assert nvme["shared_buffers_bytes"] == 2 * 1024**3
    assert "stated deviation" in nvme["caveat"]
    assert nvme["instrumentation_limit"]
    assert nvme["index_build"]["verdict"] == "no measurable difference"
    assert len(nvme["cold_runs"]) >= 2, "one cold run is not a measurement"
