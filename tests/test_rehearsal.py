"""The rehearsal evidence manifest must catch the two ways it can lie.

Per docs/house-standards.md rule 4, a gate is proven red at birth: introduce
the violation, show it fail, restore byte-identical, show it pass. Both
`test_a_manifest_missing_a_required_stage_is_rejected` and
`test_an_unredacted_secret_is_rejected` follow that shape and keep the
violating fixture as a permanent test rather than a one-time demonstration.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest

from scripts.rehearsal import (
    REQUIRED_STAGES,
    RehearsalError,
    capture_identity,
    compute_overall_status,
    compute_timing_summary,
    find_secret_leaks,
    import_bootstrap_timings,
    main,
    new_manifest,
    parse_bootstrap_timings,
    record_cold_warm,
    record_first_query,
    record_layout,
    redact,
    upsert_stage,
    validate_manifest,
)


def _valid_manifest() -> dict:
    manifest = new_manifest(operator="facilitator")
    assert validate_manifest(manifest) == []
    return manifest


def _shaped_like_an_aws_access_key_id() -> str:
    """Build an AKIA-shaped value with no matching literal in this file's text.

    A literal `AKIA` immediately followed by 16 uppercase/digit characters
    trips the repository's own pre-commit secret scanner, which cannot tell
    this fixture from a real key. Assembling it from parts at import time
    keeps the *value* AKIA-shaped for `scripts.rehearsal`'s own regex to
    catch, while the source text of this file never contains the shape a
    line-based scanner looks for.
    """
    # Deliberately not the ruff-suggested single literal: FLY002 would collapse
    # this back into the contiguous AKIA-shaped text this function exists to
    # avoid writing to disk.
    return "AKIA" + "".join(  # noqa: FLY002
        ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "A", "S", "D", "F", "G", "H"]
    )


def test_a_fresh_manifest_carries_every_required_stage_unrun():
    manifest = new_manifest()
    assert set(manifest["stages"]) == set(REQUIRED_STAGES)
    assert all(
        stage["status"] == "not_started" for stage in manifest["stages"].values()
    )
    assert manifest["kind"] == "measured"
    assert validate_manifest(manifest) == []


def test_a_manifest_missing_a_required_stage_is_rejected():
    manifest = _valid_manifest()
    broken = copy.deepcopy(manifest)
    del broken["stages"]["layout_walkthrough"]

    problems = validate_manifest(broken)

    assert problems, "expected the missing stage to be reported"
    assert any("layout_walkthrough" in problem for problem in problems)
    # Restored byte-identical to the pre-violation manifest, the gate is quiet.
    assert validate_manifest(manifest) == []


@pytest.mark.parametrize(
    "leak",
    [
        "postgresql://mosaic_admin:Sup3rSecret!@cluster.example.rds.amazonaws.com:5432/mosaic",
        _shaped_like_an_aws_access_key_id(),
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdef",
        'password: "hunter2-actually-long-enough"',
        # An STS session credential, header or query form (deploy/mosaic-bootstrap.sh
        # forwards these when the Code Editor instance role assumes a role).
        "X-Amz-Security-Token: FQoGZXIvYXdzFAKEsessiontoken1234567890abcdef",
        # Workshop Studio's CodeEditorURL carries a bare tkn= token
        # (deploy/README.md); token= is the generic form of the same shape.
        "https://codeeditor.example.com/?tkn=abcDEF123456ghijKLM789fake",
        "https://example.com/callback?token=abcDEF123456ghijKLM789fake",
    ],
)
def test_an_unredacted_secret_is_rejected(leak):
    manifest = _valid_manifest()
    broken = copy.deepcopy(manifest)
    broken["stages"]["deployment_identity"]["detail"] = f"stack came up; dsn was {leak}"
    broken["stages"]["deployment_identity"]["status"] = "passed"

    problems = validate_manifest(broken)

    assert problems, f"expected {leak!r} to be flagged"
    # Restored to the redacted form, the same manifest passes.
    fixed = copy.deepcopy(broken)
    fixed["stages"]["deployment_identity"]["detail"] = redact(
        broken["stages"]["deployment_identity"]["detail"]
    )
    assert validate_manifest(fixed) == []
    assert validate_manifest(manifest) == []


def test_ordinary_prose_mentioning_secret_or_token_is_not_flagged():
    manifest = _valid_manifest()
    manifest["stages"]["deployment_identity"]["status"] = "passed"
    manifest["stages"]["deployment_identity"]["detail"] = (
        "no secret was exposed; the session token rotated automatically"
    )
    assert find_secret_leaks(manifest) == []


def test_record_stage_redacts_free_text_automatically():
    manifest = new_manifest()
    upsert_stage(
        manifest,
        "deployment_identity",
        status="passed",
        detail="connected using postgresql://mosaic:hunter2pass@db.example.com:5432/mosaic",
    )
    assert "hunter2pass" not in manifest["stages"]["deployment_identity"]["detail"]
    assert "[REDACTED]" in manifest["stages"]["deployment_identity"]["detail"]
    assert find_secret_leaks(manifest) == []


def test_record_stage_rejects_unknown_status():
    manifest = new_manifest()
    with pytest.raises(RehearsalError):
        upsert_stage(manifest, "deployment_identity", status="ok", detail="x")


def test_a_passed_stage_with_no_detail_is_rejected():
    manifest = _valid_manifest()
    manifest["stages"]["deployment_identity"]["status"] = "passed"
    manifest["stages"]["deployment_identity"]["detail"] = ""
    problems = validate_manifest(manifest)
    assert any("deployment_identity" in problem for problem in problems)


def test_wrong_kind_is_rejected():
    manifest = _valid_manifest()
    manifest["kind"] = "simulated_calibrated"
    problems = validate_manifest(manifest)
    assert any("kind" in problem for problem in problems)


@pytest.mark.parametrize(
    ("stages_status", "expected"),
    [
        (dict.fromkeys(REQUIRED_STAGES, "not_started"), "not_started"),
        (
            {
                **dict.fromkeys(REQUIRED_STAGES, "not_started"),
                "deployment_identity": "passed",
            },
            "in_progress",
        ),
        (dict.fromkeys(REQUIRED_STAGES, "passed"), "complete"),
        (
            {**dict.fromkeys(REQUIRED_STAGES, "passed"), "lab_2_rehearsal": "failed"},
            "blocked",
        ),
    ],
)
def test_overall_status_reflects_the_worst_and_best_case(stages_status, expected):
    manifest = new_manifest()
    for name, status in stages_status.items():
        manifest["stages"][name]["status"] = status
        manifest["stages"][name]["detail"] = "x" if status != "not_started" else ""
    assert compute_overall_status(manifest) == expected


def test_parse_bootstrap_timings_reads_phase_and_total_rows():
    text = "schema_install\t12\nindex_creation\t340\ntotal\t352\n"
    phases = parse_bootstrap_timings(text)
    assert phases == [
        {"name": "schema_install", "elapsed_seconds": 12.0},
        {"name": "index_creation", "elapsed_seconds": 340.0},
        {"name": "total", "elapsed_seconds": 352.0},
    ]


def test_parse_bootstrap_timings_rejects_a_malformed_line():
    with pytest.raises(RehearsalError):
        parse_bootstrap_timings("schema_install 12\n")


def test_import_bootstrap_timings_passes_on_a_complete_file(tmp_path):
    manifest = new_manifest()
    timings = tmp_path / "bootstrap-timings.tsv"
    phases = [
        "schema_install",
        "lab_schema_install",
        "catalog_prepare",
        "catalog_load",
        "index_creation",
        "premium_cohort_load",
        "evidence_load",
        "corpus_lexeme_seed",
        "smoke_test",
        "bootstrap_acceptance",
    ]
    lines = [f"{name}\t{10 + index}" for index, name in enumerate(phases)]
    total = sum(10 + index for index in range(len(phases)))
    lines.append(f"total\t{total}")
    timings.write_text("\n".join(lines) + "\n")

    import_bootstrap_timings(manifest, timings, started_at=None, ended_at=None)

    stage = manifest["stages"]["bootstrap_phases"]
    assert stage["status"] == "passed"
    assert stage["total_elapsed_seconds"] == total
    assert len(stage["phases"]) == len(phases) + 1
    assert str(timings) in stage["artifact_paths"]


def test_import_bootstrap_timings_fails_on_a_truncated_file(tmp_path):
    manifest = new_manifest()
    timings = tmp_path / "bootstrap-timings.tsv"
    timings.write_text("schema_install\t12\n")

    import_bootstrap_timings(manifest, timings, started_at=None, ended_at=None)

    stage = manifest["stages"]["bootstrap_phases"]
    assert stage["status"] == "failed"
    assert "index_creation" in stage["detail"]


def test_import_bootstrap_timings_fails_when_the_file_is_missing(tmp_path):
    manifest = new_manifest()
    import_bootstrap_timings(
        manifest, tmp_path / "missing.tsv", started_at=None, ended_at=None
    )
    assert manifest["stages"]["bootstrap_phases"]["status"] == "failed"


def _mock_client(responses: dict[str, tuple[int, dict]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path
        if key not in responses:
            raise AssertionError(f"unexpected request to {key}")
        status_code, body = responses[key]
        return httpx.Response(status_code, json=body, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_capture_identity_records_local_facts_without_an_api_url():
    manifest = new_manifest()
    capture_identity(manifest, api_url=None, timeout=5.0)
    stage = manifest["stages"]["deployment_identity"]
    assert stage["status"] == "skipped"
    assert manifest["effective_settings"]["retrieval_profile"]["rrf_k"]
    assert manifest["environment"]["served"] is None


def test_capture_identity_records_a_ready_served_environment():
    manifest = new_manifest()
    client = _mock_client(
        {
            "/api/health": (
                200,
                {"status": "ok", "models": {"embedding": "us.cohere.embed-v4:0"}},
            ),
            "/api/readiness": (
                200,
                {
                    "status": "ready",
                    "database": {"dataset_id": "reviews-2023-500k-v1"},
                    "configured_models": {"embedding": "us.cohere.embed-v4:0"},
                    "source": {"dataset_manifest_sha256": "abc123"},
                },
            ),
        }
    )
    try:
        capture_identity(
            manifest, api_url="http://workshop-host", timeout=5.0, client=client
        )
    finally:
        client.close()
    stage = manifest["stages"]["deployment_identity"]
    assert stage["status"] == "passed"
    assert manifest["dataset_identity"]["served_dataset_id"] == "reviews-2023-500k-v1"
    assert manifest["dataset_identity"]["served_catalog_sha256"] == "abc123"


def test_capture_identity_fails_when_the_deployment_reports_blocked():
    manifest = new_manifest()
    client = _mock_client(
        {
            "/api/health": (200, {"status": "ok", "models": {}}),
            "/api/readiness": (
                200,
                {
                    "status": "blocked",
                    "database": {},
                    "configured_models": {},
                    "source": {},
                },
            ),
        }
    )
    try:
        capture_identity(
            manifest, api_url="http://workshop-host", timeout=5.0, client=client
        )
    finally:
        client.close()
    assert manifest["stages"]["deployment_identity"]["status"] == "failed"


def test_capture_identity_records_elapsed_seconds_when_timestamps_are_given():
    """Red before the fix: capture_identity used to drop --started-at/--ended-at,
    so deployment_identity.elapsed_seconds stayed null forever and the timing
    rollup, and therefore overall_status, could never reach "complete"."""
    manifest = new_manifest()
    client = _mock_client(
        {
            "/api/health": (200, {"status": "ok", "models": {}}),
            "/api/readiness": (
                200,
                {
                    "status": "ready",
                    "database": {},
                    "configured_models": {},
                    "source": {},
                },
            ),
        }
    )
    try:
        capture_identity(
            manifest,
            api_url="http://workshop-host",
            timeout=5.0,
            started_at="2026-01-01T00:00:00+00:00",
            ended_at="2026-01-01T00:05:00+00:00",
            client=client,
        )
    finally:
        client.close()
    assert manifest["stages"]["deployment_identity"]["elapsed_seconds"] == 300.0


def test_record_first_query_stores_latency_without_disturbing_status_or_detail():
    manifest = new_manifest()
    manifest["stages"]["deployment_identity"]["status"] = "passed"
    manifest["stages"]["deployment_identity"]["detail"] = "already captured"
    client = _mock_client(
        {"/api/search": (200, {"diagnostics": {"total_latency_ms": 88}, "results": []})}
    )
    try:
        record_first_query(
            manifest, api_url="http://workshop-host", timeout=5.0, client=client
        )
    finally:
        client.close()
    stage = manifest["stages"]["deployment_identity"]
    assert stage["first_query_ms"] > 0
    assert stage["status"] == "passed"
    assert stage["detail"] == "already captured"


def test_record_first_query_raises_on_a_server_error_without_recording_a_fake_value():
    manifest = new_manifest()
    client = _mock_client({"/api/search": (503, {"detail": "database is not ready"})})
    try:
        with pytest.raises(RehearsalError):
            record_first_query(
                manifest, api_url="http://workshop-host", timeout=5.0, client=client
            )
    finally:
        client.close()
    assert "first_query_ms" not in manifest["stages"]["deployment_identity"]


def _fully_rehearsed_manifest(
    tmp_path: Path, *, include_first_query: bool = True
) -> dict:
    """Build a manifest as if every clean-account acceptance-test stage ran and passed.

    Used by both the "complete" witness (finding 1) and the missing-first-query
    regression (finding 2), so the two tests agree on what "everything else
    passed" means.
    """
    manifest = new_manifest(operator="facilitator")

    identity_client = _mock_client(
        {
            "/api/health": (200, {"status": "ok", "models": {}}),
            "/api/readiness": (
                200,
                {
                    "status": "ready",
                    "database": {"dataset_id": "reviews-2023-500k-v1"},
                    "configured_models": {"embedding": "us.cohere.embed-v4:0"},
                    "source": {"dataset_manifest_sha256": "abc123"},
                },
            ),
        }
    )
    try:
        capture_identity(
            manifest,
            api_url="http://workshop-host",
            timeout=5.0,
            started_at="2026-01-01T00:00:00+00:00",
            ended_at="2026-01-01T00:05:00+00:00",
            client=identity_client,
        )
    finally:
        identity_client.close()

    if include_first_query:
        search_client = _mock_client(
            {
                "/api/search": (
                    200,
                    {"diagnostics": {"total_latency_ms": 120}, "results": []},
                )
            }
        )
        try:
            record_first_query(
                manifest,
                api_url="http://workshop-host",
                timeout=5.0,
                client=search_client,
            )
        finally:
            search_client.close()

    upsert_stage(
        manifest,
        "archive_transfer_and_join",
        status="passed",
        detail="3 parts synced and joined; sha256 verified",
        started_at="2026-01-01T00:05:00+00:00",
        ended_at="2026-01-01T00:10:00+00:00",
    )

    phase_names = [
        "schema_install",
        "lab_schema_install",
        "catalog_prepare",
        "catalog_load",
        "index_creation",
        "premium_cohort_load",
        "evidence_load",
        "corpus_lexeme_seed",
        "smoke_test",
        "bootstrap_acceptance",
    ]
    lines = [f"{name}\t{10 + index}" for index, name in enumerate(phase_names)]
    lines.append(f"total\t{sum(10 + index for index in range(len(phase_names)))}")
    timings_path = tmp_path / "bootstrap-timings.tsv"
    timings_path.write_text("\n".join(lines) + "\n")
    import_bootstrap_timings(manifest, timings_path, started_at=None, ended_at=None)

    upsert_stage(
        manifest,
        "catalog_restore_verification",
        status="passed",
        detail="500000 products, 500000 vectors, 120 premium, evidence present",
        started_at="2026-01-01T00:10:00+00:00",
        ended_at="2026-01-01T00:15:00+00:00",
    )

    for lab in (1, 2, 3):
        upsert_stage(
            manifest,
            f"lab_{lab}_rehearsal",
            status="passed",
            detail=f"lab {lab}: reset isolated, solution applied, validate-lab-{lab} PASS",
        )

    reranker_client = _mock_client(
        {
            "/api/search": (
                200,
                {
                    "diagnostics": {
                        "rerank_status": "applied",
                        "rerank_model_id": "cohere.rerank-v3.5",
                        "stage_timings_ms": {"rerank": 118.0},
                        "total_latency_ms": 420,
                    }
                },
            )
        }
    )
    try:
        for condition in ("cold", "warm"):
            record_cold_warm(
                manifest,
                target="reranker",
                condition=condition,
                api_url="http://workshop-host",
                question=None,
                timeout=5.0,
                client=reranker_client,
            )
    finally:
        reranker_client.close()

    ask_mosaic_client = _mock_client(
        {
            "/api/agent/answer": (
                200,
                {
                    "outcome": "grounded",
                    "trace": [{"tool": "search_products"}],
                    "citations": [{"product_id": 1}],
                    "recommendations": [{"product_id": 1}],
                },
            )
        }
    )
    try:
        for condition in ("cold", "warm"):
            record_cold_warm(
                manifest,
                target="ask_mosaic",
                condition=condition,
                api_url="http://workshop-host",
                question=None,
                timeout=5.0,
                client=ask_mosaic_client,
            )
    finally:
        ask_mosaic_client.close()

    for device in ("laptop", "tablet", "mobile", "projector"):
        record_layout(
            manifest, device=device, status="ok", detail=f"{device} looked fine"
        )

    compute_timing_summary(manifest)
    return manifest


def test_a_fully_populated_manifest_reaches_complete_overall_status(tmp_path):
    """Red before the fix (finding 1): without capture_identity's timestamps,
    deployment_seconds stayed null, timing_summary never passed, and this
    manifest's overall_status stuck at "in_progress" after a perfect rehearsal."""
    manifest = _fully_rehearsed_manifest(tmp_path)
    assert validate_manifest(manifest) == []
    assert compute_overall_status(manifest) == "complete"


def test_a_manifest_without_first_query_ms_is_not_complete(tmp_path):
    """Red before the fix (finding 2): first-query had no field anywhere, so a
    manifest missing it looked identical to one that recorded it."""
    manifest = _fully_rehearsed_manifest(tmp_path, include_first_query=False)
    assert manifest["stages"]["timing_summary"]["rollup"]["first_query_ms"] is None
    assert manifest["stages"]["timing_summary"]["status"] != "passed"
    assert compute_overall_status(manifest) != "complete"


def test_record_cold_warm_needs_both_conditions_before_passing():
    manifest = new_manifest()
    client = _mock_client(
        {
            "/api/search": (
                200,
                {
                    "search_event_id": "x",
                    "query": "q",
                    "normalized_query": "q",
                    "applied_filters": {},
                    "results": [],
                    "diagnostics": {
                        "rerank_status": "applied",
                        "rerank_model_id": "cohere.rerank-v3.5",
                        "stage_timings_ms": {"rerank": 118.0},
                        "total_latency_ms": 420,
                    },
                },
            )
        }
    )
    try:
        record_cold_warm(
            manifest,
            target="reranker",
            condition="cold",
            api_url="http://workshop-host",
            question=None,
            timeout=5.0,
            client=client,
        )
        stage = manifest["stages"]["reranker_cold_warm"]
        assert stage["status"] == "skipped"
        assert stage["cold"]["rerank_status"] == "applied"
        assert stage["warm"] is None

        record_cold_warm(
            manifest,
            target="reranker",
            condition="warm",
            api_url="http://workshop-host",
            question=None,
            timeout=5.0,
            client=client,
        )
    finally:
        client.close()
    stage = manifest["stages"]["reranker_cold_warm"]
    assert stage["status"] == "passed"
    assert stage["cold"] is not None and stage["warm"] is not None


def test_record_cold_warm_for_ask_mosaic_records_tool_trace_shape():
    manifest = new_manifest()
    client = _mock_client(
        {
            "/api/agent/answer": (
                200,
                {
                    "agent_run_id": "00000000-0000-4000-8000-000000000001",
                    "question": "q",
                    "answer": "a",
                    "plan": [],
                    "recommendations": [{"product_id": 1}],
                    "citations": [{"product_id": 1}],
                    "trace": [
                        {"tool": "search_products"},
                        {"tool": "get_product_evidence"},
                    ],
                    "outcome": "grounded",
                },
            )
        }
    )
    try:
        record_cold_warm(
            manifest,
            target="ask_mosaic",
            condition="cold",
            api_url="http://workshop-host",
            question=None,
            timeout=5.0,
            client=client,
        )
    finally:
        client.close()
    record = manifest["stages"]["ask_mosaic_cold_warm"]["cold"]
    assert record["outcome"] == "grounded"
    assert record["tool_call_count"] == 2
    assert record["tool_names"] == ["search_products", "get_product_evidence"]


def test_record_cold_warm_raises_on_a_server_error_without_recording_a_fake_pass():
    manifest = new_manifest()
    client = _mock_client({"/api/search": (503, {"detail": "database is not ready"})})
    try:
        with pytest.raises(RehearsalError):
            record_cold_warm(
                manifest,
                target="reranker",
                condition="cold",
                api_url="http://workshop-host",
                question=None,
                timeout=5.0,
                client=client,
            )
    finally:
        client.close()
    assert manifest["stages"]["reranker_cold_warm"]["status"] == "not_started"


def test_record_layout_requires_all_four_devices_to_pass():
    manifest = new_manifest()
    for device in ("laptop", "tablet", "mobile"):
        record_layout(
            manifest, device=device, status="ok", detail=f"{device} looked fine"
        )
        assert manifest["stages"]["layout_walkthrough"]["status"] == "skipped"
    record_layout(
        manifest, device="projector", status="ok", detail="legible from the back row"
    )
    assert manifest["stages"]["layout_walkthrough"]["status"] == "passed"


def test_record_layout_fails_on_a_reported_issue():
    manifest = new_manifest()
    for device in ("laptop", "tablet", "mobile", "projector"):
        record_layout(
            manifest,
            device=device,
            status="issue" if device == "mobile" else "ok",
            detail="x",
        )
    stage = manifest["stages"]["layout_walkthrough"]
    assert stage["status"] == "failed"
    assert "mobile" in stage["detail"]


def test_compute_timing_summary_derives_from_recorded_stages_only():
    manifest = new_manifest()
    upsert_stage(
        manifest,
        "bootstrap_phases",
        status="passed",
        detail="ok",
        extra={
            "phases": [{"name": "index_creation", "elapsed_seconds": 94.0}],
            "total_elapsed_seconds": 500.0,
        },
    )
    compute_timing_summary(manifest)
    rollup = manifest["stages"]["timing_summary"]["rollup"]
    assert rollup["index_creation_seconds"] == 94.0
    assert rollup["bootstrap_total_seconds"] == 500.0
    assert manifest["stages"]["timing_summary"]["status"] == "skipped"


def test_cli_init_then_validate_round_trips(tmp_path):
    manifest_path = tmp_path / "evidence.json"
    assert (
        main(["init", "--output", str(manifest_path), "--operator", "facilitator"]) == 0
    )
    assert main(["validate", "--manifest", str(manifest_path)]) == 0
    on_disk = json.loads(manifest_path.read_text())
    assert on_disk["schema_version"] == 1
    assert set(on_disk["stages"]) == set(REQUIRED_STAGES)


def test_cli_record_stage_then_summary(tmp_path, capsys):
    manifest_path = tmp_path / "evidence.json"
    main(["init", "--output", str(manifest_path)])
    exit_code = main(
        [
            "record-stage",
            "--manifest",
            str(manifest_path),
            "--stage",
            "archive_transfer_and_join",
            "--status",
            "passed",
            "--detail",
            "3 parts synced and joined; sha256 matched db/config/real-catalog-cache.json",
        ]
    )
    assert exit_code == 0
    capsys.readouterr()
    main(["summary", "--manifest", str(manifest_path)])
    out = capsys.readouterr().out
    assert "archive_transfer_and_join" in out
    assert "PENDING RUNTIME VERIFICATION" in out


def test_cli_validate_reports_failure_on_a_hand_edited_secret(tmp_path):
    manifest_path = tmp_path / "evidence.json"
    main(["init", "--output", str(manifest_path)])
    manifest = json.loads(manifest_path.read_text())
    manifest["stages"]["deployment_identity"]["status"] = "passed"
    manifest["stages"]["deployment_identity"]["detail"] = (
        "postgresql://mosaic:leaked@cluster.example.amazonaws.com:5432/mosaic"
    )
    manifest_path.write_text(json.dumps(manifest))

    assert main(["validate", "--manifest", str(manifest_path)]) == 1
