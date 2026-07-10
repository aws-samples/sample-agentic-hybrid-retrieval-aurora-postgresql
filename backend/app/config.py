from __future__ import annotations
from pydantic import BaseModel
from functools import lru_cache
import os
from dotenv import load_dotenv

load_dotenv()

def _embedding_model() -> str:
    return (
        os.environ.get("BEDROCK_EMBEDDING_MODEL")
        or os.environ.get("BEDROCK_EMBED_MODEL_ID")
        or "us.cohere.embed-v4:0"
    )

class Settings(BaseModel):
    database_url: str = os.environ.get("DATABASE_URL", "")
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
    app_display_name: str = os.environ.get("APP_DISPLAY_NAME", "AuraLens")

    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
