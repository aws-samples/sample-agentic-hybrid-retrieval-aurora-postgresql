"""Runtime configuration for the catalog retrieval service.

Retrieval numbers come from `db/config/retrieval.yaml` via
`scripts.retrieval_profile`, which resolves environment overrides and enforces
bounds. This module does not restate those numbers: a default written here would
be the fourth copy that `scripts/config_tripwire.py` exists to prevent.

Non-retrieval settings (model IDs, region, CORS) are read here, because they are
deployment identity rather than retrieval tuning and the yaml is not their home.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.retrieval_profile import (
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
    "DB_POOL_MAX_SIZE": (1, 64),
    "DB_POOL_TIMEOUT_SECONDS": (1, 120),
}


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise RuntimeError(
        f"{name} is {value!r}; found a value that is neither true nor false; "
        f"fix: use one of {sorted(_TRUE | _FALSE)}"
    )


def _bounded(name: str, default: str, cast: type[int | float]):
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


def _source_identity() -> tuple[str, bool]:
    """Return the configured or checked-out revision and whether files differ."""
    configured = os.getenv("MOSAIC_SOURCE_REVISION", "").strip()
    try:
        revision = (
            configured
            or subprocess.run(
                [
                    "git",
                    "-C",
                    str(Path(__file__).resolve().parents[1]),
                    "rev-parse",
                    "HEAD",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        dirty = bool(
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(Path(__file__).resolve().parents[1]),
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return configured or "unknown", True
    return revision or "unknown", dirty


def _dataset_manifest_sha256() -> str:
    """Identify the checked-in dataset manifest used by this service."""
    override = os.getenv("MOSAIC_DATASET_MANIFEST_SHA256", "").strip()
    if override:
        return override
    path = Path(__file__).resolve().parents[1] / "data" / "full" / "manifest.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    db_pool_max_size: int
    db_pool_timeout: float
    cors_origins: tuple[str, ...]
    source_revision: str = "unknown"
    source_worktree_dirty: bool = True
    dataset_manifest_sha256: str = "unknown"
    aurora_instance_class: str | None = None

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
    if "*" in origins:
        raise RuntimeError(
            "CORS_ORIGINS contains '*'; found a wildcard origin, which this "
            "service must not serve; fix: list the exact origins, e.g. "
            "http://localhost:5173"
        )
    profile = _retrieval_profile()
    source_revision, source_worktree_dirty = _source_identity()
    chat_model_id = os.getenv(
        "BEDROCK_CHAT_MODEL_ID",
        os.getenv("BEDROCK_CHAT_MODEL", "global.anthropic.claude-sonnet-4-6"),
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
        # Sized for a workshop room rather than a single reader. Uvicorn runs
        # synchronous routes on a bounded thread pool, and one agent turn checks a
        # connection out eight times in sequence, so 16 covers concurrent turns
        # without letting a stampede open hundreds of Aurora sessions. The timeout
        # exists so exhaustion surfaces as an error instead of a hung request.
        db_pool_max_size=_bounded("DB_POOL_MAX_SIZE", "16", int),
        db_pool_timeout=_bounded("DB_POOL_TIMEOUT_SECONDS", "20", float),
        cors_origins=origins,
        source_revision=source_revision,
        source_worktree_dirty=source_worktree_dirty,
        dataset_manifest_sha256=_dataset_manifest_sha256(),
        aurora_instance_class=os.getenv("AURORA_INSTANCE_CLASS") or None,
    )
