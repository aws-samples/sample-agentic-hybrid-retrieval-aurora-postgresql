"""Prove embedding checkpoints reject corruption and avoid repeat model calls."""

import gzip
import hashlib
import io
import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import numpy as np
import pytest
from botocore.exceptions import ClientError

from scripts import embed_real_catalog as embed
from scripts.prepare_real_catalog import canonical, embedding_text, sha256


def record(identity="A"):
    original = {
        "parent_asin": identity,
        "title": "A source product",
        "features": ["An original feature."],
        "description": [],
        "categories": ["Electronics"],
        "details": {},
    }
    text = embedding_text(original)
    return {
        "parent_asin": identity,
        "original": original,
        "source_record_sha256": sha256(canonical(original)),
        "embedding_text": text,
        "embedding_text_sha256": sha256(text),
    }


def response(count=1):
    vectors = [[0.5] * embed.COHERE_EMBED_V4_DIMENSIONS for _ in range(count)]
    return {
        "body": io.BytesIO(json.dumps({"embeddings": {"float": vectors}}).encode()),
        "ResponseMetadata": {
            "RequestId": "test-request",
            "HTTPHeaders": {"x-amzn-bedrock-input-token-count": "123"},
        },
    }


def test_checkpoint_resume_executes_model_once_and_validates_source_identity(tmp_path):
    client = Mock()
    client.invoke_model.return_value = response()
    rows = [record()]
    first = embed.process_batch(rows, tmp_path, client)
    second = embed.process_batch(rows, tmp_path, client)
    assert not first["reused"] and second["reused"]
    assert client.invoke_model.call_count == 1
    assert first["input_tokens"] == 123
    request = json.loads(client.invoke_model.call_args.kwargs["body"])
    assert request["texts"] == [rows[0]["embedding_text"]]
    assert request["input_type"] == "search_document"
    path = next(tmp_path.glob("*.npz"))
    with pytest.raises(ValueError, match="different products or model"):
        embed.load_batch(path, embed.batch_identity([record("B")]))


def test_altered_vector_checkpoint_is_not_reused(tmp_path):
    client = Mock()
    client.invoke_model.return_value = response()
    rows = [record()]
    embed.process_batch(rows, tmp_path, client)
    path = next(tmp_path.glob("*.npz"))
    with np.load(path, allow_pickle=False) as saved:
        metadata = saved["metadata"].copy()
        vectors = saved["vectors"].copy()
    vectors[0, 0] = 0.25
    np.savez_compressed(path, vectors=vectors, metadata=metadata)
    with pytest.raises(ValueError, match="vector hash differs"):
        embed.process_batch(rows, tmp_path, client)
    assert client.invoke_model.call_count == 1


@pytest.mark.parametrize("value", [0, float("nan"), float("inf")])
def test_invalid_vectors_never_enter_cache(value):
    with pytest.raises(ValueError, match="Embedding (shape|norm) rule"):
        embed.validate_vectors([[value] * embed.COHERE_EMBED_V4_DIMENSIONS], 1)


def test_incomplete_model_output_is_rejected():
    with pytest.raises(ValueError, match="Embedding shape rule"):
        embed.validate_vectors([[0.5] * embed.COHERE_EMBED_V4_DIMENSIONS], 2)


def test_record_integrity_checked_before_submission(tmp_path):
    row = record()
    row["embedding_text"] += " invented specification"
    with gzip.open(tmp_path / "catalog.jsonl.gz", "wt") as stream:
        stream.write(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="Source text rule"):
        list(embed.iter_batches(tmp_path))


def test_selection_hash_checked_before_paid_calls(tmp_path):
    path = tmp_path / "catalog.jsonl.gz"
    path.write_bytes(b"original bytes")
    manifest = {
        "products": 1,
        "catalog_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (tmp_path / "selection.json").write_text(json.dumps(manifest))
    assert embed.verified_selection(tmp_path) == manifest
    path.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="Selection hash rule"):
        embed.verified_selection(tmp_path)


def test_empty_selection_cannot_be_reported_as_success(tmp_path):
    (tmp_path / "selection.json").write_text(json.dumps({"products": 0}))
    with pytest.raises(ValueError, match="Selection count rule"):
        embed.verified_selection(tmp_path)


def test_batch_boundary_is_stable_and_complete(tmp_path):
    rows = [record(str(i)) for i in range(embed.BATCH_PRODUCTS + 2)]
    with gzip.open(tmp_path / "catalog.jsonl.gz", "wt") as stream:
        for row in rows:
            stream.write(canonical(row) + "\n")
    batches = list(embed.iter_batches(tmp_path))
    assert [len(batch) for batch in batches] == [embed.BATCH_PRODUCTS, 2]
    assert [row["parent_asin"] for batch in batches for row in batch] == [
        str(i) for i in range(len(rows))
    ]


def test_missing_usage_is_distinct_from_zero():
    assert embed.input_tokens({}, {}) is None
    assert embed.input_tokens({}, {"meta": {"billed_units": {"input_tokens": 0}}}) == 0


def test_request_pacing_leaves_no_initial_burst_and_does_not_build_idle_debt():
    pacer = embed.TokenPacer(600)
    assert pacer.delay_for(300, now=0) == 0
    assert pacer.delay_for(300, now=0) == 10
    assert pacer.delay_for(300, now=60) == 0


def test_requested_quota_is_not_treated_as_applied_capacity():
    assert embed.throughput_budget(300_000, None) == 255_000
    assert embed.throughput_budget(300_000, 100_000) == 100_000
    with pytest.raises(ValueError, match="applied quota 300000"):
        embed.throughput_budget(300_000, 5_000_000)


def test_running_job_adopts_an_applied_increase_but_not_a_failed_lookup():
    quotas = Mock()
    quotas.get_service_quota.return_value = {"Quota": {"Value": 5_000_000}}
    pacer = embed.TokenPacer(255_000)
    target = embed.RegionTarget("us-east-1", Mock(), pacer, 300_000, quotas)
    embed.refresh_budget(target)
    assert pacer.tokens_per_minute == 4_250_000
    assert target.applied_tokens_per_minute == 5_000_000
    quotas.get_service_quota.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "try later"}},
        "GetServiceQuota",
    )
    embed.refresh_budget(target)
    assert pacer.tokens_per_minute == 4_250_000


def test_counting_reused_batches_does_not_report_them_as_new_model_usage():
    report = dict.fromkeys(
        [
            "products",
            "newly_embedded",
            "reused_products",
            "batches",
            "input_tokens",
            "new_input_tokens",
            "batches_without_token_usage",
        ],
        0,
    )
    identity = {"products": ["A", "B"]}
    embed.count_result(
        report, {"identity": identity, "input_tokens": 42, "reused": True}
    )
    assert report["input_tokens"] == 42
    assert report["new_input_tokens"] == 0
    assert report["newly_embedded"] == 0
    embed.count_result(
        report, {"identity": identity, "input_tokens": None, "reused": False}
    )
    assert report["batches_without_token_usage"] == 1
    assert report["newly_embedded"] == 2


def profile():
    model = embed.COHERE_EMBED_V4_MODEL_ID.removeprefix("us.")
    return {
        "status": "ACTIVE",
        "inferenceProfileId": embed.COHERE_EMBED_V4_MODEL_ID,
        "models": [
            {"modelArn": f"arn:aws:bedrock:{region}::foundation-model/{model}"}
            for region in embed.US_REGIONS
        ],
    }


@pytest.mark.parametrize(
    "regions,workers",
    [
        ((), 4),
        (("us-east-1", "us-east-1"), 4),
        (("eu-west-1",), 4),
        (embed.US_REGIONS, 2),
        (("us-east-1",), 17),
    ],
)
def test_region_configuration_cannot_duplicate_or_expand_capacity(regions, workers):
    with pytest.raises(ValueError, match="Embedding (Region|worker) rule"):
        embed.validate_regions(regions, workers)
    embed.validate_regions(embed.US_REGIONS, 12)


@pytest.mark.parametrize(
    "change", ["inactive", "wrong-id", "wrong-model", "outside-us", "empty"]
)
def test_profile_guard_blocks_model_or_geography_drift(change):
    value = profile()
    embed.validate_profile("us-east-1", value)
    if change == "inactive":
        value["status"] = "CREATING"
    elif change == "wrong-id":
        value["inferenceProfileId"] = "global.cohere.embed-v4:0"
    elif change == "wrong-model":
        value["models"][0]["modelArn"] = value["models"][0]["modelArn"].replace(
            "v4", "v3"
        )
    elif change == "outside-us":
        value["models"][0]["modelArn"] = value["models"][0]["modelArn"].replace(
            "us-east-1", "eu-west-1"
        )
    else:
        value["models"] = []
    with pytest.raises(ValueError, match="Embedding profile rule"):
        embed.validate_profile("us-east-1", value)
    restored = profile()
    restored["inferenceProfileName"] = "An unrelated display-name change"
    embed.validate_profile("us-east-1", restored)


def test_regional_pacing_is_independent_and_does_not_claim_an_account_increase():
    targets = [
        embed.RegionTarget(region, Mock(), embed.TokenPacer(600), 1_000)
        for region in embed.US_REGIONS
    ]
    for target in targets:
        assert target.pacer.delay_for(300, now=0) == 0
        assert target.pacer.delay_for(300, now=0) == 10
    targets[1].quotas = Mock()
    targets[1].quotas.get_service_quota.return_value = {"Quota": {"Value": 2_000}}
    embed.refresh_budget(targets[1])
    report = {}
    embed.report_budgets(targets, report)
    assert report["applied_account_tokens_per_minute"] is None
    assert report["applied_tokens_per_minute_by_region"] == {
        "us-east-1": 1_000,
        "us-east-2": 2_000,
        "us-west-2": 1_000,
    }
    assert report["job_token_budget_per_minute_by_region"] == {
        "us-east-1": 600,
        "us-east-2": 1_700,
        "us-west-2": 600,
    }
    assert report["job_token_budget_per_minute"] == 2_900
    embed.report_budgets(targets[:1], report)
    assert report["applied_account_tokens_per_minute"] == 1_000


def test_cache_reuse_is_independent_of_request_region(tmp_path):
    rows = [record()]
    east, west = Mock(), Mock()
    east.invoke_model.return_value = response()
    original = embed.process_batch(rows, tmp_path, east, region="us-east-1")
    resumed = embed.process_batch(rows, tmp_path, west, region="us-west-2")
    assert resumed == {**original, "reused": True}
    assert resumed["request_region"] == "us-east-1"
    west.invoke_model.assert_not_called()
    assert "request_region" not in embed.batch_identity(rows)


def test_preflight_reads_and_assigns_each_regions_own_applied_quota(monkeypatch):
    import boto3

    clients = {}
    for index, region in enumerate(embed.US_REGIONS):
        control = Mock()
        control.get_inference_profile.return_value = profile()
        quotas = Mock()
        quotas.get_service_quota.return_value = {
            "Quota": {"Value": 300_000 + index * 100_000}
        }
        clients["bedrock", region] = control
        clients["service-quotas", region] = quotas
        clients["bedrock-runtime", region] = Mock()
    factory = Mock(
        side_effect=lambda name, *, region_name, **kwargs: clients[name, region_name]
    )
    monkeypatch.setattr(boto3, "client", factory)
    targets = embed.regional_targets(embed.US_REGIONS, 12, None)
    assert [target.pacer.tokens_per_minute for target in targets] == [
        255_000,
        340_000,
        425_000,
    ]
    for target in targets:
        assert target.client is clients["bedrock-runtime", target.region]
        assert target.quotas is clients["service-quotas", target.region]
        clients["bedrock", target.region].get_inference_profile.assert_called_once_with(
            inferenceProfileIdentifier=embed.COHERE_EMBED_V4_MODEL_ID
        )
        target.client.invoke_model.assert_not_called()
    fixed = embed.regional_targets(("us-east-1",), 4, 100_000)
    assert fixed[0].pacer.tokens_per_minute == 100_000 and fixed[0].quotas is None
    with pytest.raises(ValueError, match="applied quota 300000"):
        embed.regional_targets(embed.US_REGIONS, 12, 5_000_000)


def write_selection(directory, count):
    with gzip.open(directory / "catalog.jsonl.gz", "wt") as stream:
        for index in range(count):
            stream.write(canonical(record(str(index))) + "\n")
    catalog_hash = hashlib.sha256(
        (directory / "catalog.jsonl.gz").read_bytes()
    ).hexdigest()
    (directory / "selection.json").write_text(
        json.dumps({"products": count, "catalog_sha256": catalog_hash})
    )


def test_regional_run_preserves_existing_cache_and_embeds_each_remaining_product_once(
    tmp_path, monkeypatch
):
    count = 6 * embed.BATCH_PRODUCTS
    write_selection(tmp_path, count)
    output = tmp_path / "embeddings"
    output.mkdir()
    existing = Mock()
    existing.invoke_model.return_value = response(embed.BATCH_PRODUCTS)
    first = next(embed.iter_batches(tmp_path))
    embed.process_batch(first, output, existing)
    saved_path = next(output.glob("*.npz"))
    saved_bytes = saved_path.read_bytes()
    rendezvous = threading.Barrier(len(embed.US_REGIONS), timeout=5)
    targets = []
    for region in embed.US_REGIONS:
        client = Mock()
        entered = threading.Event()

        def invoke(*, body, entered=entered, **kwargs):
            if not entered.is_set():
                entered.set()
                rendezvous.wait()
            return response(len(json.loads(body)["texts"]))

        client.invoke_model.side_effect = invoke
        targets.append(embed.RegionTarget(region, client, Mock(), 300_000))
        targets[-1].pacer.tokens_per_minute = 255_000
        targets[-1].pacer.snapshot.return_value = {"strategy": "test"}
    monkeypatch.setattr(embed, "regional_targets", lambda *args: targets)
    result = embed.run(tmp_path, workers=3, max_batches=None, regions=embed.US_REGIONS)
    assert result["complete"] and result["products"] == count
    assert result["reused_products"] == embed.BATCH_PRODUCTS
    assert result["newly_embedded"] == count - embed.BATCH_PRODUCTS
    assert set(result["newly_embedded_by_region"]) == set(embed.US_REGIONS)
    assert all(target.pacer.acquire.called for target in targets)
    requests = [
        json.loads(call.kwargs["body"])["texts"]
        for target in targets
        for call in target.client.invoke_model.call_args_list
    ]
    expected = [
        record(str(index))["embedding_text"]
        for index in range(embed.BATCH_PRODUCTS, count)
    ]
    assert Counter(text for batch in requests for text in batch) == Counter(expected)
    assert saved_path.read_bytes() == saved_bytes
    resumed = embed.run(tmp_path, workers=3, max_batches=None, regions=embed.US_REGIONS)
    assert resumed["complete"] and resumed["newly_embedded"] == 0
    assert sum(target.client.invoke_model.call_count for target in targets) == 5


def test_measured_pacing_learns_only_known_usage_and_retains_headroom():
    pacer = embed.TokenPacer(600, adaptive=True)
    for _ in range(8):
        pacer.learn(300, 75)
    pacer.learn(300, None)
    pacer.learn(300, 0)
    pacer.learn(0, 75)
    assert pacer.snapshot()["samples"] == 8
    assert pacer.snapshot()["estimated_tokens_per_character"] == 0.2625
    delay, reservation = pacer.reserve(300, now=0)
    assert delay == 0 and reservation.tokens == 79
    delay, denied = pacer.reserve(300, now=0)
    assert denied is None and delay == pytest.approx(7.9)
    pacer.learn(300, 180)
    assert pacer.snapshot()["estimated_tokens_per_character"] == 0.6


def test_underestimated_response_blocks_the_next_request_until_budget_recovers():
    pacer = embed.TokenPacer(300, adaptive=True)
    _, first = pacer.reserve(300, now=0)
    assert first.tokens == 100
    pacer.complete(first, 250, now=1)
    delay, denied = pacer.reserve(300, now=50)
    assert denied is None and delay == 11
    delay, second = pacer.reserve(300, now=61)
    assert second is not None and delay == 0


def test_pending_requests_do_not_expire_before_the_response_arrives():
    pacer = embed.TokenPacer(100, adaptive=True)
    _, pending = pacer.reserve(300, now=0)
    delay, denied = pacer.reserve(300, now=90)
    assert denied is None and delay > 0
    pacer.complete(pending, 100, now=91)
    assert pacer.reserve(300, now=150)[1] is None
    assert pacer.reserve(300, now=151)[1] is not None


def test_missing_usage_and_retries_do_not_release_unverified_capacity():
    pacer = embed.TokenPacer(600, adaptive=True)
    _, reserved = pacer.reserve(300, now=0)
    pacer.complete(reserved, None, retry_attempts=2, now=1)
    assert reserved.tokens == 300
    assert pacer.snapshot()["reported_retry_attempts"] == 2
    assert pacer.reserve(300, now=29)[1] is None
    assert pacer.reserve(300, now=30)[1] is not None


def test_cached_usage_trains_estimates_without_consuming_current_quota(tmp_path):
    client = Mock()
    client.invoke_model.return_value = response()
    rows = [record()]
    original = embed.process_batch(rows, tmp_path, client)
    saved_bytes = next(tmp_path.glob("*.npz")).read_bytes()
    pacer = embed.TokenPacer(600, adaptive=True)
    reused = embed.process_batch(rows, tmp_path, client, pacer)
    assert reused == {**original, "reused": True}
    assert pacer.snapshot()["samples"] == 1
    assert pacer.reservations == [] and pacer.next_request_at == 0
    client.invoke_model.assert_called_once()
    assert next(tmp_path.glob("*.npz")).read_bytes() == saved_bytes


def test_parallel_admission_cannot_reserve_the_same_region_capacity_twice():
    pacer = embed.TokenPacer(600, adaptive=True)
    ready = threading.Barrier(8, timeout=5)

    def request():
        ready.wait()
        return pacer.reserve(300, now=0)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: request(), range(8)))
    assert sum(reservation is not None for _, reservation in results) == 1
    assert len(pacer.reservations) == 1


def test_budget_reduction_is_respected_before_admitting_new_work():
    pacer = embed.TokenPacer(600, adaptive=True)
    _, first = pacer.reserve(900, now=0)
    pacer.complete(first, 300, now=1)
    pacer.set_budget(300)
    assert pacer.reserve(300, now=30)[1] is None
    assert pacer.reserve(300, now=61)[1] is not None
    with pytest.raises(ValueError, match="estimated tokens=400, job budget=300"):
        pacer.reserve(1200, now=100)


def test_production_batch_reconciles_usage_and_records_request_timing(tmp_path):
    client = Mock()
    reply = response()
    reply["ResponseMetadata"]["RetryAttempts"] = 1
    client.invoke_model.return_value = reply
    pacer = embed.TokenPacer(600, adaptive=True)
    result = embed.process_batch([record()], tmp_path, client, pacer, "us-east-1")
    assert result["input_tokens"] == 123 and result["retry_attempts"] == 1
    assert result["request_started_at"] <= result["request_completed_at"]
    assert pacer.snapshot()["samples"] == 1
    assert pacer.snapshot()["reported_retry_attempts"] == 1
    assert pacer.reservations[0].tokens == 246
    assert pacer.reservations[0].completed_at is not None


def test_replayed_batches_increase_throughput_within_the_rolling_budget():
    pacer = embed.TokenPacer(255_000, adaptive=True)
    for _ in range(8):
        pacer.learn(100_000, 27_000)
    started_at = []
    now = 0.0
    for _ in range(50):
        reservation = None
        while reservation is None:
            delay, reservation = pacer.reserve(100_000, now)
            now += delay
        started_at.append(now)
        pacer.complete(reservation, 27_000, now=now + 2)
        pacer.learn(100_000, 27_000)
        assert (
            sum(27_000 for timestamp in started_at if now - 60 < timestamp <= now)
            <= 255_000
        )
        now += 2
    conservative_seconds = (len(started_at) - 1) * (100_000 / 3) / 255_000 * 60
    assert started_at[-1] < conservative_seconds * 0.92
