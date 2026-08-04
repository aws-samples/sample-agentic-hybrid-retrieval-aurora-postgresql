from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import get_settings
from app.db import close_pool, get_owner_conn
from app.embeddings import hash_embedding
from app.search_index import EmbeddingCache, rebuild_search_index

DEFAULT_LIVE_CACHE = Path("data/generated/live-embeddings.jsonl")


def _stage_cache(cache_path: Path) -> Path:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=cache_path.parent,
        prefix=f".{cache_path.name}.",
        suffix=".building",
    )
    os.close(descriptor)
    staged_path = Path(temporary_name)
    if cache_path.exists():
        shutil.copyfile(cache_path, staged_path)
    return staged_path


def _publish_cache(
    staged_path: Path,
    cache_path: Path,
    *,
    model_id: str,
) -> dict[str, object]:
    cache = EmbeddingCache(staged_path)
    cache.load()
    manifest = cache.write_manifest(model_id=model_id)
    manifest["cache"] = cache_path.name
    cache.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    staged_path.replace(cache_path)
    cache.manifest_path.replace(
        cache_path.with_name(f"{cache_path.name}.manifest.json")
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the retrieval index from admitted live evidence."
    )
    parser.add_argument("--provider", choices=("bedrock", "hash"), default="bedrock")
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help=(
            "invoke the configured Bedrock embedding model for cache misses; "
            "this is billable and is never enabled implicitly"
        ),
    )
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument(
        "--cache",
        type=Path,
        help="runtime cache for embeddings generated from admitted live evidence",
    )
    parser.add_argument(
        "--verify-cache",
        action="store_true",
        help="require the runtime embedding cache to match its manifest",
    )
    parser.add_argument(
        "--write-cache-manifest",
        action="store_true",
        help="rewrite the runtime embedding cache manifest after indexing",
    )
    parser.add_argument(
        "--source-system",
        action="append",
        dest="source_systems",
        help=(
            "index only this authoritative source system; repeat for multiple "
            "sources. Out-of-scope current documents are left unchanged"
        ),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    if args.provider == "hash" and args.embed_missing:
        raise SystemExit("--embed-missing is only valid with --provider bedrock")
    if args.source_systems and args.write_cache_manifest:
        raise SystemExit(
            "--source-system cannot be combined with --write-cache-manifest"
        )

    settings = get_settings()
    if args.provider == "hash":
        model_id = "local-hash-embedding-v1"
        embed_missing = True
        embedder = lambda texts: [hash_embedding(text, dim=1024) for text in texts]
        default_cache = Path("data/generated/local-hash-embeddings.jsonl")
    else:
        model_id = settings.bedrock_embedding_model
        embed_missing = args.embed_missing
        embedder = None
        default_cache = DEFAULT_LIVE_CACHE
    cache_path = args.cache or default_cache

    # Verification reads the cache before indexing, so a run that also writes
    # to it proves nothing about the file it leaves behind.
    if args.verify_cache and embed_missing:
        raise SystemExit(
            "--verify-cache cannot be combined with a run that writes embeddings; "
            "embed first with --write-cache-manifest, then verify in a second run"
        )
    staged_cache_path: Path | None = None
    working_cache_path = cache_path
    if args.write_cache_manifest:
        staged_cache_path = _stage_cache(cache_path)
        working_cache_path = staged_cache_path

    try:
        with get_owner_conn() as conn:
            search_index = rebuild_search_index(
                conn,
                model_id=model_id,
                cache_path=working_cache_path,
                embed_missing=embed_missing,
                batch_size=args.batch_size,
                embedder=embedder,
                verify_cache=args.verify_cache,
                prune_unused_cache_entries=args.write_cache_manifest,
                source_systems=args.source_systems,
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT retrieval.assert_search_index_ready()")
                health = cursor.fetchone()[0]
        cache_manifest = None
        if args.write_cache_manifest:
            cache_manifest = _publish_cache(
                working_cache_path,
                cache_path,
                model_id=model_id,
            )
            staged_cache_path = None
        print(
            json.dumps(
                {
                    "search_index": search_index,
                    "cache_manifest": cache_manifest,
                    "health": health,
                },
                indent=2,
                default=str,
            )
        )
        return 0
    finally:
        if staged_cache_path is not None:
            staged_cache_path.unlink(missing_ok=True)
            EmbeddingCache(staged_cache_path).manifest_path.unlink(missing_ok=True)
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
