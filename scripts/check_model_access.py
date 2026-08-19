#!/usr/bin/env python3
"""Prove, per model, whether this account can actually invoke it on Bedrock.

An `ACTIVE` inference profile does not mean the account may use it. A fresh
Workshop Studio account returned this for the pinned agent model:

    AccessDeniedException: anthropic.claude-sonnet-5 is not available for this
    account.

That is an *entitlement* failure, not an IAM one, and the two are easy to confuse
because both arrive as `AccessDeniedException`. An IAM failure names the principal
and the action; an entitlement failure names the model and points at AWS Sales.
This check separates them and says which remedy applies, because the fix for one
is a policy edit and the fix for the other is model access on the account.

It also probes fallbacks, so a failure tells you what you *can* use rather than
only what you cannot. Every model is exercised through the same API the
application uses: Converse for the agent, InvokeModel for embeddings, Rerank for
the reranker. A model that answers here is a model the application can use.

Deliberately dependency-light: boto3 and the standard library only, no `service.*`
imports. The bootstrap's Claude Code preflight runs *before* the repository is
cloned, so the box that needs this check most may not have the repository on it.
Copy this one file to such a box and run it.

Usage
-----
    # In the repository, with the pinned models filled in for you:
    make check-model-access

    # Standalone on any box with the account's credentials:
    python3 scripts/check_model_access.py \\
      --chat global.anthropic.claude-sonnet-5 \\
      --embed us.cohere.embed-v4:0 \\
      --rerank cohere.rerank-v3-5:0

    python3 scripts/check_model_access.py --chat ... --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
except ImportError:  # pragma: no cover - the box always has boto3 via uv
    print(
        "FAIL: boto3 is not importable; run inside the project venv or `pip install boto3`"
    )
    raise SystemExit(2) from None

DEFAULT_REGION = "us-east-1"

# Diagnostic probes, not configuration. When a pinned model is not entitled, the
# useful question is which comparable model is, so these are tried too and
# reported separately. They are never used by the application.
CHAT_FALLBACKS = (
    "global.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
)

ENTITLEMENT_MARKERS = (
    "is not available for this account",
    "You can explore other available models",
    "don't have access to the model",
    "access to the model with the specified model ID",
)


class Outcome:
    """Why a model did or did not answer, and what to do about it."""

    OK = "OK"
    NOT_ENTITLED = "NOT_ENTITLED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    THROTTLED = "THROTTLED"
    NOT_FOUND = "NOT_FOUND"
    ERROR = "ERROR"


REMEDY = {
    Outcome.NOT_ENTITLED: (
        "grant model access on this account (Bedrock console -> Model access); "
        "an ACTIVE inference profile is not enough"
    ),
    Outcome.NOT_AUTHORIZED: (
        "the account may use this model but the caller's IAM policy does not "
        "allow it; a global profile needs the profile ARN and the regional and "
        "regionless foundation-model ARNs"
    ),
    Outcome.THROTTLED: "transient; retry, and treat a first cold invoke as unreliable",
    Outcome.NOT_FOUND: "no such model or profile in this region; check the identifier",
    Outcome.ERROR: "read the message; this is not an access problem",
}


@dataclass
class Probe:
    """One model, one verdict."""

    kind: str
    model_id: str
    required: bool
    outcome: str = Outcome.ERROR
    detail: str = ""
    latency_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "model_id": self.model_id,
            "required": self.required,
            "outcome": self.outcome,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
        }


@dataclass
class Report:
    probes: list[Probe] = field(default_factory=list)

    @property
    def required_failures(self) -> list[Probe]:
        return [p for p in self.probes if p.required and p.outcome != Outcome.OK]

    @property
    def usable_alternatives(self) -> list[Probe]:
        return [p for p in self.probes if not p.required and p.outcome == Outcome.OK]


def classify(error: Exception) -> tuple[str, str]:
    """Map a Bedrock exception onto an outcome and a one-line detail.

    Entitlement and authorization both surface as AccessDeniedException, so the
    message text is the only thing that separates them.
    """
    if isinstance(error, NoCredentialsError):
        return Outcome.ERROR, "no credentials resolved in this environment"
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "")
        message = error.response.get("Error", {}).get("Message", "") or str(error)
        one_line = " ".join(message.split())
        if code == "AccessDeniedException":
            if any(marker in message for marker in ENTITLEMENT_MARKERS):
                return Outcome.NOT_ENTITLED, one_line
            return Outcome.NOT_AUTHORIZED, one_line
        if code in {"ThrottlingException", "TooManyRequestsException"}:
            return Outcome.THROTTLED, one_line
        if code in {"ResourceNotFoundException", "ValidationException"}:
            return Outcome.NOT_FOUND, one_line
        return Outcome.ERROR, f"{code}: {one_line}"
    if isinstance(error, BotoCoreError):
        return Outcome.ERROR, " ".join(str(error).split())
    return Outcome.ERROR, " ".join(str(error).split())


def _runtime(region: str, service: str = "bedrock-runtime"):
    # Bounded so an unreachable endpoint fails in seconds rather than minutes.
    return boto3.client(
        service,
        region_name=region,
        config=Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )


def probe_chat(model_id: str, region: str, required: bool) -> Probe:
    """Converse with a two-token budget: the smallest real invocation there is."""
    probe = Probe("chat", model_id, required)
    try:
        response = _runtime(region).converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "Reply with OK."}]}],
            inferenceConfig={"maxTokens": 8},
        )
        probe.outcome = Outcome.OK
        probe.latency_ms = (
            int(response.get("metrics", {}).get("latencyMs") or 0) or None
        )
        probe.detail = f"{response['usage']['totalTokens']} tokens"
    except Exception as error:  # noqa: BLE001 - every failure is a verdict
        probe.outcome, probe.detail = classify(error)
    return probe


def probe_embedding(model_id: str, region: str, required: bool) -> Probe:
    probe = Probe("embedding", model_id, required)
    try:
        response = _runtime(region).invoke_model(
            modelId=model_id,
            body=json.dumps({"texts": ["access check"], "input_type": "search_query"}),
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(response["body"].read())
        vectors = payload.get("embeddings") or []
        if isinstance(vectors, dict):
            vectors = next(iter(vectors.values()), [])
        probe.outcome = Outcome.OK
        first = vectors[0] if vectors else []
        probe.detail = f"vector of {len(first)} values"
    except Exception as error:  # noqa: BLE001
        probe.outcome, probe.detail = classify(error)
    return probe


def probe_rerank(model_id: str, region: str, required: bool) -> Probe:
    """Rerank lives on bedrock-agent-runtime, the same client the app uses."""
    probe = Probe("rerank", model_id, required)
    try:
        arn = f"arn:aws:bedrock:{region}::foundation-model/{model_id}"
        response = _runtime(region, "bedrock-agent-runtime").rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": "access check"}}],
            sources=[
                {
                    "type": "INLINE",
                    "inlineDocumentSource": {
                        "type": "TEXT",
                        "textDocument": {"text": "a document to score"},
                    },
                }
            ],
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "numberOfResults": 1,
                    "modelConfiguration": {"modelArn": arn},
                },
            },
        )
        probe.outcome = Outcome.OK
        probe.detail = f"{len(response.get('results', []))} result scored"
    except Exception as error:  # noqa: BLE001
        probe.outcome, probe.detail = classify(error)
    return probe


def run(args: argparse.Namespace) -> Report:
    report = Report()
    if args.chat:
        report.probes.append(probe_chat(args.chat, args.region, required=True))
    if args.embed:
        report.probes.append(probe_embedding(args.embed, args.region, required=True))
    if args.rerank:
        report.probes.append(probe_rerank(args.rerank, args.region, required=True))

    # Only worth spending calls on fallbacks when a required chat model failed.
    chat_failed = any(
        p.kind == "chat" and p.required and p.outcome != Outcome.OK
        for p in report.probes
    )
    if chat_failed and not args.no_fallbacks:
        for candidate in CHAT_FALLBACKS:
            if candidate == args.chat:
                continue
            report.probes.append(probe_chat(candidate, args.region, required=False))
    return report


def render(report: Report, region: str) -> None:
    print(f"Bedrock model access in {region}\n")
    width = max(len(p.model_id) for p in report.probes)
    for probe in report.probes:
        tag = "required" if probe.required else "fallback"
        mark = "ok  " if probe.outcome == Outcome.OK else "FAIL"
        print(f"  {mark} {probe.model_id:<{width}}  {tag:<8} {probe.outcome}")
        if probe.detail:
            print(f"       {probe.detail[:150]}")

    failures = report.required_failures
    if not failures:
        print("\nEvery required model answered. Bedrock access is not your blocker.")
        return

    print("\nRequired models that did not answer:")
    for probe in failures:
        print(f"  {probe.model_id}\n    {REMEDY[probe.outcome]}")

    usable = report.usable_alternatives
    if usable:
        print("\nThese answered and could be pinned instead:")
        for probe in usable:
            print(f"  {probe.model_id}")
    elif any(p.outcome == Outcome.NOT_ENTITLED for p in failures):
        print(
            "\nNo probed alternative answered either, so this account has no "
            "entitled chat model in this family. Model access has to be granted."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--chat", help="agent and synthesis model or inference profile")
    parser.add_argument("--embed", help="embedding model")
    parser.add_argument("--rerank", help="reranking model")
    parser.add_argument("--no-fallbacks", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not any((args.chat, args.embed, args.rerank)):
        parser.error("give at least one of --chat, --embed, --rerank")

    report = run(args)
    if args.json:
        print(json.dumps([p.as_dict() for p in report.probes], indent=1))
    else:
        render(report, args.region)
    return 1 if report.required_failures else 0


if __name__ == "__main__":
    sys.exit(main())
