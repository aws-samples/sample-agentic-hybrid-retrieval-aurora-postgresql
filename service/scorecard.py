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
from service.retrieval_fingerprint import compute_retrieval_fingerprint

ROOT = Path(__file__).resolve().parents[1]
SCORECARD_ARTIFACT = ROOT / "data" / "evals" / "canonical_scorecard.json"
STAGE_ABLATION_ARTIFACT = ROOT / "data" / "evals" / "canonical_stage_ablation.json"
CANONICAL_QUERIES = ROOT / "data" / "evals" / "canonical_queries.jsonl"

METRIC_EXPLANATIONS: dict[str, str] = {
    "recall": (
        "Of the products graded relevant for a query, the share retrieved "
        "anywhere in the top-k window."
    ),
    "mrr": (
        "Mean Reciprocal Rank: how early the first relevant result appears, "
        "averaged across the sample."
    ),
    "ndcg": (
        "Normalized Discounted Cumulative Gain: how well the top-k results "
        "are ordered once relevance differs by grade, not just whether a "
        "relevant product is present."
    ),
}

SAMPLE_DESCRIPTION = (
    "A curated teaching and evaluation set with hand-graded relevance "
    "judgments, hard negatives, and release checks. Built to exercise every "
    "workshop failure mode deliberately, not drawn as a statistically "
    "comprehensive benchmark of the full 500,000-product catalog."
)

ELIGIBILITY_DESCRIPTION = (
    "Each fixture names a hard-negative product for one scored query: a "
    "near-identical or explicitly ineligible item (a refurbished sibling, "
    "the wrong model identity, a price- or attribute-ineligible match) that "
    "must never reach the returned window regardless of semantic similarity. "
    "Not a relevance judgment: no Recall, MRR, or nDCG is computed over "
    "these. scripts/score_evals.py's validate_hard_negatives raises, "
    "refusing to write this artifact, if any fixture is violated, so this "
    "artifact existing is itself the pass record for every fixture below."
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
    "retrieval_scope": "Retrieval scope",
    "compare_boundary": "Compare boundary",
    "evidence_authorization": "Evidence authorization",
    "citation_resolution": "Citation resolution",
    "tool_contract": "Tool contract",
}

_AGENT_CONTRACT_DESCRIPTIONS: dict[str, str] = {
    "retrieval_scope": (
        "The agent may act only on products its own retrieval calls actually "
        "returned. service.retrieval_scope enforces the caller's authorized "
        "window server-side, so a wider request from the model cannot reach "
        "past it."
    ),
    "compare_boundary": (
        "A comparison cannot widen past the recommendation shortlist "
        "retrieval already granted; compare_products is checked against the "
        "same scope evidence and citations are."
    ),
    "evidence_authorization": (
        "Evidence visible to the model is not automatically usable in an "
        "answer. It must be registered by a successful evidence tool call "
        "before synthesis may cite it, and synthesis fails closed otherwise."
    ),
    "citation_resolution": (
        "Every citation the agent returns must resolve to a real evidence "
        "record for the cited product, with a source revision attached, so "
        "the claim can be re-checked against the row that produced it."
    ),
    "tool_contract": (
        "Every tool call is checked against a registered, versioned contract "
        "rather than an untyped model instruction; structured constraints "
        "must survive decomposition into that call."
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


def _attribution(
    artifact: dict[str, Any],
    current: _CurrentRetrievalIdentity,
) -> tuple[bool, str]:
    """Decide whether the artifact's metrics describe the running system.

    A strict revision equality (`artifact_revision == current_revision`) can
    never hold: `scripts/score_evals.py` records the source revision *before*
    the artifact it writes is committed, so committing the artifact always
    advances HEAD one commit past what was measured. That gate would read
    "pending" forever. See `service.retrieval_fingerprint` for the full
    argument and the manifest of files it hashes in its place.

    Binding conjunction over exactly three facts:

        artifact.retrieval_fingerprint == current retrieval fingerprint
        AND artifact.source.worktree_dirty == False
        AND the pinned evaluation inputs and models still match:
            artifact.models.embedding        == current embedding model id
            artifact.models.rerank           == current rerank model id
            artifact.query_set_sha256        == current query_set_sha256
            artifact.scored_query_set_sha256 == current scored_query_set_sha256
            -> show the metrics
        otherwise
            -> withhold them, with `PENDING_TEXT`

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

    if fingerprint_matches and measured_clean and inputs_match:
        return True, (
            f"Measured at retrieval fingerprint {artifact_fingerprint[:12]}, "
            "with the models and canonical query set currently running."
        )

    reasons: list[str] = []
    if not fingerprint_matches:
        if not artifact_fingerprint:
            reasons.append(
                "no retrieval fingerprint was recorded when this artifact was measured"
            )
        else:
            reasons.append(
                f"the retrieval fingerprint changed ({artifact_fingerprint[:12]} "
                f"measured, {current.retrieval_fingerprint[:12]} running)"
            )
    if not measured_clean:
        reasons.append("the measurement's own worktree was not clean")
    if not models_match:
        reasons.append("the embedding or rerank model changed")
    if not query_set_matches:
        reasons.append("the canonical query set or its judgments changed")

    return False, (
        f"{PENDING_TEXT}: " + "; ".join(reasons) + ". Rerun "
        "scripts/score_evals.py --write-baseline once the retrieval change is "
        "reviewed, then commit the regenerated artifact."
    )


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
        per_query_metrics=list(artifact["per_query_metrics"]),
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
    attributed, attribution_note = _attribution(artifact, current)
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
    )
    attributed, attribution_note = _attribution(artifact, current)
    provenance = ScorecardProvenance(
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
        database_instance_id=artifact["database_instance_id"],
        strategy=artifact["strategy"],
        source_revision=artifact_source.get("revision"),
        source_worktree_dirty=artifact_source.get("worktree_dirty"),
        current_source_revision=settings.source_revision,
        current_source_worktree_dirty=settings.source_worktree_dirty,
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
