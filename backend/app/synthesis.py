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
- When the question asks what a future migration should do differently, present
  bounded batches with commits as cited guidance derived from the observed
  unbatched backfill. That guidance sentence must include the numbered citation
  for the unbatched-backfill evidence; do not present it as an observed outcome.
- Write exactly four short paragraphs, separated by a blank line. No headings,
  bullets, numbered lists, or preamble: the reader strips them, so they render as
  literal characters mid-sentence. The UI adds the section headings, so preserve
  this paragraph order exactly.
- Paragraph 1 is "Root cause": one plain-language conclusion that answers why
  the incident happened, with citations. Include future-migration guidance here
  only when the question asks for it.
- Paragraph 2 begins "Inside PostgreSQL" and explains the sessions that reached
  the database, why they blocked, and why they recovered, with citations.
- Paragraph 3 begins "At the application pool" and explains why the callers that
  never reached PostgreSQL timed out, with citations.
- Paragraph 4 begins "For query performance" and explains why ANALYZE did not
  change the access path. State that a human must create the missing composite
  index as the remediation, with citations, then close by directing the reader
  to review the proposed index in Action review before executing it.
- Keep each sentence under about 30 words. A sentence-count limit alone produces
  one enormous sentence per clause, which is unreadable on a projector.
- Put PIDs, relation OIDs, lock modes, and exact SQL in the cited evidence rather
  than stacking them into the prose. Name an identifier only when the claim
  depends on that specific value.
- Never restate proposed DDL. The supervised Action review is the one validated
  copy of the proposal, preconditions, expected effect, and rollback.
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
