"""Runtime configuration for the catalog retrieval service."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    aws_region: str
    vector_dimension: int
    embedding_provider: str
    embedding_model_id: str
    rerank_provider: str
    rerank_model_id: str
    chat_model_id: str | None
    rerank_required: bool
    allow_development_embeddings: bool
    lexical_candidate_limit: int
    trigram_candidate_limit: int
    semantic_candidate_limit: int
    rerank_candidate_limit: int
    rrf_k: int
    business_weight: float
    hnsw_ef_search: int
    bedrock_max_attempts: int
    cors_origins: tuple[str, ...]

    @property
    def embedding_dimensions(self) -> int:
        """Width of the stored vectors.

        The schema is rendered at this width, so a mismatch is a hard failure at
        query time rather than a silent quality regression. Kept as an alias of
        `vector_dimension` so both names read correctly at their call sites.
        """
        return self.vector_dimension


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    origins = tuple(
        value.strip()
        for value in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if value.strip()
    )
    return Settings(
        database_url=os.getenv("DATABASE_URL"),
        aws_region=os.getenv("BEDROCK_REGION", os.getenv("AWS_REGION", "us-east-1")),
        vector_dimension=int(os.getenv("VECTOR_DIM", "1024")),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "bedrock"),
        embedding_model_id=os.getenv(
            "BEDROCK_EMBED_MODEL_ID",
            os.getenv("BEDROCK_EMBEDDING_MODEL", "us.cohere.embed-v4:0"),
        ),
        rerank_provider=os.getenv("RERANK_PROVIDER", "bedrock"),
        rerank_model_id=os.getenv(
            "BEDROCK_RERANK_MODEL_ID",
            "cohere.rerank-v3-5:0",
        ),
        chat_model_id=os.getenv(
            "BEDROCK_CHAT_MODEL_ID",
            os.getenv("BEDROCK_CHAT_MODEL", "global.anthropic.claude-sonnet-5"),
        ),
        rerank_required=_boolean("RERANK_REQUIRED", True),
        allow_development_embeddings=_boolean(
            "ALLOW_DEVELOPMENT_EMBEDDINGS",
            False,
        ),
        # Defaults match db/config/retrieval.yaml. Changing one without the
        # other makes the shipped profile a lie.
        lexical_candidate_limit=int(os.getenv("FTS_CANDIDATE_LIMIT", "120")),
        trigram_candidate_limit=int(os.getenv("TRIGRAM_CANDIDATE_LIMIT", "80")),
        semantic_candidate_limit=int(os.getenv("SEMANTIC_CANDIDATE_LIMIT", "150")),
        rerank_candidate_limit=int(os.getenv("RERANK_CANDIDATE_LIMIT", "50")),
        rrf_k=int(os.getenv("RRF_K", "60")),
        # `mosaic_search.search_hybrid_rrf` fuses by reciprocal rank and adds a
        # small business nudge. There are no per-arm weights: RRF weights by
        # rank position, which is the point of using it.
        business_weight=float(os.getenv("BUSINESS_WEIGHT", "0.003")),
        hnsw_ef_search=int(os.getenv("HNSW_EF_SEARCH", "100")),
        bedrock_max_attempts=int(os.getenv("BEDROCK_MAX_ATTEMPTS", "5")),
        cors_origins=origins,
    )
