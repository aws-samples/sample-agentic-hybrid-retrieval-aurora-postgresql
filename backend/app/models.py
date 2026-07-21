from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

RetrievalMode = Literal["hybrid", "semantic", "lexical", "fuzzy"]
SyncMode = Literal["upsert", "full"]

class SourceObject(BaseModel):
    source_system: str
    source_type: str
    external_id: str
    title: str
    url: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    owner: Optional[str] = None
    owner_team: Optional[str] = None
    account_name: Optional[str] = None
    project_key: Optional[str] = None
    component: Optional[str] = None
    environment: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    source_authority: float = 0.70
    acl: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    body: str

class IngestObjectsRequest(BaseModel):
    source_name: str = "api-ingest"
    source_system: str = "source_bundle"
    sync_mode: SyncMode = "upsert"
    sync_cursor: Dict[str, Any] = Field(default_factory=dict)
    objects: List[SourceObject]

class SearchRequest(BaseModel):
    query: str
    source_systems: Optional[List[str]] = None
    source_types: Optional[List[str]] = None
    statuses: Optional[List[str]] = None
    priorities: Optional[List[str]] = None
    project_key: Optional[str] = None
    account_name: Optional[str] = None
    component: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = Field(10, ge=1, le=50)
    # Retrieval-mode + fusion knobs — the live tradeoff clinic. `hybrid` runs the
    # fused ranker; the single-signal modes route to ops.{vector,full_text,fuzzy}
    # so a builder can watch one arm at a time (e.g. semantic-only drops the exact
    # ORION-1489 Jira hit the lexical arm surfaces).
    mode: RetrievalMode = "hybrid"
    rrf_k: int = Field(60, ge=1, le=1000)
    w_text: float = Field(1.0, ge=0.0, le=10.0)
    w_vector: float = Field(1.0, ge=0.0, le=10.0)
    w_trgm: float = Field(0.5, ge=0.0, le=10.0)
    ef_search: Optional[int] = Field(None, ge=1, le=1000)
    rerank: Optional[bool] = None
    fuzzy_threshold: float = Field(0.08, ge=0.0, le=1.0)
    # Row-level ACL context. When null, retrieval is unfiltered (the default
    # workshop audience). When set, only objects whose acl visibility is listed in
    # `clearances` are retrievable — e.g. {"clearances": ["workshop_lab", "restricted"]}
    # can see the restricted CASE-20919, while {"clearances": ["workshop_lab"]} cannot.
    # Threaded verbatim into ops.hybrid_search / vector_search / full_text_search /
    # fuzzy_match as p_principal and persisted to ops.retrieval_runs.principal.
    principal: Optional[Dict[str, Any]] = None

class AgentAnswerRequest(BaseModel):
    question: str
    source_systems: Optional[List[str]] = None
    project_key: Optional[str] = None
    account_name: Optional[str] = None
    component: Optional[str] = None
    limit: int = Field(8, ge=1, le=20)

class SourceCreateRequest(BaseModel):
    source_system: str
    source_name: str
    auth_mode: str = "api"
    config: Dict[str, Any] = Field(default_factory=dict)

class EvaluationRequest(BaseModel):
    # Which retrieval modes to score against the judged queries. Defaults to all
    # four so the leaderboard shows the per-query tradeoff (lexical wins on exact
    # IDs, semantic on paraphrase, hybrid is the robust default that never collapses).
    modes: Optional[List[RetrievalMode]] = None
    limit: int = Field(10, ge=1, le=50)

class QueryPlanRequest(BaseModel):
    # EXPLAIN one retrieval arm's real query body so a builder can see which index
    # the planner chooses (or rejects at small corpus size). 'hybrid' returns the
    # plan of all three arms, since the fused ranker runs each of them.
    query: str
    arm: Literal["hybrid", "semantic", "lexical", "fuzzy"] = "hybrid"
    limit: int = Field(10, ge=1, le=50)
    source_systems: Optional[List[str]] = None
    project_key: Optional[str] = None
