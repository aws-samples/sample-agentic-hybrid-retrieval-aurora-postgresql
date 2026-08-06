from __future__ import annotations
from pydantic import BaseModel, Field
from functools import lru_cache
import os
from dotenv import load_dotenv

# Process configuration wins. Workshop Studio writes .env for interactive shells,
# while tests and one-off validation commands can override individual values.
load_dotenv(override=False)

# Every field below reads the environment through a default_factory, so the value
# is resolved when Settings() is constructed rather than when this module is
# imported. A bare `field: str = os.environ.get(...)` default is evaluated at
# class-definition time: any process that exports DATABASE_URL after the first
# import of this module would silently keep the old target. That defect pointed
# the destructive test suite at the live Aurora database.

def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}

def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        parsed = default
    else:
        parsed = int(value)
    if minimum is not None:
        return max(minimum, parsed)
    return parsed


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        parsed = default
    else:
        parsed = float(value)
    if minimum is not None:
        return max(minimum, parsed)
    return parsed


def _embedding_model() -> str:
    return (
        os.environ.get("BEDROCK_EMBEDDING_MODEL")
        or os.environ.get("BEDROCK_EMBED_MODEL_ID")
        or "us.cohere.embed-v4:0"
    )

def _cohere_rerank_model() -> str:
    return (
        os.environ.get("COHERE_RERANK_MODEL")
        or os.environ.get("BEDROCK_COHERE_RERANK_MODEL")
        or os.environ.get("BEDROCK_RERANK_MODEL")
        or "cohere.rerank-v3-5:0"
    )

class Settings(BaseModel):
    database_url: str = Field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "")
    )
    # The optional security module (sql/11_roles_rls.sql + sql/12_masking.sql).
    # Off by default: the core retrieval workshop must run on a database that has
    # never had a persona role, an RLS policy, or a masking policy applied.
    workshop_app_database_url: str = Field(
        default_factory=lambda: os.environ.get("WORKSHOP_APP_DATABASE_URL", "")
    )
    workbench_security_enabled: bool = Field(
        default_factory=lambda: _env_bool("WORKBENCH_SECURITY_ENABLED", False)
    )
    # The hot-write and pool-status routes exist only to drive and observe the
    # guided incident. They are disabled unless the workshop runner enables them.
    lab_endpoints_enabled: bool = Field(
        default_factory=lambda: _env_bool("LAB_ENDPOINTS_ENABLED", False)
    )
    database_connect_timeout_seconds: int = Field(
        default_factory=lambda: _env_int(
            "DATABASE_CONNECT_TIMEOUT_SECONDS", 10, minimum=1
        )
    )
    # A workshop room drives many concurrent requests through one API process; a
    # bounded connection pool keeps Aurora from being hit with a fresh connect per
    # request while capping the total sessions the process can open.
    db_pool_min_size: int = Field(
        default_factory=lambda: _env_int("DB_POOL_MIN_SIZE", 1, minimum=0)
    )
    db_pool_max_size: int = Field(
        default_factory=lambda: _env_int("DB_POOL_MAX_SIZE", 10, minimum=1)
    )
    db_pool_max_idle_seconds: int = Field(
        default_factory=lambda: _env_int("DB_POOL_MAX_IDLE_SECONDS", 300, minimum=1)
    )
    # Pool checkout bounds application queuing. statement_timeout is configured
    # separately inside the hot-write transaction so a checked-out request cannot
    # wait on the backfill forever.
    lab_hot_write_checkout_timeout_seconds: float = Field(
        default_factory=lambda: _env_float(
            "LAB_HOT_WRITE_CHECKOUT_TIMEOUT_SECONDS",
            3.0,
            minimum=0.1,
        )
    )
    lab_hot_write_statement_timeout: str = Field(
        default_factory=lambda: os.environ.get(
            "LAB_HOT_WRITE_STATEMENT_TIMEOUT",
            "40s",
        )
    )
    lab_hot_write_request_count: int = Field(
        default_factory=lambda: _env_int(
            "LAB_HOT_WRITE_REQUEST_COUNT",
            12,
            minimum=1,
        )
    )
    # Bedrock throttles hard when a full room calls it at once; adaptive retries add
    # client-side rate limiting on top of the bounded attempt count.
    bedrock_max_attempts: int = Field(
        default_factory=lambda: _env_int("BEDROCK_MAX_ATTEMPTS", 5, minimum=1)
    )
    aws_region: str = Field(
        default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1")
    )
    cors_allow_origins: str = Field(
        default_factory=lambda: os.environ.get(
            "CORS_ALLOW_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:5174,http://127.0.0.1:5174",
        )
    )
    cors_allow_origin_regex: str = Field(
        default_factory=lambda: os.environ.get(
            "CORS_ALLOW_ORIGIN_REGEX", r"https?://(localhost|127\.0\.0\.1):[0-9]+"
        )
    )
    # Default to Cohere Embed 4 so live queries use the same vector space as
    # documents embedded during the participant's current incident run.
    embed_provider: str = Field(
        default_factory=lambda: os.environ.get("EMBED_PROVIDER", "bedrock")
    )
    embed_dim: int = Field(
        default_factory=lambda: int(os.environ.get("EMBED_DIM", "1024"))
    )
    bedrock_synthesis_model: str = Field(
        default_factory=lambda: os.environ.get(
            "BEDROCK_SYNTHESIS_MODEL",
            "global.anthropic.claude-sonnet-5",
        )
    )
    bedrock_model_transport: str = Field(
        default_factory=lambda: os.environ.get(
            "BEDROCK_MODEL_TRANSPORT",
            "converse_global_cris",
        )
    )
    # Synthesis treats a max_tokens stop as a failure and falls back to extractive
    # text, so the cap has to clear the answer's real ceiling rather than its
    # average. The three-paragraph answer measures 1190-1210 output tokens on the
    # four-clause question against live evidence, and 1365 on a sizing run, so
    # 1200 truncated the headline demo on normal variance. 2000 leaves headroom
    # without inviting a longer answer: length is bounded by the prompt, not here.
    bedrock_synthesis_max_tokens: int = Field(
        default_factory=lambda: _env_int(
            "BEDROCK_SYNTHESIS_MAX_TOKENS",
            2000,
            minimum=1,
        )
    )
    bedrock_embedding_model: str = Field(default_factory=_embedding_model)
    bedrock_embed_model_id: str = Field(default_factory=_embedding_model)
    # Cohere Rerank is exposed through the Bedrock Agent Runtime rerank API.
    # Keep the participant-facing model explicit: this is Cohere Rerank v3.5,
    # not a generic Bedrock ranking score.
    cohere_rerank_enabled: bool = Field(
        default_factory=lambda: _env_bool(
            "COHERE_RERANK_ENABLED", _env_bool("RERANK_ENABLED", True)
        )
    )
    cohere_rerank_model: str = Field(default_factory=_cohere_rerank_model)
    cohere_rerank_max_documents: int = Field(
        default_factory=lambda: _env_int(
            "COHERE_RERANK_MAX_DOCUMENTS",
            _env_int("RERANK_MAX_DOCUMENTS", 30, minimum=1),
            minimum=1,
        )
    )
    app_display_name: str = Field(
        default_factory=lambda: os.environ.get(
            "APP_DISPLAY_NAME", "Hybrid Retrieval Workbench"
        )
    )
    # Lock-analysis hand-off. Deployment identity and the console URL template
    # are captured during the dry run, never guessed. With no template, the Proof
    # surface still renders the observation window but no deep-link button.
    workbench_db_resource_id: str = Field(
        default_factory=lambda: os.environ.get("WORKBENCH_DB_RESOURCE_ID", "")
    )
    workbench_region: str = Field(
        default_factory=lambda: os.environ.get("WORKBENCH_REGION")
        or os.environ.get("AWS_REGION", "us-east-1")
    )
    # The lock-analysis template may use {region}, {db_resource_id}, and
    # {window_start}/{window_end}. The API substitutes only placeholders the
    # operator captured from the real console URL during the dry run.
    workbench_lock_url_template: str = Field(
        default_factory=lambda: os.environ.get("WORKBENCH_LOCK_URL_TEMPLATE", "")
    )

    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
