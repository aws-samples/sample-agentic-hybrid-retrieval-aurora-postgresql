from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from backend.app.search_index import (
    EmbeddingCache,
    EmbeddingCacheIntegrityError,
    chunk_text,
)
from backend.scripts.build_search_index import _publish_cache, _stage_cache


class ChunkTextTests(unittest.TestCase):
    def test_chunks_never_exceed_requested_size(self) -> None:
        chunks = chunk_text("word " * 1000, max_chars=120)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk.text) <= 120 for chunk in chunks))
        self.assertEqual(
            [chunk.ordinal for chunk in chunks],
            list(range(1, len(chunks) + 1)),
        )

    def test_empty_input_still_has_one_stable_chunk(self) -> None:
        chunks = chunk_text("")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].ordinal, 1)
        self.assertEqual(chunks[0].text, "")


class EmbeddingCacheTests(unittest.TestCase):
    def test_round_trip_is_model_and_text_hash_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.jsonl"
            cache = EmbeddingCache(path)
            cache.put("model-a", "hash-a", [0.0] * 1024)
            cache.save()

            loaded = EmbeddingCache(path)
            loaded.load()

            self.assertEqual(loaded.get("model-a", "hash-a"), [0.0] * 1024)
            self.assertIsNone(loaded.get("model-b", "hash-a"))
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["dimensions"], 1024)

    def test_retain_removes_superseded_and_other_model_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.jsonl"
            cache = EmbeddingCache(path)
            cache.put("model-a", "current", [0.0] * 1024)
            cache.put("model-a", "superseded", [0.1] * 1024)
            cache.put("model-b", "current", [0.2] * 1024)

            removed = cache.retain("model-a", {"current"})

            self.assertEqual(removed, 2)
            self.assertEqual(cache.get("model-a", "current"), [0.0] * 1024)
            self.assertIsNone(cache.get("model-a", "superseded"))
            self.assertIsNone(cache.get("model-b", "current"))

    def test_release_cache_is_staged_until_explicit_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.jsonl"
            original = EmbeddingCache(path)
            original.put("model-a", "old", [0.0] * 1024)
            original.save()
            original.write_manifest(model_id="model-a")

            staged_path = _stage_cache(path)
            staged = EmbeddingCache(staged_path)
            staged.load()
            staged.put("model-a", "new", [0.1] * 1024)
            staged.save()

            untouched = EmbeddingCache(path)
            untouched.load()
            self.assertIsNone(untouched.get("model-a", "new"))

            manifest = _publish_cache(
                staged_path,
                path,
                model_id="model-a",
            )
            published = EmbeddingCache(path)
            published.load()
            self.assertEqual(published.get("model-a", "new"), [0.1] * 1024)
            self.assertEqual(manifest["cache"], "cache.jsonl")
            self.assertEqual(published.verify()["cache"], "cache.jsonl")


class EmbeddingCacheManifestTests(unittest.TestCase):
    def _seeded_cache(self, directory: str) -> EmbeddingCache:
        cache = EmbeddingCache(Path(directory) / "cache.jsonl")
        cache.put("model-a", "hash-a", [0.25] * 1024)
        cache.put("model-a", "hash-b", [0.5] * 1024)
        cache.save()
        cache.write_manifest(model_id="model-a")
        return cache

    def test_untampered_cache_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            written = self._seeded_cache(directory)

            loaded = EmbeddingCache(written.path)
            loaded.load()
            manifest = loaded.verify()

            self.assertEqual(manifest["entry_count"], 2)
            self.assertEqual(manifest["model_id"], "model-a")

    def test_digest_is_independent_of_line_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            written = self._seeded_cache(directory)
            lines = written.path.read_text(encoding="utf-8").splitlines()
            written.path.write_text(
                "\n".join(reversed(lines)) + "\n",
                encoding="utf-8",
            )

            reordered = EmbeddingCache(written.path)
            reordered.load()

            self.assertEqual(reordered.verify()["entry_count"], 2)

    def test_truncated_cache_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            written = self._seeded_cache(directory)
            first = written.path.read_text(encoding="utf-8").splitlines()[0]
            written.path.write_text(first + "\n", encoding="utf-8")

            truncated = EmbeddingCache(written.path)
            truncated.load()

            with self.assertRaises(EmbeddingCacheIntegrityError) as caught:
                truncated.verify()
            self.assertIn("declares 2", str(caught.exception))

    def test_edited_vector_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            written = self._seeded_cache(directory)
            records = [
                json.loads(line)
                for line in written.path.read_text(encoding="utf-8").splitlines()
            ]
            records[0]["embedding"][0] = 0.9
            written.path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )

            edited = EmbeddingCache(written.path)
            edited.load()

            with self.assertRaises(EmbeddingCacheIntegrityError) as caught:
                edited.verify()
            self.assertIn("content digest", str(caught.exception))

    def test_missing_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            written = self._seeded_cache(directory)
            written.manifest_path.unlink()

            loaded = EmbeddingCache(written.path)
            loaded.load()

            with self.assertRaises(EmbeddingCacheIntegrityError) as caught:
                loaded.verify()
            self.assertIn("is missing", str(caught.exception))


class ReleaseCacheGuardTests(unittest.TestCase):
    """The release cache ships to every account, so no test run may write to it."""

    def _build(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "backend/scripts/build_search_index.py", *arguments],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        )

    def test_verify_cache_rejects_a_run_that_also_embeds(self) -> None:
        completed = self._build("--verify-cache", "--embed-missing")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("cannot be combined", completed.stderr)

    def test_embedding_into_release_cache_requires_manifest_rewrite(self) -> None:
        completed = self._build("--embed-missing")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("refusing to add embeddings to the release cache", completed.stderr)

    def test_hash_provider_may_not_target_the_release_cache(self) -> None:
        from backend.scripts.build_search_index import RELEASE_CACHE

        completed = self._build("--provider", "hash", "--cache", str(RELEASE_CACHE))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("refusing to add embeddings to the release cache", completed.stderr)


if __name__ == "__main__":
    unittest.main()
