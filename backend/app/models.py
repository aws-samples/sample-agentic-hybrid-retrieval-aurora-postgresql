from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RetrievalMode = Literal["hybrid", "semantic", "lexical", "fuzzy"]
EvidenceKind = Literal[
    "incident",
    "change",
    "support_case",
    "runbook",
    "lock_evidence",
    "commitment",
    "postmortem",
]
IterativeScanMode = Literal["off", "strict_order", "relaxed_order"]


def workshop_principal() -> dict[str, Any]:
    return {"scopes": ["workshop"], "principals": []}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kinds: list[EvidenceKind] | None = None
    cluster_id: str | None = None
    incident_id: str | None = None
    account_name: str | None = None
    severities: list[str] | None = None
    environment: str | None = None
    service_name: str | None = None
    engine_version: str | None = None
    aws_region: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    limit: int = Field(8, ge=1, le=50)
    mode: RetrievalMode = "hybrid"
    candidate_pool: int = Field(24, ge=8, le=2000)
    rrf_k: int = Field(60, ge=1, le=1000)
    w_text: float = Field(2.0, ge=0.0, le=10.0)
    w_vector: float = Field(1.0, ge=0.0, le=10.0)
    w_trgm: float = Field(1.0, ge=0.0, le=10.0)
    fuzzy_threshold: float = Field(0.3, ge=0.1, le=1.0)
    ef_search: int = Field(40, ge=1, le=1000)
    iterative_scan: IterativeScanMode = "strict_order"
    rerank: bool | None = None
    principal: dict[str, Any] = Field(default_factory=workshop_principal)


class AgentAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    kinds: list[EvidenceKind] | None = None
    cluster_id: str | None = None
    incident_id: str | None = None
    account_name: str | None = None
    severities: list[str] | None = None
    environment: str | None = None
    service_name: str | None = None
    engine_version: str | None = None
    aws_region: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    limit: int = Field(8, ge=1, le=20)
    candidate_pool: int = Field(24, ge=8, le=2000)
    rrf_k: int = Field(60, ge=1, le=1000)
    w_text: float = Field(2.0, ge=0.0, le=10.0)
    w_vector: float = Field(1.0, ge=0.0, le=10.0)
    w_trgm: float = Field(1.0, ge=0.0, le=10.0)
    fuzzy_threshold: float = Field(0.3, ge=0.1, le=1.0)
    ef_search: int = Field(40, ge=1, le=1000)
    iterative_scan: IterativeScanMode = "strict_order"
    rerank: bool = False
    max_tool_calls: int = Field(12, ge=1, le=50)
    max_escalations: int = Field(2, ge=0, le=10)
    principal: dict[str, Any] = Field(default_factory=workshop_principal)


class DecomposeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class TraverseRequest(BaseModel):
    seed_external_keys: list[str] = Field(min_length=1, max_length=20)
    max_depth: int = Field(2, ge=0, le=8)
    principal: dict[str, Any] = Field(default_factory=workshop_principal)


class CompareRequest(BaseModel):
    external_keys: list[str] = Field(min_length=1, max_length=20)
    principal: dict[str, Any] = Field(default_factory=workshop_principal)


class SynthesisRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    run_ids: list[str] = Field(min_length=1, max_length=20)
    limit: int = Field(8, ge=1, le=8)


class ExplainRankingRequest(BaseModel):
    run_id: str = Field(min_length=36, max_length=36)


class EvaluationRequest(BaseModel):
    modes: list[RetrievalMode] | None = None
    limit: int = Field(10, ge=1, le=50)


class QueryPlanRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    arm: Literal["semantic", "lexical", "fuzzy"] = "semantic"
    limit: int = Field(10, ge=1, le=50)
    cluster_id: str | None = None
    kinds: list[EvidenceKind] | None = None
    principal: dict[str, Any] = Field(default_factory=workshop_principal)
