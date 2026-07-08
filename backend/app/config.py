from __future__ import annotations
from pydantic import BaseModel
from functools import lru_cache
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    database_url: str = os.environ.get("DATABASE_URL", "")
    aws_region: str = os.environ.get("AWS_REGION", "us-east-1")
    embed_provider: str = os.environ.get("EMBED_PROVIDER", "hash")
    embed_dim: int = int(os.environ.get("EMBED_DIM", "1024"))
    bedrock_embed_model_id: str = os.environ.get("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
    app_display_name: str = os.environ.get("APP_DISPLAY_NAME", "Evidence Trail")

@lru_cache
def get_settings() -> Settings:
    return Settings()
