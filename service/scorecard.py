"""Read-only Prove-step surface: the committed canonical evaluation artifact.

Ruling R7 in
`docs/superpowers/specs/2026-08-27-prove-and-package-architecture.md` is
explicit: this module reads a file artifact and gains no `eval_run` table.
Every number below comes from `data/evals/canonical_scorecard.json`,
`data/evals/canonical_queries.jsonl`, `service/assertions.py`, or the live
tool-contract registry. Nothing here recomputes retrieval quality, reruns the
canonical evaluation, or queries Aurora.

Four sections, matched to the spec's ruling that they must never be conflated:

    A. retrieval_quality       population IR metrics, gated on provenance
    B. regression_anchors      compact PASS/total over golden anchors
    C. eligibility_contracts   hard eligibility/filter fixtures, not relevance
    D. agent_contracts         deterministic agent/evidence guarantees

Section A is withheld entirely when `ScorecardProvenance.attributed` is false.
B and C still render their data -- the counts and fixture ids are real -- but
they must not claim present-tense verification, because both derive from an
artifact measured at one revision:

  * B's `passed` can only equal the number of checks the artifact recorded.
    `scripts.score_evals.validate_release_checks` raises on the first failure
    and never writes a failing entry, so a written artifact always reads N/N.
    `verified_for_running_revision` carries whether that N/N describes the
    running code.
  * C's `held` is `True` only while attributed, `None` otherwise. It was
    previously the literal `True`, which made the section incapable of ever
    reporting a problem.

D is genuinely revision-independent: it resolves assertions and tool contracts
from the running code, not from the artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.eval_contract import load_evaluation_queries
from scripts.retrieval_profile import explain
from scripts.score_evals import (
    product_retrieval_queries,
    query_set_sha256,
    scored_query_set_sha256,
)
from scripts.tool_contracts import contracts_for_surface
from service.assertions import ASSERTIONS
from service.config import get_settings
from service.models import (
    RetrievalScorecardResponse,
    ScorecardAgentContractGuarantee,
    ScorecardAgentContracts,
    ScorecardCandidateRecallCeiling,
    ScorecardEligibilityContracts,
    ScorecardGoldenAnchor,
    ScorecardProvenance,
    ScorecardRegressionAnchors,
    ScorecardRetrievalQuality,
    ScorecardStageAblation,
    ScorecardStageAblationQuery,
    ScorecardStageArm,
)
from service.retrieval_fingerprint import (
    compute_ablation_methodology_sha256,
    compute_live_retrieval_settings_sha256,
    compute_retrieval_fingerprint,
    compute_scorecard_methodology_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
SCORECARD_ARTIFACT = ROOT / "data" / "evals" / "canonical_scorecard.json"
STAGE_ABLATION_ARTIFACT = ROOT / "data" / "evals" / "canonical_stage_ablation.json"
CANONICAL_QUERIES = ROOT / "data" / "evals" / "canonical_queries.jsonl"

METRIC_EXPLANATIONS: dict[str, str] = {
    "recall": (
        "Of the products graded relevant for a search, the share that appeared "
        "anywhere in the top 10."
    ),
    "mrr": (
        "How high the first relevant product landed, averaged across the "
        "sample. A score of 1.0 means it was always first."
    ),
    "ndcg": (
        "How well the top 10 are ordered once relevance has grades, not just "
        "whether a relevant product is present somewhere in the list."
    ),
}

SAMPLE_DESCRIPTION = (
    "A hand-built set of test searches, each with products graded as right or "
    "wrong answers, including look-alike wrong answers. Written to trigger "
    "every failure the labs teach, not to stand in for the whole "
    "500,000-product catalog."
)

ELIGIBILITY_DESCRIPTION = (
    "Each check names one product that must never appear for one test "
    "search: a near-identical or plainly ineligible item, such as a "
    "refurbished sibling, the wrong model, or a product outside the price or "
    "attribute filter, no matter how similar it looks. These are pass-or-fail "
    "checks, kept separate from the search-quality scores. The scoring script "
    "refuses to save its results if any check fails, so the saved results "
    "existing is the pass record for every check below."
)

# Which real `service.assertions` names back each of the five deterministic
# agent/evidence guarantees named in the Prove step (spec section 7-10, part
# D). Every name here must resolve through `service.assertions.ASSERTIONS`;
# `retrieval_scorecard()` fails closed if one does not, so this mapping cannot
# silently drift from the vocabulary it describes.
_AGENT_CONTRACT_ASSERTIONS: dict[str, list[str]] = {
    "retrieval_scope": ["retrieval_tool_called", "expected_products_considered"],
    "compare_boundary": ["comparison_tool_called", "recommendation_grounded"],
    "evidence_authorization": ["evidence_tool_called", "evidence_records_returned"],
    "citation_resolution": [
        "citations_present",
        "citation_ids_resolve",
        "citation_source_revision_present",
    ],
    "tool_contract": ["structured_constraints_extracted"],
}

_AGENT_CONTRACT_LABELS: dict[str, str] = {
    "retrieval_scope": "Only what search returned",
    "compare_boundary": "Comparisons stay inside the shortlist",
    "evidence_authorization": "Evidence is registered before it is cited",
    "citation_resolution": "Every citation resolves to a record",
    "tool_contract": "Every tool call is checked",
}

_AGENT_CONTRACT_DESCRIPTIONS: dict[str, str] = {
    "retrieval_scope": (
        "The agent may only act on products its own searches returned. The "
        "server enforces that window, so a wider request from the model "
        "cannot reach past it."
    ),
    "compare_boundary": (
        "A comparison cannot widen past the shortlist the search already "
        "produced; the compare step is held to the same window as evidence "
        "and citations."
    ),
    "evidence_authorization": (
        "Evidence the model has seen is not automatically usable in an "
        "answer. It must be registered by a successful evidence lookup "
        "before the answer may cite it; otherwise the answer is refused."
    ),
    "citation_resolution": (
        "Every citation the agent returns must point at a real evidence "
        "record for the cited product, with the version it came from, so the "
        "claim can be checked against the row that produced it."
    ),
    "tool_contract": (
        "Every tool call is checked against a registered, versioned "
        "definition rather than a free-form instruction, and the shopper's "
        "constraints must survive into that call."
    ),
}


def _load_artifact() -> dict[str, Any]:
    """Read the committed canonical scorecard, refusing to fabricate one."""
    if not SCORECARD_ARTIFACT.exists():
        raise FileNotFoundError(
            explain(
                f"no canonical scorecard at {SCORECARD_ARTIFACT}",
                "run `.venv/bin/python scripts/score_evals.py --write-baseline` "
                "against Aurora after reviewing measured ranks",
            )
        )
    return json.loads(SCORECARD_ARTIFACT.read_text(encoding="utf-8"))


def _load_stage_ablation_artifact() -> dict[str, Any]:
    """Read the committed stage-ablation artifact, refusing to fabricate one.

    A separate file from `SCORECARD_ARTIFACT`: section E decomposes the same
    served-path quality section A reports into semantic-only, RRF-fused, and
    RRF-fused-plus-reranked, and that measurement (`scripts/ablation_evals.py`)
    is its own run against Aurora, not a re-label of section A's numbers.
    """
    if not STAGE_ABLATION_ARTIFACT.exists():
        raise FileNotFoundError(
            explain(
                f"no stage ablation artifact at {STAGE_ABLATION_ARTIFACT}",
                "run `.venv/bin/python scripts/ablation_evals.py` against "
                "Aurora after reviewing measured ranks",
            )
        )
    return json.loads(STAGE_ABLATION_ARTIFACT.read_text(encoding="utf-8"))


def _scored_queries() -> list[dict[str, Any]]:
    """The product-retrieval population the artifact's metrics were scored over."""
    queries = load_evaluation_queries(CANONICAL_QUERIES)
    scored, _excluded = product_retrieval_queries(queries)
    return scored


def _eligibility_fixtures(scored: list[dict[str, Any]]) -> list[str]:
    """Query ids carrying at least one hard-negative eligibility fixture."""
    return [query["query_id"] for query in scored if query.get("hard_negative_ids")]


def _release_check_total(scored: list[dict[str, Any]]) -> int:
    """Every release check declared in the query set, not just the ones that ran."""
    return sum(len(query.get("release_checks") or []) for query in scored)


#: The exact participant-facing pending string, owner-specified verbatim.
#: `attribution_note` carries additional detail for the disclosure below it;
#: the UI must render this constant unmodified as the headline, not a
#: paraphrase of it.
PENDING_TEXT = "Metrics pending evaluation for this retrieval revision"

#: What this artifact is. The canonical scorecard is a maintainers' release
#: baseline measured against Aurora at one revision, not the attendee's own
#: proof of the retrieval they just ran. Naming that on the wire keeps the
#: surface from implying a live measurement it never performs.
ARTIFACT_KIND = "release_baseline"


@dataclass(frozen=True)
class _CurrentRetrievalIdentity:
    """What the running service reports, compared against the artifact's own
    record. Every field here has a same-named counterpart already stored on
    the artifact; none of this is new state, only a fresh read of it."""

    retrieval_fingerprint: str
    embedding_model_id: str
    rerank_model_id: str
    query_set_sha256: str
    scored_query_set_sha256: str
    #: How the scorecard is measured and served, held apart from what retrieval
    #: does. A mismatch marks section A pending until the scorecard is
    #: re-measured; it cannot be cleared by replaying historical output.
    scorecard_methodology_sha256: str
    #: The superset covering the ablation harness too. Section E reads this one,
    #: so an ablation-only edit leaves section A attributed.
    ablation_methodology_sha256: str
    #: The resolved retrieval settings, which no file hash can see: `RRF_K`,
    #: `FTS_CANDIDATE_LIMIT`, `HNSW_EF_SEARCH` and the rest are read from the
    #: environment ahead of `db/config/retrieval.yaml`, so `RRF_K=1` changes
    #: every served result with the retrieval fingerprint sitting still.
    retrieval_settings_sha256: str


def _attribution(
    artifact: dict[str, Any],
    current: _CurrentRetrievalIdentity,
    *,
    methodology_key: str = "scorecard_methodology_sha256",
    methodology_expected: str | None = None,
) -> tuple[bool, str]:
    """Decide whether the artifact's metrics describe the running system.

    A strict revision equality (`artifact_revision == current_revision`) can
    never hold: `scripts/score_evals.py` records the source revision *before*
    the artifact it writes is committed, so committing the artifact always
    advances HEAD one commit past what was measured. That gate would read
    "pending" forever. See `service.retrieval_fingerprint` for the full
    argument and the manifest of files it hashes in its place.

    Binding conjunction over exactly five facts, in the order they are
    checked:

        artifact.retrieval_fingerprint == current retrieval fingerprint
        AND artifact.source.worktree_dirty == False
        AND the pinned evaluation inputs and models still match:
            artifact.models.embedding        == current embedding model id
            artifact.models.rerank           == current rerank model id
            artifact.query_set_sha256        == current query_set_sha256
            artifact.scored_query_set_sha256 == current scored_query_set_sha256
        AND artifact.<methodology_key> == the methodology hash resolved now
        AND artifact.retrieval_settings_sha256 == the settings resolved now
            -> show the metrics
        otherwise
            -> withhold them, with `PENDING_TEXT`

    The settings clause is not redundant with the fingerprint.
    `scripts/retrieval_profile._resolve` reads the environment ahead of
    `db/config/retrieval.yaml`, so `RRF_K=1` changes every served result while
    every fingerprinted file stays byte-identical. Without this clause that
    configuration serves an attributed scorecard measured under different
    settings.

    Nothing about the *current* server's own worktree cleanliness enters this
    decision -- only the artifact's own recorded `worktree_dirty` at
    measurement time does. `current_source_worktree_dirty` is still carried on
    `ScorecardProvenance` for inspection, but does not gate `attributed`, and
    neither does `source_revision`: both stay as display and audit evidence,
    not as the gate.
    """
    source = artifact.get("source") or {}
    artifact_fingerprint = artifact.get("retrieval_fingerprint") or None
    artifact_dirty = source.get("worktree_dirty")
    artifact_models = artifact.get("models") or {}

    fingerprint_matches = (
        bool(artifact_fingerprint)
        and artifact_fingerprint == current.retrieval_fingerprint
    )
    measured_clean = artifact_dirty is False
    models_match = (
        artifact_models.get("embedding") == current.embedding_model_id
        and artifact_models.get("rerank") == current.rerank_model_id
    )
    query_set_matches = (
        artifact.get("query_set_sha256") == current.query_set_sha256
        and artifact.get("scored_query_set_sha256") == current.scored_query_set_sha256
    )
    inputs_match = models_match and query_set_matches
    # Section A reads the scorecard methodology; section E reads its own, which
    # is a superset. That split is the point: editing scripts/ablation_evals.py
    # must not unattribute canonical retrieval metrics.
    expected_methodology = (
        methodology_expected
        if methodology_expected is not None
        else current.scorecard_methodology_sha256
    )
    artifact_methodology = artifact.get(methodology_key) or None
    methodology_matches = (
        bool(artifact_methodology) and artifact_methodology == expected_methodology
    )
    artifact_settings = artifact.get("retrieval_settings_sha256") or None
    settings_match = (
        bool(artifact_settings)
        and artifact_settings == current.retrieval_settings_sha256
    )

    if (
        fingerprint_matches
        and measured_clean
        and inputs_match
        and methodology_matches
        and settings_match
    ):
        return True, (
            "Measured on the retrieval code running now "
            f"({artifact_fingerprint[:12]}), with the same models and the same "
            "test searches."
        )

    reasons: list[str] = []
    if not fingerprint_matches:
        if not artifact_fingerprint:
            reasons.append(
                "no record of the retrieval code version was saved when this was "
                "measured"
            )
        else:
            reasons.append(
                f"the retrieval code changed since it was measured "
                f"({artifact_fingerprint[:12]} measured, "
                f"{current.retrieval_fingerprint[:12]} running)"
            )
    if not measured_clean:
        reasons.append("the measurement was taken with uncommitted changes")
    if not models_match:
        reasons.append("the embedding or rerank model changed")
    if not query_set_matches:
        reasons.append("the test searches or their grades changed")
    if not methodology_matches:
        reasons.append(
            "no measurement methodology hash was recorded"
            if not artifact_methodology
            else (
                f"the measurement methodology changed "
                f"({artifact_methodology[:12]} measured, "
                f"{expected_methodology[:12]} running)"
            )
        )
    if not settings_match:
        reasons.append(
            "no retrieval settings hash was recorded when this artifact was measured"
            if not artifact_settings
            else (
                f"the live retrieval settings changed "
                f"({artifact_settings[:12]} measured, "
                f"{current.retrieval_settings_sha256[:12]} running)"
            )
        )

    # Pending is resolved by re-measuring, never by replaying historical output.
    # An earlier design let a methodology mismatch be "recertified" from the
    # persisted CSV; an audit showed that falsely restores attribution, because a
    # behaviour-affecting change leaves old output untouched and therefore
    # reproducible. The ablation's re-measure spends no reranker calls, so only
    # the scorecard's costs anything.
    remedy = (
        "Rerun scripts/score_evals.py --write-baseline once the change is "
        "reviewed, then commit the regenerated artifact."
    )
    return False, f"{PENDING_TEXT}: " + "; ".join(reasons) + f". {remedy}"


def _retrieval_quality(
    artifact: dict[str, Any],
    scored: list[dict[str, Any]],
) -> ScorecardRetrievalQuality:
    k = artifact["k"]
    metrics = artifact["metrics"]
    sample_size = artifact["product_retrieval_query_count"]
    if sample_size != len(scored):
        raise ValueError(
            explain(
                f"data/evals/canonical_queries.jsonl now scores {len(scored)} "
                f"product_retrieval queries but the committed artifact recorded "
                f"{sample_size}",
                "regenerate data/evals/canonical_scorecard.json with "
                "scripts/score_evals.py --write-baseline before trusting this "
                "artifact's population metrics",
            )
        )
    representative_products: dict[str, int] = {}
    for query in scored:
        judgments = query.get("judgments") or []
        if not judgments:
            raise ValueError(
                explain(
                    f"{query['query_id']} has no relevance judgments",
                    "add at least one graded judgment to "
                    "data/evals/canonical_queries.jsonl",
                )
            )
        highest_grade = max(int(judgment["grade"]) for judgment in judgments)
        representative_products[query["query_id"]] = next(
            int(judgment["product_id"])
            for judgment in judgments
            if int(judgment["grade"]) == highest_grade
        )

    per_query_metrics: list[dict[str, Any]] = []
    for recorded in artifact["per_query_metrics"]:
        row = dict(recorded)
        query_id = row.get("query_id")
        if query_id not in representative_products:
            raise ValueError(
                explain(
                    f"scorecard row {query_id!r} has no canonical query",
                    "regenerate data/evals/canonical_scorecard.json from "
                    "data/evals/canonical_queries.jsonl",
                )
            )
        row["representative_product_id"] = representative_products[query_id]
        per_query_metrics.append(row)

    return ScorecardRetrievalQuality(
        sample_size=sample_size,
        canonical_query_count=artifact["canonical_query_count"],
        sample_description=SAMPLE_DESCRIPTION,
        recall_at_10=metrics[f"recall@{k}"],
        mrr=metrics["mrr"],
        ndcg_at_10=metrics[f"ndcg@{k}"],
        metric_explanations={
            f"recall@{k}": METRIC_EXPLANATIONS["recall"],
            "mrr": METRIC_EXPLANATIONS["mrr"],
            f"ndcg@{k}": METRIC_EXPLANATIONS["ndcg"],
        },
        excluded_agent_contract_query_ids=list(
            artifact["excluded_agent_contract_queries"]
        ),
        per_query_metrics=per_query_metrics,
    )


def _regression_anchors(
    artifact: dict[str, Any],
    scored: list[dict[str, Any]],
    *,
    attributed: bool,
) -> ScorecardRegressionAnchors:
    checks = artifact["deterministic_release_checks"]
    return ScorecardRegressionAnchors(
        passed=len(checks),
        total=_release_check_total(scored),
        anchors=[ScorecardGoldenAnchor.model_validate(check) for check in checks],
        verified_for_running_revision=attributed,
    )


def _eligibility_contracts(
    scored: list[dict[str, Any]],
    *,
    attributed: bool,
) -> ScorecardEligibilityContracts:
    fixtures = _eligibility_fixtures(scored)
    return ScorecardEligibilityContracts(
        fixture_count=len(fixtures),
        # Not a literal. `scripts.score_evals.validate_hard_negatives` raises
        # when a graded-0 product reaches the result window, so an artifact
        # cannot exist for a run that violated a contract -- which is what
        # justifies True. That justification covers the revision measured, not
        # whatever is running now, so a provenance mismatch makes this unknown.
        held=True if attributed else None,
        description=ELIGIBILITY_DESCRIPTION,
        fixture_query_ids=fixtures,
    )


def _agent_contracts() -> ScorecardAgentContracts:
    tool_contract_count = len(contracts_for_surface("agent"))
    guarantees: list[ScorecardAgentContractGuarantee] = []
    for key, assertion_names in _AGENT_CONTRACT_ASSERTIONS.items():
        unknown = [name for name in assertion_names if name not in ASSERTIONS]
        if unknown:
            raise ValueError(
                explain(
                    f"agent contract {key!r} names unresolved assertions {unknown}",
                    "add them to service.assertions.ASSERTIONS or fix this mapping",
                )
            )
        guarantees.append(
            ScorecardAgentContractGuarantee(
                key=key,  # type: ignore[arg-type]
                label=_AGENT_CONTRACT_LABELS[key],
                description=_AGENT_CONTRACT_DESCRIPTIONS[key],
                assertion_names=assertion_names,
                falsifiers=[ASSERTIONS[name].falsifier for name in assertion_names],
                fixture_count=tool_contract_count if key == "tool_contract" else None,
            )
        )
    return ScorecardAgentContracts(guarantees=guarantees)


def _stage_ablation(
    artifact: dict[str, Any],
    current: _CurrentRetrievalIdentity,
) -> ScorecardStageAblation:
    """Project the committed ablation artifact into section E.

    Reuses `_attribution` against the *same* running-system identity section
    A is judged against: the ablation is withheld with the same
    `PENDING_TEXT` whenever the retrieval fingerprint, models, or query set
    it was measured against no longer match what is running, exactly as
    section A is.
    """
    attributed, attribution_note = _attribution(
        artifact,
        current,
        methodology_key="ablation_methodology_sha256",
        methodology_expected=current.ablation_methodology_sha256,
    )
    arms = [
        ScorecardStageArm(
            key=key,
            label=values["label"],
            description=values["description"],
            recall_at_10=values["recall@10"],
            mrr=values["mrr"],
            ndcg_at_10=values["ndcg@10"],
            ndcg_at_10_min=values["ndcg@10_min"],
            ndcg_at_10_max=values["ndcg@10_max"],
            ndcg_at_10_stdev=values["ndcg@10_stdev"],
            ndcg_at_10_query_wins=values["ndcg@10_query_wins"],
        )
        for key, values in artifact["arms"].items()
    ]
    per_query = [
        ScorecardStageAblationQuery(
            query_id=row["query_id"],
            query_text=row["query_text"],
            ndcg_at_10=row["ndcg@10"],
            pool_recall=row["pool_recall"],
            relevant_count=row["relevant_count"],
            found_in_pool=row["found_in_pool"],
            missed_product_ids=row["missed_product_ids"],
        )
        for row in artifact["per_query"]
    ]
    return ScorecardStageAblation(
        attributed=attributed,
        attribution_note=attribution_note,
        measured_at=artifact["measured_at"],
        spread_note=artifact["spread_note"],
        scored_query_count=artifact["scored_query_count"],
        arms=arms,
        candidate_recall_ceiling=ScorecardCandidateRecallCeiling.model_validate(
            artifact["candidate_recall_ceiling"]
        ),
        per_query=per_query,
    )


def retrieval_scorecard() -> RetrievalScorecardResponse:
    """Assemble the Prove-step scorecard from the committed artifact."""
    artifact = _load_artifact()
    ablation_artifact = _load_stage_ablation_artifact()
    scored = _scored_queries()
    settings = get_settings()
    artifact_source = artifact.get("source") or {}
    current = _CurrentRetrievalIdentity(
        retrieval_fingerprint=compute_retrieval_fingerprint(),
        embedding_model_id=settings.embedding_model_id,
        rerank_model_id=settings.rerank_model_id,
        query_set_sha256=query_set_sha256(CANONICAL_QUERIES),
        scored_query_set_sha256=scored_query_set_sha256(scored),
        scorecard_methodology_sha256=compute_scorecard_methodology_sha256(),
        ablation_methodology_sha256=compute_ablation_methodology_sha256(),
        retrieval_settings_sha256=compute_live_retrieval_settings_sha256(),
    )
    attributed, attribution_note = _attribution(artifact, current)
    provenance = ScorecardProvenance(
        artifact_kind=ARTIFACT_KIND,
        served_at=datetime.now(UTC),
        measured_at=artifact["measured_at"],
        query_set=artifact["query_set"],
        query_set_sha256=artifact["query_set_sha256"],
        scored_query_set_sha256=artifact["scored_query_set_sha256"],
        ranked_result_sha256=artifact["ranked_result_sha256"],
        dataset_manifest_sha256=artifact["dataset_manifest_sha256"],
        models=dict(artifact["models"]),
        aurora_configuration=dict(artifact["aurora_configuration"]),
        hnsw_settings=dict(artifact["hnsw_settings"]),
        retrieval_profile=dict(artifact["retrieval_profile"]),
        retrieval_settings_sha256=artifact.get("retrieval_settings_sha256"),
        retrieval_fingerprint=artifact.get("retrieval_fingerprint") or None,
        database_instance_id=artifact["database_instance_id"],
        strategy=artifact["strategy"],
        source_revision=artifact_source.get("revision"),
        source_worktree_dirty=artifact_source.get("worktree_dirty"),
        current_source_revision=settings.source_revision,
        current_source_worktree_dirty=settings.source_worktree_dirty,
        current_retrieval_settings_sha256=current.retrieval_settings_sha256,
        attributed=attributed,
        attribution_note=attribution_note,
    )
    return RetrievalScorecardResponse(
        provenance=provenance,
        retrieval_quality=_retrieval_quality(artifact, scored),
        regression_anchors=_regression_anchors(artifact, scored, attributed=attributed),
        eligibility_contracts=_eligibility_contracts(scored, attributed=attributed),
        agent_contracts=_agent_contracts(),
        stage_ablation=_stage_ablation(ablation_artifact, current),
    )
