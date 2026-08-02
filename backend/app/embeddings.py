from __future__ import annotations
import hashlib
import json
import os
import re
from typing import List

import numpy as np

DEFAULT_BEDROCK_EMBEDDING_MODEL = "us.cohere.embed-v4:0"

SYNONYMS = {
    "delay": ["blocked", "slipped", "late", "lag", "deferred"],
    "incident": ["outage", "sev", "service disruption"],
    "latency": ["slow", "p95", "response time", "lag"],
    "failover": ["blue green", "cutover", "switchover", "replica promotion"],
    "bug": ["defect", "issue", "regression"],
    "slack": ["channel", "thread", "message", "conversation"],
}

def normalize_text(text: str) -> str:
    value = (text or "").lower()
    for canonical, variants in SYNONYMS.items():
        for v in variants:
            value = value.replace(v, canonical)
    return re.sub(r"\s+", " ", value).strip()

def hash_embedding(text: str, dim: int = 1024) -> List[float]:
    text = normalize_text(text)
    vec = np.zeros(dim, dtype=np.float32)
    tokens = re.findall(r"[a-zA-Z0-9_\-]+", text)
    for token in tokens:
        h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 8) & 1) else -1.0
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return [float(x) for x in vec]

def _bedrock_embedding_model(model_id: str | None) -> str:
    return (
        model_id
        or os.environ.get("BEDROCK_EMBEDDING_MODEL")
        or os.environ.get("BEDROCK_EMBED_MODEL_ID")
        or DEFAULT_BEDROCK_EMBEDDING_MODEL
    )

def _cohere_embed_body(texts: str | List[str], dim: int, input_type: str) -> dict:
    return {
        "texts": [texts] if isinstance(texts, str) else texts,
        "input_type": input_type,
        "embedding_types": ["float"],
        "output_dimension": dim,
        "truncate": "END",
    }

def _titan_embed_body(text: str, dim: int) -> dict:
    return {"inputText": text, "dimensions": dim, "normalize": True}

def _embeddings_from_payload(payload: dict) -> List[List[float]]:
    if isinstance(payload.get("embedding"), list):
        return [payload["embedding"]]

    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return embeddings
    if isinstance(embeddings, dict):
        floats = embeddings.get("float") or embeddings.get("floats")
        if isinstance(floats, list) and floats and isinstance(floats[0], list):
            return floats

    raise ValueError("Bedrock embedding response did not include a supported embedding field.")


def _embedding_from_payload(payload: dict) -> List[float]:
    return _embeddings_from_payload(payload)[0]


def bedrock_embeddings(
    texts: List[str],
    dim: int = 1024,
    model_id: str | None = None,
    region: str | None = None,
    input_type: str = "search_document",
) -> List[List[float]]:
    if not texts:
        return []
    from .bedrock import get_bedrock_client

    model_id = _bedrock_embedding_model(model_id)
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    if "cohere.embed" not in model_id:
        return [
            bedrock_embedding(text, dim=dim, model_id=model_id, region=region, input_type=input_type)
            for text in texts
        ]
    client = get_bedrock_client("bedrock-runtime", region=region)
    resp = client.invoke_model(
        modelId=model_id,
        body=json.dumps(_cohere_embed_body(texts, dim, input_type)),
    )
    vectors = _embeddings_from_payload(json.loads(resp["body"].read()))
    if len(vectors) != len(texts):
        raise ValueError(f"Bedrock returned {len(vectors)} embeddings for {len(texts)} texts.")
    return vectors


def bedrock_embedding(
    text: str,
    dim: int = 1024,
    model_id: str | None = None,
    region: str | None = None,
    input_type: str = "search_document",
) -> List[float]:
    from .bedrock import get_bedrock_client

    model_id = _bedrock_embedding_model(model_id)
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    client = get_bedrock_client("bedrock-runtime", region=region)
    body = _cohere_embed_body([text], dim, input_type) if "cohere.embed" in model_id else _titan_embed_body(text, dim)
    resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
    payload = json.loads(resp["body"].read())
    return _embedding_from_payload(payload)

def embed_text(text: str, provider: str = "hash", dim: int = 1024, input_type: str = "search_document") -> List[float]:
    if provider == "bedrock":
        return bedrock_embedding(text, dim=dim, input_type=input_type)
    return hash_embedding(text, dim=dim)


def embed_texts(
    texts: List[str],
    provider: str = "hash",
    dim: int = 1024,
    input_type: str = "search_document",
) -> List[List[float]]:
    if provider == "bedrock":
        return bedrock_embeddings(texts, dim=dim, input_type=input_type)
    return [hash_embedding(text, dim=dim) for text in texts]


def to_pgvector(values: List[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"
