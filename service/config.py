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
    lexical_weight: float
    trigram_weight: float
    semantic_weight: float
    business_weight: float
    bedrock_max_attempts: int
    cors_origins: tuple[str, ...]


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
        lexical_candidate_limit=int(os.getenv("LEXICAL_CANDIDATE_LIMIT", "100")),
        trigram_candidate_limit=int(os.getenv("TRIGRAM_CANDIDATE_LIMIT", "75")),
        semantic_candidate_limit=int(os.getenv("SEMANTIC_CANDIDATE_LIMIT", "100")),
        rerank_candidate_limit=int(os.getenv("RERANK_CANDIDATE_LIMIT", "50")),
        rrf_k=int(os.getenv("RRF_K", "60")),
        lexical_weight=float(os.getenv("LEXICAL_WEIGHT", "0.30")),
        trigram_weight=float(os.getenv("TRIGRAM_WEIGHT", "0.10")),
        semantic_weight=float(os.getenv("SEMANTIC_WEIGHT", "0.45")),
        business_weight=float(os.getenv("BUSINESS_WEIGHT", "0.15")),
        bedrock_max_attempts=int(os.getenv("BEDROCK_MAX_ATTEMPTS", "5")),
        cors_origins=origins,
    )
