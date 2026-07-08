from __future__ import annotations
import hashlib
import json
import os
import re
from typing import List

import numpy as np

SYNONYMS = {
    "delay": ["blocked", "slipped", "late", "lag", "deferred"],
    "customer": ["account", "client", "tenant"],
    "incident": ["outage", "sev", "service disruption"],
    "latency": ["slow", "p95", "response time", "lag"],
    "failover": ["blue green", "cutover", "switchover", "replica promotion"],
    "commitment": ["promise", "deliverable", "timeline", "sla"],
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

def bedrock_embedding(text: str, dim: int = 1024, model_id: str | None = None, region: str | None = None) -> List[float]:
    import boto3
    model_id = model_id or os.environ.get("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("bedrock-runtime", region_name=region)
    body = {"inputText": text, "dimensions": dim, "normalize": True}
    resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
    payload = json.loads(resp["body"].read())
    return payload["embedding"]

def embed_text(text: str, provider: str = "hash", dim: int = 1024) -> List[float]:
    if provider == "bedrock":
        return bedrock_embedding(text, dim=dim)
    return hash_embedding(text, dim=dim)

def to_pgvector(values: List[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"
