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

def _rerank_model() -> str:
    return (
        os.environ.get("BEDROCK_RERANK_MODEL")
        or os.environ.get("BEDROCK_RERANK_MODEL_ID")
        or "cohere.rerank-v3-5:0"
    )

class Settings(BaseModel):
    database_url: str = os.environ.get("DATABASE_URL", "")
    aws_region: str = os.environ.get("AWS_REGION", "us-east-1")
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
    bedrock_rerank_model: str = _rerank_model()
    bedrock_rerank_model_id: str = _rerank_model()
    app_display_name: str = os.environ.get("APP_DISPLAY_NAME", "AuraLens")

@lru_cache
def get_settings() -> Settings:
    return Settings()
