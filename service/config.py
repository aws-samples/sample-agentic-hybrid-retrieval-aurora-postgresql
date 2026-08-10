"""Runtime configuration for the catalog retrieval service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


class ConfigurationError(RuntimeError):
    """A setting cannot serve a request, so the process must not start.

    `RetrievalProfile` enforces the same bounds when it is constructed per
    request. Enforcing them here too means a bad value fails at startup with the
    parameter named, instead of escaping as an unhandled HTTP 500 on every query.
    """


# Bounds are declared next to the setting and are the same numbers
# `service.models.RetrievalProfile` enforces. Phase 2 makes
# `db/config/retrieval.yaml` their single source; this stops the crash.
_NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    "VECTOR_DIM": (1, 4096),
    "FTS_CANDIDATE_LIMIT": (1, 1000),
    "TRIGRAM_CANDIDATE_LIMIT": (1, 1000),
    "SEMANTIC_CANDIDATE_LIMIT": (1, 1000),
    "RERANK_CANDIDATE_LIMIT": (1, 250),
    "RRF_K": (1, 10_000),
    "BUSINESS_WEIGHT": (0, 0.05),
    "HNSW_EF_SEARCH": (1, 1000),
    "BEDROCK_MAX_ATTEMPTS": (1, 20),
}


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded(name: str, default: str, cast: type[int] | type[float]):
    """Parse a numeric setting, refusing anything outside its declared bound."""
    raw = os.getenv(name, default)
    try:
        value = cast(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"{name}={raw!r} is not a valid {cast.__name__}. "
            f"Set {name} to a {cast.__name__} in "
            f"[{_NUMERIC_BOUNDS[name][0]}, {_NUMERIC_BOUNDS[name][1]}]."
        ) from exc
    low, high = _NUMERIC_BOUNDS[name]
    if not low <= value <= high:
        raise ConfigurationError(
            f"{name}={value} is out of range; it must be between {low} and "
            f"{high}. Copying config/.env.example gives a working value."
        )
    return value


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
        vector_dimension=_bounded("VECTOR_DIM", "1024", int),
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
        lexical_candidate_limit=_bounded("FTS_CANDIDATE_LIMIT", "120", int),
        trigram_candidate_limit=_bounded("TRIGRAM_CANDIDATE_LIMIT", "80", int),
        semantic_candidate_limit=_bounded("SEMANTIC_CANDIDATE_LIMIT", "150", int),
        rerank_candidate_limit=_bounded("RERANK_CANDIDATE_LIMIT", "50", int),
        rrf_k=_bounded("RRF_K", "60", int),
        # `mosaic_search.search_hybrid_rrf` fuses by reciprocal rank and adds a
        # small business nudge. There are no per-arm weights: RRF weights by
        # rank position, which is the point of using it.
        business_weight=_bounded("BUSINESS_WEIGHT", "0.003", float),
        hnsw_ef_search=_bounded("HNSW_EF_SEARCH", "100", int),
        bedrock_max_attempts=_bounded("BEDROCK_MAX_ATTEMPTS", "5", int),
        cors_origins=origins,
    )
