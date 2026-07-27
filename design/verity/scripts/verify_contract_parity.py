#!/usr/bin/env python3
"""
Verify that the Verity tool contract produces the same semantic result over
HTTP/FastAPI, local stdio MCP, and an Amazon Bedrock AgentCore Gateway target.

This script exists to make one claim credible:

    The tool contract moves; the retrieval authority does not.

It therefore has to be capable of FAILING. The previous version compared the
three captures only to each other, after stripping the keys that differed --
so three copies of the same file passed, an empty `citations` list satisfied
"citation IDs match", and the golden file was never loaded at all.

This version:
  * compares every transport to fixtures/tool-parity-golden.json, not just to
    the other transports;
  * refuses to pass on empty evidence (vacuity guard);
  * recomputes every rrf_score from its arm positions and the controls, so a
    transport cannot agree with the others about a number that is wrong;
  * normalizes the AgentCore Gateway tool-name prefix rather than ignoring it,
    and asserts the prefix is actually present on the Gateway capture.

Usage:
    python3 scripts/verify_contract_parity.py
    python3 scripts/verify_contract_parity.py --http a.json --mcp b.json --agentcore c.json
    python3 scripts/verify_contract_parity.py --golden fixtures/tool-parity-golden.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Keys that legitimately differ per transport. Everything else must match.
VOLATILE_KEYS = {
    "invocation_id", "request_id", "run_id", "transport", "transport_trace_id",
    "trace_id", "start_time", "end_time", "created_at", "updated_at",
    "latency_ms", "duration_ms", "stage_timings", "stage_timings_illustrative",
    "tool_name",
}

ARMS = ("text", "vector", "fuzzy")


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize(value[k]) for k in sorted(value) if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def digest(value: Any) -> str:
    payload = json.dumps(normalize(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def strip_gateway_prefix(tool_name: str) -> str:
    """AgentCore Gateway exposes ${targetName}___${operationId} (three
    underscores), not the bare operationId. Normalize before comparing.
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html
    """
    return tool_name.split("___", 1)[1] if "___" in tool_name else tool_name


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------

def candidate_signature(doc: dict) -> list[tuple]:
    return [
        (r.get("evidence_id"), r.get("text_position"), r.get("vector_position"),
         r.get("fuzzy_position"), round(float(r.get("rrf_score", 0.0)), 6),
         r.get("fused_rank"), r.get("final_rank"))
        for r in doc.get("candidates", [])
    ]


def citation_signature(doc: dict) -> list[tuple]:
    return [
        (c.get("citation_number"), c.get("evidence_id"), c.get("external_key"),
         c.get("source_revision"),
         hashlib.sha256((c.get("quote") or "").encode("utf-8")).hexdigest()[:12])
        for c in doc.get("citations", [])
    ]


def verdict_signature(doc: dict) -> list[tuple]:
    return sorted((v.get("evidence_id"), v.get("verdict")) for v in doc.get("verdicts", []))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_not_vacuous(name: str, doc: dict) -> list[str]:
    """A comparison over empty collections is not evidence of parity."""
    errors = []
    if not doc.get("candidates"):
        errors.append(f"{name}: no candidates -- candidate parity would be vacuous")
    if not doc.get("citations"):
        errors.append(f"{name}: no citations -- citation parity would be vacuous")
    if not doc.get("verdicts"):
        errors.append(f"{name}: no verdicts -- verdict parity would be vacuous")
    if not doc.get("contract_version"):
        errors.append(f"{name}: no contract_version")
    return errors


def check_arithmetic(name: str, doc: dict, controls: dict) -> list[str]:
    """Recompute every rrf_score from its arm positions. Three transports that
    agree on a wrong number are still wrong."""
    errors = []
    k = controls.get("rrf_k", 60)
    weights = {"text": controls.get("text_weight", 2.0),
               "vector": controls.get("vector_weight", 1.0),
               "fuzzy": controls.get("fuzzy_weight", 1.0)}
    rows = doc.get("candidates", [])
    for r in rows:
        expect = 0.0
        for arm in ARMS:
            p = r.get(f"{arm}_position")
            if p is not None:
                expect += weights[arm] / (k + p)
        got = float(r.get("rrf_score", 0.0))
        if abs(expect - got) > 1e-6:
            errors.append(
                f"{name}: {r.get('evidence_id')} rrf_score={got:.8f} but "
                f"positions T={r.get('text_position')} V={r.get('vector_position')} "
                f"F={r.get('fuzzy_position')} with k={k} weights="
                f"{weights['text']}/{weights['vector']}/{weights['fuzzy']} give {expect:.8f}")

    ranks = sorted(r.get("fused_rank") for r in rows)
    if ranks != list(range(1, len(rows) + 1)):
        errors.append(f"{name}: fused_rank is not dense 1..{len(rows)} (got {ranks})")

    ordered = sorted(rows, key=lambda r: r.get("fused_rank") or 0)
    for a, b in zip(ordered, ordered[1:]):
        if float(a.get("rrf_score", 0)) < float(b.get("rrf_score", 0)):
            errors.append(f"{name}: fused_rank {a['evidence_id']}>{b['evidence_id']} "
                          f"contradicts rrf_score")

    if not controls.get("rerank", False):
        for r in rows:
            if r.get("final_rank") != r.get("fused_rank"):
                errors.append(f"{name}: rerank is off but {r.get('evidence_id')} has "
                              f"final_rank {r.get('final_rank')} != fused_rank {r.get('fused_rank')}")
    else:
        byfinal = sorted(rows, key=lambda r: r.get("final_rank") or 0)
        for a, b in zip(byfinal, byfinal[1:]):
            if (a.get("rerank_score") or 0) < (b.get("rerank_score") or 0):
                errors.append(f"{name}: final_rank {a['evidence_id']}>{b['evidence_id']} "
                              f"contradicts rerank_score")
    return errors


def check_against_golden(name: str, doc: dict, golden: dict) -> list[str]:
    errors = []
    if doc.get("contract_version") != golden.get("contract_version"):
        errors.append(f"{name}: contract_version {doc.get('contract_version')} != "
                      f"golden {golden.get('contract_version')}")

    order = [r.get("evidence_id") for r in
             sorted(doc.get("candidates", []), key=lambda r: r.get("fused_rank") or 0)]
    if order != golden.get("candidate_order"):
        errors.append(f"{name}: candidate order {order} != golden {golden.get('candidate_order')}")

    for r in doc.get("candidates", []):
        want = golden.get("positions", {}).get(r.get("evidence_id"))
        if want is None:
            errors.append(f"{name}: {r.get('evidence_id')} is not in the golden position map")
            continue
        got = {a: r.get(f"{a}_position") for a in ARMS}
        if got != want:
            errors.append(f"{name}: {r.get('evidence_id')} arm positions {got} != golden {want}")
        wants = golden.get("rrf_scores", {}).get(r.get("evidence_id"))
        if wants is not None and abs(float(r.get("rrf_score", 0)) - float(wants)) > 1e-6:
            errors.append(f"{name}: {r.get('evidence_id')} rrf_score "
                          f"{r.get('rrf_score')} != golden {wants}")

    cited = [c.get("evidence_id") for c in doc.get("citations", [])]
    if cited != golden.get("citation_ids"):
        errors.append(f"{name}: citation IDs {cited} != golden {golden.get('citation_ids')}")

    got_v = {v.get("evidence_id"): v.get("verdict") for v in doc.get("verdicts", [])}
    if got_v != golden.get("verdicts"):
        errors.append(f"{name}: verdicts {got_v} != golden {golden.get('verdicts')}")

    # ACL: restricted evidence must be ABSENT, not present and flagged.
    ids = {r.get("evidence_id") for r in doc.get("candidates", [])}
    for hidden in golden.get("hidden", []):
        if hidden in ids:
            errors.append(f"{name}: ACL-restricted {hidden} is present in the candidate set")
    for c in doc.get("citations", []):
        if c.get("evidence_id") in golden.get("hidden", []):
            errors.append(f"{name}: ACL-restricted {c.get('evidence_id')} is cited")
    return errors


def check_tool_naming(docs: dict[str, dict], golden: dict) -> list[str]:
    """Gateway exposes ${targetName}___${operationId}. Assert the prefix is
    there, and that stripping it recovers the same operationId everywhere."""
    errors = []
    expected_op = golden.get("tool")
    ac_name = docs.get("agentcore", {}).get("tool_name")
    if ac_name is None:
        errors.append("agentcore: capture has no tool_name -- cannot verify Gateway tool naming")
    elif "___" not in ac_name:
        errors.append(f"agentcore: tool_name {ac_name!r} has no '___' prefix; AgentCore Gateway "
                      f"exposes ${{targetName}}___${{operationId}}, so this is not a Gateway "
                      f"response or the target name is missing")
    elif ac_name != golden.get("gateway_tool_name"):
        errors.append(f"agentcore: tool_name {ac_name!r} != golden "
                      f"{golden.get('gateway_tool_name')!r}")

    for name, doc in docs.items():
        got = strip_gateway_prefix(doc.get("tool_name") or "")
        if got != expected_op:
            errors.append(f"{name}: operationId {got!r} != contract {expected_op!r}")
    return errors


def compare(name_a: str, a: dict, name_b: str, b: dict) -> list[str]:
    errors = []
    if a.get("contract_version") != b.get("contract_version"):
        errors.append(f"contract_version differs: {name_a}={a.get('contract_version')} "
                      f"{name_b}={b.get('contract_version')}")
    if candidate_signature(a) != candidate_signature(b):
        errors.append(f"candidate signature differs: {name_a} vs {name_b}")
    if citation_signature(a) != citation_signature(b):
        errors.append(f"citation signature differs: {name_a} vs {name_b}")
    if verdict_signature(a) != verdict_signature(b):
        errors.append(f"verdicts differ: {name_a} vs {name_b}")
    return errors


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(description="Compare Verity tool outputs across transports.")
    p.add_argument("--http", default=ROOT / "fixtures/captures/http.json")
    p.add_argument("--mcp", default=ROOT / "fixtures/captures/mcp.json")
    p.add_argument("--agentcore", default=ROOT / "fixtures/captures/agentcore.json")
    p.add_argument("--golden", default=ROOT / "fixtures/tool-parity-golden.json")
    args = p.parse_args()

    try:
        docs = {"http": load(args.http), "mcp": load(args.mcp), "agentcore": load(args.agentcore)}
        golden = load(args.golden)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"PARITY FAILED\n- could not load inputs: {exc}")
        raise SystemExit(2)

    controls = golden.get("controls", {})
    errors: list[str] = []

    for name, doc in docs.items():
        errors += check_not_vacuous(name, doc)
        errors += check_arithmetic(name, doc, controls)
        errors += check_against_golden(name, doc, golden)
    errors += check_tool_naming(docs, golden)
    errors += compare("http", docs["http"], "mcp", docs["mcp"])
    errors += compare("http", docs["http"], "agentcore", docs["agentcore"])

    http = docs["http"]
    print(f"contract        {golden.get('contract_version')}")
    print(f"operation       {golden.get('tool')}")
    print(f"gateway tool    {golden.get('gateway_tool_name')}")
    print(f"asserted        {len(http.get('candidates', []))} candidates, "
          f"{len(http.get('citations', []))} citations, "
          f"{len(http.get('verdicts', []))} verdicts, "
          f"{len(golden.get('hidden', []))} ACL-hidden")
    print(f"rerank          {'on' if controls.get('rerank') else 'off (no model call required)'}")
    print()
    for name, doc in docs.items():
        print(f"{name:10s} tool={str(doc.get('tool_name', '?')):42s} "
              f"normalized_sha256={digest(doc)}")

    if errors:
        print("\nPARITY FAILED")
        for e in dict.fromkeys(errors):
            print(f"- {e}")
        raise SystemExit(1)

    print("\nPARITY PASSED")
    print("  every rrf_score recomputed from its arm positions")
    print("  every transport compared to the golden, not only to the other transports")
    print("  gateway tool-name prefix present and normalized")


if __name__ == "__main__":
    main()
