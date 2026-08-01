from __future__ import annotations

from typing import Any

from .bedrock import get_bedrock_client
from .config import get_settings


SYSTEM_PROMPT = """You are an incident evidence specialist.

Answer only from the numbered evidence supplied by the caller.
- Cite every factual sentence with one or more bracketed evidence numbers.
- Use square brackets only for citations. Write arrays and PID lists with parentheses.
- Preserve database identifiers, lock modes, SQL, timestamps, and source limits exactly.
- Distinguish observed telemetry, confirmed relationships, ruled-out changes, and guidance.
- Never call a rerank score, cosine similarity, or reciprocal-rank-fusion score a probability.
- If the evidence is insufficient or conflicts, state that with citations.
- Write exactly 5 to 7 concise sentences with no headings, bullets, or preamble.
"""


def evidence_block(evidence: list[dict[str, Any]], limit: int = 8) -> str:
    blocks: list[str] = []
    for number, row in enumerate(evidence[:limit], start=1):
        metadata = [
            f"kind={row.get('evidence_kind')}",
            f"key={row.get('external_key')}",
            f"relation={row.get('via_relation')}" if row.get("via_relation") else "",
            f"relation_origin={row.get('via_origin')}" if row.get("via_origin") else "",
            f"cluster={row.get('cluster_id')}" if row.get("cluster_id") else "",
            f"incident={row.get('incident_id')}" if row.get("incident_id") else "",
            f"account={row.get('account_name')}" if row.get("account_name") else "",
            f"severity={row.get('severity')}" if row.get("severity") else "",
            f"revision={row.get('source_revision')}",
        ]
        snippet = str(row.get("snippet") or "").replace("[", "(").replace("]", ")")
        relationships = row.get("relationships") or []
        relationship_lines = [
            (
                f"Relationship: {relationship.get('relation')} "
                f"{relationship.get('direction')} "
                f"{relationship.get('other_external_key')}; "
                f"origin={relationship.get('origin')}; "
                f"confidence={relationship.get('confidence')}"
                + (
                    f"; rationale={relationship.get('rationale')}"
                    if relationship.get("rationale")
                    else ""
                )
            )
            for relationship in relationships
        ]
        blocks.append(
            "\n".join(
                (
                    f"[{number}] {'; '.join(item for item in metadata if item)}",
                    f"Title: {row.get('title')}",
                    *relationship_lines,
                    f"Evidence: {snippet}",
                )
            )
        )
    return "\n\n".join(blocks)


def synthesize_live(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    required_kinds: list[str] | None = None,
) -> dict[str, Any]:
    if not evidence:
        raise ValueError("no evidence rows were supplied for synthesis")

    settings = get_settings()
    if settings.bedrock_model_transport != "converse_global_cris":
        raise ValueError(
            "unsupported BEDROCK_MODEL_TRANSPORT; use converse_global_cris "
            "until bedrock-mantle supports CRIS model identifiers"
        )
    if not settings.bedrock_synthesis_model.startswith(("global.", "us.", "eu.", "apac.")):
        raise ValueError(
            "BEDROCK_SYNTHESIS_MODEL must be a cross-region inference profile ID"
        )

    response = get_bedrock_client(
        "bedrock-runtime",
        region=settings.aws_region,
    ).converse(
        modelId=settings.bedrock_synthesis_model,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"Question: {question}\n\n"
                            f"Evidence:\n{evidence_block(evidence)}\n\n"
                            + (
                                "The answer must use and cite evidence for each "
                                "required kind: "
                                f"{', '.join(required_kinds)}.\n\n"
                                if required_kinds
                                else ""
                            )
                            + "Write the cited answer."
                        )
                    }
                ],
            }
        ],
        inferenceConfig={"maxTokens": settings.bedrock_synthesis_max_tokens},
    )
    content = response.get("output", {}).get("message", {}).get("content", [])
    answer = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("text")
    ).strip()
    if not answer:
        raise ValueError("Bedrock returned an empty synthesis")
    if response.get("stopReason") == "max_tokens":
        raise ValueError("Bedrock synthesis reached the configured token limit")

    usage = response.get("usage") or {}
    return {
        "answer": answer,
        "model": settings.bedrock_synthesis_model,
        "transport": settings.bedrock_model_transport,
        "usage": {
            "input_tokens": int(usage.get("inputTokens", 0)),
            "output_tokens": int(usage.get("outputTokens", 0)),
            "total_tokens": int(usage.get("totalTokens", 0)),
        },
        "stop_reason": response.get("stopReason"),
    }
