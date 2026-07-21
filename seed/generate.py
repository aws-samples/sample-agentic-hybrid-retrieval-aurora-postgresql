#!/usr/bin/env python3
"""Generate the byte-identical workshop seed for the Orion hybrid-retrieval demo.

Two outputs, in this order:

  1. seed/artifacts/source_objects.jsonl  — all 150 objects (deterministic).
  2. seed/artifacts/hybrid-retrieval-seed-v1.dump — a `pg_dump -Fc` custom-format
     archive of the fully-populated `ops` schema (objects, chunks, 1024-d
     embeddings, links, citations, the canonical run + candidates, agent_answers,
     retrieval_run_metrics, evaluation queries + judgments).

The dump step needs a reachable Postgres 18 + pgvector >= 0.8.1 (local or
Aurora) via DATABASE_URL. Embeddings are computed OFFLINE — no Bedrock calls
during provisioning — using the deterministic `hash` provider by default (the
same one the backend uses when EMBED_PROVIDER=hash), or `bedrock` if explicitly
requested and credentials are available.

Usage:
  python seed/generate.py --jsonl-only            # write JSONL, skip DB/dump
  python seed/generate.py                          # JSONL + populate DB + dump
  python seed/generate.py --provider bedrock       # use Cohere embed-v4 (online)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ARTIFACTS = HERE / "artifacts"
BACKEND = ROOT / "backend"

# canonical + filler live next to this script
sys.path.insert(0, str(HERE))
# reuse the backend's embedding + chunking logic so the seed matches runtime
sys.path.insert(0, str(BACKEND))

import canonical as C  # noqa: E402
from filler import build_filler  # noqa: E402
from realformat import REAL_METADATA  # noqa: E402

from app.embeddings import embed_text, to_pgvector  # noqa: E402
from app.ingest import body_hash, chunk_text  # noqa: E402

ARTIFACT_NAME = "hybrid-retrieval-seed-v1.dump"
JSONL_NAME = "source_objects.jsonl"
MANIFEST_NAME = "manifest.json"
HERO_PREVIEW_NAME = "hero_preview.json"


# ---------------------------------------------------------------------------
# Assemble the 150-object corpus
# ---------------------------------------------------------------------------

def _named_object(o: dict) -> dict:
    """A cited or near-miss object → the SourceObject-shaped dict."""
    ext = o["external_id"]
    body = f"{o['title']}\n\n{o['snippet']}"
    return {
        "source_system": o["source_system"],
        "source_type": o["source_type"],
        "external_id": ext,
        "title": o["title"],
        "url": f"https://example.internal/{o['source_system']}/{ext}",
        "status": o.get("status"),
        "priority": o.get("priority"),
        "owner": o.get("owner"),
        "owner_team": o.get("owner_team"),
        "account_name": o.get("account_name"),
        "project_key": o.get("project_key"),
        "component": o.get("component"),
        "environment": o.get("environment"),
        "created_at": o.get("created_at"),
        "updated_at": o.get("updated_at"),
        "source_authority": o.get("source_authority", 0.70),
        "acl": {"visibility": "workshop_lab"},
        "metadata": REAL_METADATA.get(ext, {"workshop_seed": True}),
        "body": body,
    }


def assemble_corpus() -> list[dict]:
    objs: list[dict] = []
    for o in C.CITED:
        objs.append(_named_object(o))
    for o in C.NEAR_MISS:
        objs.append(_named_object(o))
    for o in build_filler():
        o = dict(o)
        o.setdefault("acl", {"visibility": "workshop_lab"})
        objs.append(o)
    return objs


def write_jsonl(objs: list[dict]) -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / JSONL_NAME
    with path.open("w", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(objs: list[dict], provider: str, artifact_sha256: str | None = None) -> Path:
    by_system: dict[str, int] = {}
    for o in objs:
        by_system[o["source_system"]] = by_system.get(o["source_system"], 0) + 1
    manifest = {
        "artifact": ARTIFACT_NAME,
        "version": "v1",
        "total_objects": len(objs),
        "per_system": by_system,
        "cited_order": [c["external_id"] for c in C.CITED],
        "canonical_question": C.CANONICAL_QUESTION,
        "run_slug": C.CANONICAL_RUN_SLUG,
        "embedding_provider": provider,
        "embedding_model": C.EMBEDDING_MODEL,
        "embedding_dim": C.EMBEDDING_DIM,
        "index_spec": C.INDEX_SPEC,
        "generated_stamp": C.SEED_STAMP,
    }
    if artifact_sha256:
        manifest["artifact_sha256"] = artifact_sha256
    path = ARTIFACTS / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_hero_preview() -> Path:
    """Write the landing-only preview from the canonical seed source.

    Keep one cited object per source system so the structural five-node hero can
    render while Aurora is unavailable. This is deliberately separate from the
    live canonical diagnostics payload and cannot start the guided walkthrough.
    """
    citations = []
    seen_systems: set[str] = set()
    for citation in C.CITED:
        system = citation["source_system"]
        if system in seen_systems:
            continue
        seen_systems.add(system)
        citations.append({
            "source_system": system,
            "source_type": citation["source_type"],
            "external_id": citation["external_id"],
            "title": citation["title"],
            "score": citation["final_score"],
        })
    preview = {
        "preview": True,
        "question": C.CANONICAL_QUESTION,
        "confidence": C.ANSWER_CONFIDENCE,
        "total_objects": C.CORPUS_TOTAL,
        "citations": citations,
    }
    path = ARTIFACTS / HERO_PREVIEW_NAME
    path.write_text(json.dumps(preview, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl-only", action="store_true", help="write JSONL + manifest only; skip DB + dump")
    parser.add_argument("--provider", choices=["hash", "bedrock"], default=os.environ.get("EMBED_PROVIDER", "hash"))
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--artifact", default=str(ARTIFACTS / ARTIFACT_NAME))
    args = parser.parse_args()

    objs = assemble_corpus()
    counts: dict[str, int] = {}
    for o in objs:
        counts[o["source_system"]] = counts.get(o["source_system"], 0) + 1

    jsonl = write_jsonl(objs)
    artifact_path = Path(args.artifact)
    artifact_sha256 = sha256_file(artifact_path) if artifact_path.exists() else None
    manifest = write_manifest(objs, args.provider, artifact_sha256=artifact_sha256)
    hero_preview = write_hero_preview()
    print(f"[seed] wrote {len(objs)} objects → {jsonl}")
    print(f"[seed] per-system: {counts}")
    print(f"[seed] manifest → {manifest}")
    print(f"[seed] hero preview → {hero_preview}")

    assert len(objs) == C.CORPUS_TOTAL, f"expected {C.CORPUS_TOTAL}, got {len(objs)}"
    for system, n in counts.items():
        assert n == C.PER_SYSTEM, f"{system} has {n}, expected {C.PER_SYSTEM}"
    cited_ext = {c["external_id"] for c in C.CITED}
    have = {o["external_id"] for o in objs}
    assert cited_ext <= have, f"missing cited objects: {cited_ext - have}"

    if args.jsonl_only:
        print("[seed] --jsonl-only: skipping DB populate + dump")
        return 0

    if not args.database_url:
        print("[seed] DATABASE_URL not set — skipping DB populate + dump.", file=sys.stderr)
        print("[seed] JSONL + manifest are ready; re-run with DATABASE_URL to build the dump.", file=sys.stderr)
        return 0

    from populate import populate_database  # local import; needs DB
    populate_database(args.database_url, objs, provider=args.provider,
                      embed_text=embed_text, to_pgvector=to_pgvector,
                      body_hash=body_hash, chunk_text=chunk_text)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    print(f"[seed] pg_dump -Fc → {args.artifact}")
    subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
         "--schema=ops", "--file", args.artifact, args.database_url],
        check=True,
    )
    size = artifact_path.stat().st_size
    manifest = write_manifest(objs, args.provider, artifact_sha256=sha256_file(artifact_path))
    print(f"[seed] artifact written: {args.artifact} ({size} bytes)")
    print(f"[seed] manifest updated with artifact SHA256 → {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
