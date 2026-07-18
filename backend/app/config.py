from __future__ import annotations
from pydantic import BaseModel
from functools import lru_cache
import os
from dotenv import load_dotenv

# Workshop Studio and `make aurora-local-env` write the intended local runtime
# into .env. Let that file win over stale shell exports such as AWS_REGION from a
# previous account or region.
load_dotenv(override=True)

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
    database_url: str = os.environ.get("DATABASE_URL", "")
    database_connect_timeout_seconds: int = _env_int("DATABASE_CONNECT_TIMEOUT_SECONDS", 10, minimum=1)
    aws_region: str = os.environ.get("AWS_REGION", "us-east-1")
    cors_allow_origins: str = os.environ.get(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
    )
    cors_allow_origin_regex: str = os.environ.get("CORS_ALLOW_ORIGIN_REGEX", r"https?://(localhost|127\.0\.0\.1):[0-9]+")
    # Default to real Cohere embed-v4 so live query embeddings share the exact
    # vector space as the seeded corpus (the shipped dump is Cohere-embedded).
    # Set EMBED_PROVIDER=hash only for an offline, no-Bedrock corpus.
    embed_provider: str = os.environ.get("EMBED_PROVIDER", "bedrock")
    embed_dim: int = int(os.environ.get("EMBED_DIM", "1024"))
    bedrock_opus_model: str = os.environ.get("BEDROCK_OPUS_MODEL", "global.anthropic.claude-opus-4-8")
    bedrock_sonnet_model: str = os.environ.get("BEDROCK_SONNET_MODEL", "global.anthropic.claude-sonnet-5")
    bedrock_router_model: str = os.environ.get("BEDROCK_ROUTER_MODEL", "global.anthropic.claude-sonnet-5")
    bedrock_reporting_model: str = os.environ.get("BEDROCK_REPORTING_MODEL", "global.anthropic.claude-sonnet-5")
    bedrock_chat_model: str = os.environ.get("BEDROCK_CHAT_MODEL", "global.anthropic.claude-opus-4-8")
    bedrock_embedding_model: str = _embedding_model()
    bedrock_embed_model_id: str = _embedding_model()
    claude_code_model: str = os.environ.get("CLAUDE_CODE_MODEL", "global.anthropic.claude-sonnet-5")
    # Cohere Rerank is exposed through the Bedrock Agent Runtime rerank API.
    # Keep the participant-facing model explicit: this is Cohere Rerank v3.5,
    # not a generic Bedrock ranking score.
    cohere_rerank_enabled: bool = _env_bool("COHERE_RERANK_ENABLED", _env_bool("RERANK_ENABLED", True))
    cohere_rerank_model: str = _cohere_rerank_model()
    cohere_rerank_max_documents: int = _env_int(
        "COHERE_RERANK_MAX_DOCUMENTS",
        _env_int("RERANK_MAX_DOCUMENTS", 30, minimum=1),
        minimum=1,
    )
    app_display_name: str = os.environ.get("APP_DISPLAY_NAME", "AuraLens")

    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
