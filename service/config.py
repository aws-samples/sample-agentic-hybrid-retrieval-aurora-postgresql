"""Runtime configuration for the catalog retrieval service.

Retrieval numbers come from `db/config/retrieval.yaml` via
`scripts.retrieval_profile`, which resolves environment overrides and enforces
bounds. This module does not restate those numbers: a default written here would
be the fourth copy that `scripts/config_tripwire.py` exists to prevent.

Non-retrieval settings (model IDs, region, CORS) are read here, because they are
deployment identity rather than retrieval tuning and the yaml is not their home.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.retrieval_profile import (  # noqa: E402  (path set above)
    ProfileError,
    RetrievalProfileConfig,
    load_profile,
)


class ConfigurationError(RuntimeError):
    """A setting cannot serve a request, so the process must not start.

    `RetrievalProfile` enforces the same bounds when it is constructed per
    request. Enforcing them at load too means a bad value fails at startup with
    the parameter named instead of escaping as an unhandled HTTP 500.
    """


# Bounds for settings that are NOT retrieval tuning. Retrieval bounds live in
# `scripts.retrieval_profile.BOUNDS`, next to the yaml path they guard.
_NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
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


def _retrieval_profile() -> RetrievalProfileConfig:
    """Load the yaml-sourced profile, re-raising as a configuration failure.

    Callers of `get_settings` catch `ConfigurationError`; a `ProfileError`
    escaping from here would bypass that handling and read as a crash rather
    than a misconfiguration.
    """
    try:
        return load_profile()
    except ProfileError as error:
        raise ConfigurationError(
            f"db/config/retrieval.yaml does not yield a usable profile: {error}"
        ) from error


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
    agent_model_id: str | None
    synthesis_model_id: str | None
    rerank_required: bool
    allow_development_embeddings: bool
    lexical_candidate_limit: int
    trigram_candidate_limit: int
    semantic_candidate_limit: int
    rerank_candidate_limit: int
    rrf_k: int
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
    profile = _retrieval_profile()
    chat_model_id = os.getenv(
        "BEDROCK_CHAT_MODEL_ID",
        os.getenv("BEDROCK_CHAT_MODEL", "global.anthropic.claude-sonnet-5"),
    )
    return Settings(
        database_url=os.getenv("DATABASE_URL"),
        aws_region=os.getenv("BEDROCK_REGION", os.getenv("AWS_REGION", "us-east-1")),
        vector_dimension=profile.vector_dimension,
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
        chat_model_id=chat_model_id,
        agent_model_id=os.getenv("BEDROCK_AGENT_MODEL_ID", chat_model_id),
        synthesis_model_id=os.getenv("BEDROCK_SYNTHESIS_MODEL_ID", chat_model_id),
        rerank_required=_boolean("RERANK_REQUIRED", True),
        allow_development_embeddings=_boolean(
            "ALLOW_DEVELOPMENT_EMBEDDINGS",
            False,
        ),
        # Every retrieval number below comes from db/config/retrieval.yaml, with
        # environment overrides already applied by scripts.retrieval_profile.
        # None is restated here; that is what made three copies possible.
        lexical_candidate_limit=profile.fts_limit,
        trigram_candidate_limit=profile.trigram_limit,
        semantic_candidate_limit=profile.semantic_limit,
        rerank_candidate_limit=profile.fused_limit,
        rrf_k=profile.rrf_k,
        hnsw_ef_search=profile.hnsw_ef_search,
        bedrock_max_attempts=_bounded("BEDROCK_MAX_ATTEMPTS", "5", int),
        cors_origins=origins,
    )
