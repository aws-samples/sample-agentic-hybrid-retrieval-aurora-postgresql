from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import get_settings
from app.db import close_pool, get_conn
from app.embeddings import hash_embedding
from app.search_index import EmbeddingCache, rebuild_search_index
from seed.capture import capture_offline_lock_fixture, validate_capture_bundle
from seed.corpus import load_casework

RELEASE_CACHE = Path("seed/artifacts/casework-embeddings.jsonl")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load deterministic casework and rebuild its search index."
    )
    parser.add_argument("--load-casework", action="store_true")
    parser.add_argument("--background-documents", type=int, default=15000)
    capture_group = parser.add_mutually_exclusive_group()
    capture_group.add_argument(
        "--capture-bundle",
        type=Path,
        help="load a previously captured PostgreSQL/Aurora incident bundle",
    )
    capture_group.add_argument(
        "--offline-capture",
        action="store_true",
        help=(
            "generate genuine local PostgreSQL lock evidence labeled offline_test; "
            "this can never satisfy the Aurora release gate"
        ),
    )
    parser.add_argument("--offline-capture-rows", type=int, default=25000)
    parser.add_argument(
        "--require-release-capture",
        action="store_true",
        help="reject any capture bundle not labeled and validated as release_aurora",
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
        help="embedding cache path; defaults to the release artifact for "
        "--provider bedrock and to a local scratch cache for --provider hash",
    )
    parser.add_argument(
        "--verify-cache",
        action="store_true",
        help=(
            "require the embedding cache to match its shipped manifest before "
            "indexing, so every workshop account ranks identically"
        ),
    )
    parser.add_argument(
        "--write-cache-manifest",
        action="store_true",
        help="rewrite the cache manifest after indexing; use when regenerating "
        "the release artifact",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.background_documents < 0:
        raise SystemExit("--background-documents must be non-negative")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    if args.offline_capture_rows < 1000:
        raise SystemExit("--offline-capture-rows must be at least 1000")
    if args.provider == "hash" and args.embed_missing:
        raise SystemExit("--embed-missing is only valid with --provider bedrock")
    if args.load_casework and not (args.capture_bundle or args.offline_capture):
        raise SystemExit(
            "--load-casework requires --capture-bundle or --offline-capture"
        )
    if args.require_release_capture and not args.capture_bundle:
        raise SystemExit("--require-release-capture requires --capture-bundle")

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
        default_cache = RELEASE_CACHE
    cache_path = args.cache or default_cache

    # Verification reads the cache before indexing, so a run that also writes
    # to it proves nothing about the file it leaves behind.
    if args.verify_cache and embed_missing:
        raise SystemExit(
            "--verify-cache cannot be combined with a run that writes embeddings; "
            "embed first with --write-cache-manifest, then verify in a second run"
        )
    if embed_missing and cache_path == RELEASE_CACHE and not args.write_cache_manifest:
        raise SystemExit(
            f"refusing to add embeddings to the release cache {RELEASE_CACHE} "
            "without --write-cache-manifest, which would leave the shipped "
            "manifest stale; pass --cache <scratch path> for test seeding"
        )

    try:
        capture_bundle = None
        if args.capture_bundle:
            capture_bundle = json.loads(
                args.capture_bundle.read_text(encoding="utf-8")
            )
            validate_capture_bundle(
                capture_bundle,
                require_release=args.require_release_capture,
            )
        elif args.offline_capture:
            capture_bundle = capture_offline_lock_fixture(
                settings.database_url,
                row_count=args.offline_capture_rows,
            )

        with get_conn() as conn:
            casework = None
            if args.load_casework:
                casework = load_casework(
                    conn,
                    capture_bundle=capture_bundle,
                    background_documents=args.background_documents,
                )
            search_index = rebuild_search_index(
                conn,
                model_id=model_id,
                cache_path=cache_path,
                embed_missing=embed_missing,
                batch_size=args.batch_size,
                embedder=embedder,
                verify_cache=args.verify_cache,
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT retrieval.assert_search_index_ready()")
                health = cursor.fetchone()[0]
        cache_manifest = None
        if args.write_cache_manifest:
            cache = EmbeddingCache(cache_path)
            cache.load()
            cache_manifest = cache.write_manifest(model_id=model_id)
        print(
            json.dumps(
                {
                    "casework": casework,
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
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
