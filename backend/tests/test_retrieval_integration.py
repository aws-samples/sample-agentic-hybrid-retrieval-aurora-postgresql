from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from backend.app.config import get_settings
from backend.app.embeddings import hash_embedding, to_pgvector
from backend.app.search_index import rebuild_search_index
from seed.capture import capture_offline_lock_fixture
from seed.corpus import evidence_id, load_casework


def _database_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _assert_disposable_test_database() -> None:
    """Refuse to reseed anything but an explicitly named test database.

    ``setUpClass`` TRUNCATEs every casework, retrieval, and proof table and
    rebuilds the corpus. Two independent things must therefore agree before it
    runs: the URL this module was handed, and the URL the application code
    resolved through ``get_settings()``. They can diverge because pytest imports
    sibling test modules first, which loads ``backend.app.config`` before this
    module gets to export ``DATABASE_URL``.

    Raises:
        RuntimeError: If the two URLs disagree, or the target database name does
            not end in ``_test`` -- the marker that says the database is
            disposable rather than the live workshop corpus.
    """
    resolved = get_settings().database_url
    if resolved != TEST_DATABASE_URL:
        raise RuntimeError(
            "the application resolved a different database than the test target; "
            f"tests target {_database_name(TEST_DATABASE_URL)!r} but the app "
            f"resolved {_database_name(resolved)!r}. Destructive tests must never "
            "run against a database the application picked up from .env."
        )
    name = _database_name(TEST_DATABASE_URL)
    if not name.endswith("_test"):
        raise RuntimeError(
            f"refusing to reseed database {name!r}: these tests TRUNCATE every "
            "casework, retrieval, and proof table. Point TEST_DATABASE_URL at a "
            "disposable database whose name ends in '_test'."
        )


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _apply_schema(connection: psycopg.Connection) -> None:
    """Apply every versioned SQL file before seeding.

    Retrieval, ranking, and ACL enforcement live in SQL, so a test that runs
    against whatever was last applied by hand is testing an unknown revision. The
    files are idempotent (CREATE OR REPLACE, IF NOT EXISTS), and applying them
    here means editing SQL is enough to make the suite exercise the change.

    Args:
        connection: An open connection to the disposable test database.
    """
    # Apply every versioned migration NN_*.sql except 99_reset.sql, which drops
    # all three schemas. This matches what `make schema` applies.
    files = sorted(
        path
        for path in (REPOSITORY_ROOT / "sql").glob("[0-9][0-9]_*.sql")
        if not path.name.startswith("99")
    )
    if not files:
        raise RuntimeError(f"no versioned SQL files found in {REPOSITORY_ROOT / 'sql'}")
    with connection.cursor() as cursor:
        for path in files:
            cursor.execute(path.read_text(encoding="utf-8"))
    connection.commit()


@unittest.skipUnless(
    TEST_DATABASE_URL and os.environ.get("ALLOW_TEST_DATABASE_RESET") == "1",
    "set TEST_DATABASE_URL and ALLOW_TEST_DATABASE_RESET=1 for database contract tests",
)
class RetrievalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _assert_disposable_test_database()
        cls.conn = psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row)
        _apply_schema(cls.conn)
        cls.capture_bundle = capture_offline_lock_fixture(
            TEST_DATABASE_URL,
            row_count=1000,
        )
        cls.casework_receipt = load_casework(
            cls.conn,
            capture_bundle=cls.capture_bundle,
            background_documents=200,
        )
        cls.cache_dir = tempfile.TemporaryDirectory()
        cls.receipt = rebuild_search_index(
            cls.conn,
            model_id="local-hash-embedding-v1",
            cache_path=Path(cls.cache_dir.name) / "embeddings.jsonl",
            embed_missing=True,
            embedder=lambda texts: [hash_embedding(text, dim=1024) for text in texts],
        )

    @classmethod
    def tearDownClass(cls) -> None:
        from backend.app.db import close_pool

        close_pool()
        cls.conn.close()
        cls.cache_dir.cleanup()

    def tearDown(self) -> None:
        self.conn.rollback()

    def test_search_index_is_ready_and_idempotent(self) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT retrieval.assert_search_index_ready() AS health")
            health = cursor.fetchone()["health"]

        self.assertEqual(health["status"], "ready")
        self.assertEqual(health["drift_issues"], 0)
        self.assertEqual(health["source_documents"], health["current_documents"])

        second = rebuild_search_index(
            self.conn,
            model_id="local-hash-embedding-v1",
            cache_path=Path(self.cache_dir.name) / "embeddings.jsonl",
            embed_missing=False,
        )
        self.assertEqual(second["documents_indexed"], 0)
        self.assertEqual(
            second["documents_skipped"],
            health["source_documents"],
        )

    def test_search_wrapper_persists_candidate_receipt(self) -> None:
        from backend.app.models import SearchRequest
        from backend.app.search import run_hybrid_search

        result = run_hybrid_search(
            SearchRequest(
                query="Why did CHG-1842 block writes on checkout-prod-cluster-01?",
                mode="lexical",
                cluster_id="checkout-prod-cluster-01",
                rerank=False,
                limit=5,
            )
        )
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM proof.v_run_receipts WHERE run_id = %s",
                (result["run_id"],),
            )
            receipt = cursor.fetchone()
            cursor.execute(
                """
                SELECT external_key
                FROM proof.v_candidate_receipts
                WHERE run_id = %s
                ORDER BY result_rank
                """,
                (result["run_id"],),
            )
            candidates = cursor.fetchall()
            cursor.execute(
                """
                SELECT window_start, window_end
                FROM proof.observability_refs
                WHERE run_id = %s
                """,
                (result["run_id"],),
            )
            observability_ref = cursor.fetchone()

        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["candidate_count"], len(candidates))
        self.assertEqual(receipt["role"], "analyst")
        self.assertGreaterEqual(receipt["candidate_count"], 1)
        self.assertLessEqual(receipt["candidate_count"], 5)
        self.assertEqual(candidates[0]["external_key"], "CHG-1842")
        self.assertIsNotNone(observability_ref)
        self.assertIsNotNone(observability_ref["window_start"])
        self.assertIsNotNone(observability_ref["window_end"])

    def test_synthesis_tool_reloads_evidence_from_run(self) -> None:
        from backend.app.agent import (
            explain_ranking_impl,
            synthesize_cited_answer_from_run_impl,
        )
        from backend.app.insights import latest_cited_run
        from backend.app.models import SearchRequest
        from backend.app.search import run_hybrid_search

        search = run_hybrid_search(
            SearchRequest(
                query="CHG-1842",
                mode="lexical",
                rerank=False,
                limit=4,
            )
        )
        with patch(
            "backend.app.synthesis.synthesize_live",
            return_value={
                "answer": "CHG-1842 is the persisted top-ranked change [1].",
                "model": "test-model",
                "transport": "test",
                "usage": {},
            },
        ):
            result = synthesize_cited_answer_from_run_impl(
                "What did CHG-1842 do?",
                search["run_id"],
                limit=4,
            )

        self.assertEqual(result["citations"][0]["external_key"], "CHG-1842")
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM proof.validate_answer_citations(%s)",
                (search["run_id"],),
            )
            validation = cursor.fetchall()
        self.assertTrue(validation)
        self.assertTrue(all(row["is_valid"] for row in validation))
        replay = explain_ranking_impl(search["run_id"])
        self.assertEqual(
            replay["answer"]["answer_text"],
            "CHG-1842 is the persisted top-ranked change [1].",
        )
        self.assertEqual(
            replay["answer"]["citations"][0]["external_key"],
            "CHG-1842",
        )
        self.assertEqual(
            replay["answer"]["citations"][0]["document_version_id"],
            result["citations"][0]["document_version_id"],
        )
        self.assertEqual(
            replay["answer"]["citations"][0]["chunk_version_id"],
            result["citations"][0]["chunk_version_id"],
        )
        self.assertEqual(replay["answer"]["validation_status"], "valid")
        self.assertEqual(str(latest_cited_run()["run_id"]), search["run_id"])

    def test_evaluation_separates_retrieval_from_traversal(self) -> None:
        from backend.app.evaluation import run_evaluation

        result = run_evaluation(modes=["lexical"], limit=10)
        traversal = next(
            query
            for query in result["queries"]
            if query["query_id"] == "customer-impact"
        )
        receipt = traversal["results"][0]

        self.assertEqual(result["retrieval_query_count"], 3)
        self.assertEqual(result["traversal_query_count"], 1)
        self.assertEqual(traversal["evaluation_type"], "traversal")
        self.assertEqual(receipt["metrics"]["recall"], 1.0)
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT item.external_key
                FROM proof.traversal_results result
                JOIN casework.evidence_items item
                  ON item.evidence_id = result.evidence_id
                WHERE result.run_id = %s
                """,
                (receipt["run_id"],),
            )
            reached = {row["external_key"] for row in cursor.fetchall()}
        self.assertIn("CASE-7419", reached)
        self.assertNotIn("CASE-7421", reached)

    def test_relationship_traversal_enforces_acl(self) -> None:
        from backend.app.agent import follow_evidence_links_impl

        analyst = follow_evidence_links_impl(
            ["INC-2047"],
            role="analyst",
            max_depth=2,
        )
        admin = follow_evidence_links_impl(
            ["INC-2047"],
            role="admin",
            max_depth=2,
        )

        analyst_keys = {row["external_key"] for row in analyst["reached"]}
        admin_keys = {row["external_key"] for row in admin["reached"]}
        self.assertNotIn("CASE-7421", analyst_keys)
        self.assertIn("CASE-7421", admin_keys)

    def test_evidence_detail_endpoint_enforces_acl(self) -> None:
        from fastapi import HTTPException

        from backend.app.main import evidence_detail

        restricted = str(evidence_id("support_case", "CASE-7421"))
        with self.assertRaises(HTTPException) as ctx:
            evidence_detail(restricted)
        self.assertEqual(ctx.exception.status_code, 404)

        visible = evidence_detail(str(evidence_id("incident", "INC-2047")))
        self.assertEqual(visible["evidence"]["external_key"], "INC-2047")

    def test_exact_identifier_leads_lexical_arm(self) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT external_key, explanation
                FROM retrieval.full_text_search(
                  %s,
                  p_limit => 5
                )
                """,
                ("Why did CHG-1842 block writes on checkout-prod-cluster-01?",),
            )
            rows = cursor.fetchall()

        self.assertEqual(rows[0]["external_key"], "CHG-1842")
        self.assertTrue(rows[0]["explanation"]["exact_identifier"])

    def test_excluded_terms_narrow_the_lexical_arm(self) -> None:
        # The arm ORs positive terms so a natural-language question can rank at
        # all. Negation is still a filter: ORing it in would make "-staging"
        # match every document that merely lacks the word.
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  count(*) FILTER (
                    WHERE search_tsv @@ retrieval.to_or_tsquery('index build lock')
                  ) AS plain,
                  count(*) FILTER (
                    WHERE search_tsv @@ retrieval.to_or_tsquery(
                      'index build lock -staging'
                    )
                  ) AS excluded,
                  count(*) AS total
                FROM retrieval.chunks
                """
            )
            counts = cursor.fetchone()
            cursor.execute(
                """
                SELECT
                  retrieval.to_or_tsquery('checkout writes blocked')::text AS ored,
                  retrieval.to_or_tsquery('lock -staging')::text AS negated,
                  retrieval.to_or_tsquery('lock -"create index"')::text AS phrase,
                  retrieval.to_or_tsquery('CHG-1842 blocked')::text AS hyphenated
                """
            )
            rendered = cursor.fetchone()

        self.assertLess(counts["excluded"], counts["plain"])
        self.assertLess(counts["excluded"], counts["total"])
        self.assertEqual(rendered["ored"], "'checkout' | 'write' | 'block'")
        self.assertEqual(rendered["negated"], "'lock' & !'stage'")
        self.assertEqual(rendered["phrase"], "'lock' & !( 'creat' <-> 'index' )")
        # A hyphen inside a token is part of the identifier, not an exclusion.
        self.assertNotIn("!", rendered["hyphenated"])

    def test_fuzzy_arm_recovers_mistyped_identifier(self) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT external_key
                FROM retrieval.fuzzy_search(
                  %s,
                  p_limit => 5
                )
                """,
                (["CGH-1842"],),
            )
            rows = cursor.fetchall()

        self.assertEqual(rows[0]["external_key"], "CHG-1842")

    def test_restricted_identifier_never_enters_fuzzy_probes(self) -> None:
        from backend.app.models import SearchRequest
        from backend.app.search import _resolve_fuzzy_probe_tokens

        request = SearchRequest(query="What happened on CASE-7421?", mode="hybrid")
        self.assertEqual(
            _resolve_fuzzy_probe_tokens(request, ["CASE-7421"]),
            [],
        )
        self.assertEqual(
            _resolve_fuzzy_probe_tokens(request, ["CGH-1842"]),
            ["CGH-1842"],
        )

    def test_restricted_identifier_yields_no_visible_evidence(self) -> None:
        from backend.app.models import SearchRequest
        from backend.app.search import run_hybrid_search

        query = "CASE-7421"
        with (
            patch(
                "backend.app.search._query_embedding_model",
                return_value="local-hash-embedding-v1",
            ),
            patch(
                "backend.app.search.embed_text",
                return_value=hash_embedding(query),
            ),
        ):
            result = run_hybrid_search(
                SearchRequest(query=query, rerank=False, limit=8)
            )

        self.assertEqual(result["knobs"]["identifier_tokens"], ["CASE-7421"])
        self.assertEqual(result["knobs"]["fuzzy_probe_tokens"], [])
        returned = {row["external_key"] for row in result["results"]}
        self.assertNotIn("CASE-7421", returned)
        self.assertTrue(
            all(row.get("trigram_score") is None for row in result["results"]),
            "the trigram arm must not substitute near neighbours for a "
            "restricted identifier",
        )

    def test_chunk_acl_scalars_match_their_document(self) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)::integer AS mismatched
                FROM retrieval.chunks chunk
                JOIN retrieval.documents document
                  ON document.document_version_id = chunk.document_version_id
                WHERE chunk.acl IS DISTINCT FROM document.acl
                   OR chunk.acl_visibility IS DISTINCT FROM document.acl_visibility
                   OR chunk.acl_principals IS DISTINCT FROM document.acl_principals
                """
            )
            self.assertEqual(cursor.fetchone()["mismatched"], 0)

    def test_generated_corpus_has_unique_search_surfaces(self) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  count(*) AS evidence_items,
                  count(DISTINCT evidence_id) AS evidence_ids,
                  count(DISTINCT external_key) AS external_keys
                FROM casework.evidence_items
                """
            )
            source = cursor.fetchone()
            cursor.execute(
                """
                SELECT
                  count(*) AS documents,
                  count(DISTINCT search_document_hash) AS search_document_hashes
                FROM retrieval.documents
                WHERE is_current
                """
            )
            documents = cursor.fetchone()
            cursor.execute(
                """
                SELECT
                  count(*) AS chunks,
                  count(DISTINCT chunk.chunk_hash) AS chunk_hashes,
                  count(DISTINCT chunk.embedding::text) AS embeddings
                FROM retrieval.chunks chunk
                JOIN retrieval.documents document
                  ON document.document_version_id = chunk.document_version_id
                WHERE document.is_current
                """
            )
            chunks = cursor.fetchone()

        expected = self.casework_receipt["evidence_items"]
        self.assertEqual(source["evidence_items"], expected)
        self.assertEqual(source["evidence_ids"], expected)
        self.assertEqual(source["external_keys"], expected)
        self.assertEqual(documents["documents"], expected)
        self.assertEqual(documents["search_document_hashes"], expected)
        self.assertEqual(chunks["chunks"], expected)
        self.assertEqual(chunks["chunk_hashes"], expected)
        self.assertEqual(chunks["embeddings"], expected)

    def test_acl_is_applied_before_retrieval(self) -> None:
        query = "Northstar premium checkout escalation"
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT external_key
                FROM retrieval.full_text_search(
                  %s,
                  p_role => 'persona_analyst',
                  p_limit => 50
                )
                """,
                (query,),
            )
            analyst = {row["external_key"] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT external_key
                FROM retrieval.full_text_search(
                  %s,
                  p_role => 'persona_admin',
                  p_limit => 50
                )
                """,
                (query,),
            )
            admin = {row["external_key"] for row in cursor.fetchall()}

        self.assertNotIn("CASE-7421", analyst)
        self.assertIn("CASE-7421", admin)

    def test_canonical_search_functions_have_one_signature_each(self) -> None:
        expected = {
            "full_text_search": (14, 13),
            "vector_search": (15, 14),
            "fuzzy_search": (15, 14),
            "hybrid_search": (22, 20),
        }
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  procedure.proname,
                  count(*)::integer AS overloads,
                  min(procedure.pronargs)::integer AS arguments,
                  min(procedure.pronargdefaults)::integer AS defaults
                FROM pg_proc procedure
                JOIN pg_namespace namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'retrieval'
                  AND procedure.proname = ANY(%s)
                GROUP BY procedure.proname
                """,
                (list(expected),),
            )
            signatures = {
                row["proname"]: (
                    row["overloads"],
                    row["arguments"],
                    row["defaults"],
                )
                for row in cursor.fetchall()
            }

        self.assertEqual(
            signatures,
            {
                name: (1, arguments, defaults)
                for name, (arguments, defaults) in expected.items()
            },
        )

    def test_default_hybrid_ranks_confirmed_change_first(self) -> None:
        query = "Why did CHG-1842 block writes on checkout-prod-cluster-01?"
        vector = to_pgvector(hash_embedding(query))
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT external_key, match_tier, exact_identifier_position,
                       explanation
                FROM retrieval.hybrid_search(
                  %s,
                  %s::vector,
                  p_cluster_id => 'checkout-prod-cluster-01',
                  p_limit => 8
                )
                """,
                (query, vector),
            )
            rows = cursor.fetchall()

        self.assertEqual(rows[0]["external_key"], "CHG-1842")
        self.assertEqual(rows[0]["match_tier"], 1)
        self.assertEqual(rows[0]["exact_identifier_position"], 1)
        self.assertEqual(
            rows[0]["explanation"]["match_tier_label"],
            "exact_identifier",
        )
        self.assertEqual(
            rows[0]["explanation"]["positions"]["exact_identifier"],
            1,
        )
        self.assertNotIn("exact_identifier_rrf", rows[0]["explanation"]["signals"])
        self.assertEqual(
            rows[0]["explanation"]["weights"],
            {"full_text": 2.0, "semantic": 1.0, "fuzzy": 1.0},
        )
        self.assertEqual(rows[0]["explanation"]["rrf_k"], 60)
        self.assertTrue(
            all(row["match_tier"] == 2 for row in rows[1:]),
            "only the resolved identifier belongs to the exact tier",
        )

    def test_every_rrf_score_reproduces_from_the_published_formula(self) -> None:
        query = "Why did CHG-1842 block writes on checkout-prod-cluster-01?"
        vector = to_pgvector(hash_embedding(query))
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT external_key, text_position, vector_position,
                       trigram_position, rrf_score, final_score
                FROM retrieval.hybrid_search(
                  %s,
                  %s::vector,
                  p_cluster_id => 'checkout-prod-cluster-01',
                  p_limit => 8
                )
                """,
                (query, vector),
            )
            rows = cursor.fetchall()

        self.assertTrue(rows)
        for row in rows:
            expected = sum(
                weight / (60 + row[column])
                for weight, column in (
                    (2.0, "text_position"),
                    (1.0, "vector_position"),
                    (1.0, "trigram_position"),
                )
                if row[column] is not None
            )
            self.assertAlmostEqual(
                float(row["rrf_score"]),
                expected,
                places=12,
                msg=f"{row['external_key']} does not match the 3-term formula",
            )
            self.assertEqual(row["rrf_score"], row["final_score"])

    def test_no_weighting_can_demote_a_named_identifier(self) -> None:
        """A zero text weight and a maximal vector weight must not move CHG-1842.

        The vector arm is fed the embedding of a competing change so that the
        distractor legitimately wins the semantic arm. Before the exact tier
        existed this combination put CHG-1907 above CHG-1842.
        """
        query = "Why did CHG-1842 block writes on checkout-prod-cluster-01?"
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT chunk.embedding
                FROM retrieval.chunks chunk
                JOIN retrieval.documents document
                  ON document.document_version_id = chunk.document_version_id
                WHERE document.external_key = 'CHG-1907'
                  AND chunk.is_current
                LIMIT 1
                """
            )
            distractor_embedding = cursor.fetchone()["embedding"]
            cursor.execute(
                """
                SELECT external_key, match_tier, rrf_score
                FROM retrieval.hybrid_search(
                  %s,
                  %s::vector,
                  p_cluster_id => 'checkout-prod-cluster-01',
                  p_limit => 6,
                  p_w_text => 0.0,
                  p_w_vector => 10.0
                )
                """,
                (query, distractor_embedding),
            )
            rows = cursor.fetchall()

        self.assertEqual(rows[0]["external_key"], "CHG-1842")
        self.assertEqual(rows[0]["match_tier"], 1)
        distractor = next(row for row in rows if row["external_key"] == "CHG-1907")
        self.assertGreater(
            float(distractor["rrf_score"]),
            float(rows[0]["rrf_score"]),
            "the test is only meaningful while the distractor outscores the "
            "exact match on weighted RRF",
        )

    def test_hybrid_persists_independent_arm_positions(self) -> None:
        vector = to_pgvector(
            hash_embedding("Why did CHG-1842 block writes on checkout-prod-cluster-01?")
        )
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT external_key, text_position, vector_position,
                       trigram_position, final_score, explanation
                FROM retrieval.hybrid_search(
                  %s,
                  %s::vector,
                  p_cluster_id => 'checkout-prod-cluster-01',
                  p_limit => 8
                )
                """,
                (
                    "Why did CHG-1842 block writes on checkout-prod-cluster-01?",
                    vector,
                ),
            )
            rows = cursor.fetchall()

        match = next(row for row in rows if row["external_key"] == "CHG-1842")
        self.assertEqual(match["text_position"], 1)
        self.assertAlmostEqual(
            float(match["final_score"]),
            float(match["explanation"]["signals"]["rrf"]),
            places=12,
        )

    def test_hybrid_receipt_persists_default_fusion_controls(self) -> None:
        from backend.app.models import SearchRequest
        from backend.app.search import run_hybrid_search

        query = "Why did CHG-1842 block writes on checkout-prod-cluster-01?"
        with (
            patch(
                "backend.app.search._query_embedding_model",
                return_value="local-hash-embedding-v1",
            ),
            patch(
                "backend.app.search.embed_text",
                return_value=hash_embedding(query),
            ),
        ):
            result = run_hybrid_search(
                SearchRequest(
                    query=query,
                    cluster_id="checkout-prod-cluster-01",
                    rerank=False,
                    limit=5,
                )
            )

        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  rrf_k,
                  text_weight,
                  vector_weight,
                  fuzzy_weight,
                  fuzzy_threshold
                FROM proof.v_run_receipts
                WHERE run_id = %s
                """,
                (result["run_id"],),
            )
            receipt = cursor.fetchone()

        self.assertEqual(result["results"][0]["external_key"], "CHG-1842")
        self.assertEqual(result["knobs"]["rrf_k"], 60)
        self.assertEqual(
            result["knobs"]["weights"],
            {"text": 2.0, "vector": 1.0, "fuzzy": 1.0},
        )
        self.assertEqual(result["knobs"]["fuzzy_threshold"], 0.3)
        self.assertEqual(receipt["rrf_k"], 60)
        self.assertEqual(float(receipt["text_weight"]), 2.0)
        self.assertEqual(float(receipt["vector_weight"]), 1.0)
        self.assertEqual(float(receipt["fuzzy_weight"]), 1.0)
        self.assertAlmostEqual(float(receipt["fuzzy_threshold"]), 0.3)
        self.assertEqual(
            result["match_tiers"],
            [
                {
                    "tier": 1,
                    "label": "Exact identifier",
                    "count": 1,
                    "first_rank": 1,
                    "last_rank": 1,
                },
                {
                    "tier": 2,
                    "label": "Fused candidates",
                    "count": 4,
                    "first_rank": 2,
                    "last_rank": 5,
                },
            ],
        )

        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT result_rank, external_key, match_tier,
                       exact_identifier_position
                FROM proof.v_candidate_receipts
                WHERE run_id = %s
                ORDER BY result_rank
                """,
                (result["run_id"],),
            )
            candidates = cursor.fetchall()

        self.assertEqual(candidates[0]["external_key"], "CHG-1842")
        self.assertEqual(candidates[0]["match_tier"], 1)
        self.assertEqual(candidates[0]["exact_identifier_position"], 1)
        self.assertTrue(all(row["match_tier"] == 2 for row in candidates[1:]))

    def test_agent_coverage_escalates_only_the_starved_runbook(self) -> None:
        from backend.app.agent import answer_question, get_agent_coverage_impl
        from backend.app.models import AgentAnswerRequest

        question = (
            "During INC-2047 on checkout-prod-cluster-01, why did checkout writes "
            "appear to hang while reads continued? Determine whether CHG-1842 "
            "or CHG-1838 caused the incident, identify the customer impact "
            "visible to the current role, explain what evidence rules out "
            "the alternative change, and cite the lock evidence and approved "
            "runbook supporting recovery and prevention."
        )
        with (
            patch(
                "backend.app.search._query_embedding_model",
                return_value="local-hash-embedding-v1",
            ),
            patch(
                "backend.app.search.embed_text",
                side_effect=lambda text, **_: hash_embedding(text),
            ),
        ):
            response = answer_question(
                AgentAnswerRequest(question=question, limit=8)
            )
        coverage = get_agent_coverage_impl(response["agent_run_id"])

        self.assertEqual(response["status"], "complete")
        self.assertEqual(len(response["subquestions"]), 5)
        self.assertEqual(coverage["covered_count"], 5)
        self.assertEqual(response["escalations_spent"], 1)
        self.assertEqual(response["tool_calls_spent"], 9)
        self.assertEqual(len(response["retrievals"]), 6)
        self.assertEqual(len(response["escalations"]), 1)

        escalation = response["escalations"][0]
        self.assertEqual(escalation["subquestion_id"], "SQ-5")
        self.assertEqual(escalation["missing_kinds"], ["runbook"])
        # Runbooks are reusable procedures, so they carry neither an incident nor
        # a cluster. Both scope filters have to go or the retry cannot reach one.
        self.assertEqual(
            escalation["changed"]["after"]["filters"],
            {"cluster_id": None, "incident_id": None},
        )
        self.assertEqual(
            escalation["changed"]["before"]["filters"],
            {"cluster_id": "checkout-prod-cluster-01", "incident_id": "INC-2047"},
        )
        sq5 = response["subquestions"][-1]
        self.assertEqual(sq5["attempts"], 2)
        self.assertFalse(sq5["runs"][0]["coverage"]["covered"])
        self.assertTrue(sq5["runs"][1]["coverage"]["covered"])
        self.assertEqual(
            sq5["runs"][1]["coverage"]["covering_evidence_ids"]["runbook"],
            "RB-017",
        )
        # The evidence the workshop asks participants to prove from. Assembling
        # this set is Aurora's job -- retrieval, escalation, and traversal -- so
        # it is exact. Which subset of it the model then chooses to cite is a
        # model decision and is asserted separately below.
        briefed = {row["external_key"] for row in response["results"]}
        self.assertEqual(
            briefed,
            {
                "INC-2047",
                "CHG-1842",
                "CHG-1838",
                "LOCK-2047-001",
                "LOCK-2047-002",
                "CASE-7419",
                "CASE-7424",
                "RB-017",
            },
        )
        # CASE-7421 is relevant but restricted, and RB-092 is superseded. ACL
        # and currency are enforced in SQL, so neither can reach the model.
        self.assertNotIn("CASE-7421", briefed)
        self.assertNotIn("RB-092", briefed)
        # Every citation must resolve to briefed evidence. The count is not
        # pinned: the model occasionally leaves one brief uncited, which is a
        # weaker answer but not a retrieval or provenance defect.
        cited = {citation["external_key"] for citation in response["citations"]}
        self.assertTrue(cited)
        self.assertLessEqual(cited, briefed)
        # Causation and the ruled-out alternative are what the module exists to
        # show, so those four must be cited every time.
        self.assertLessEqual(
            {"INC-2047", "CHG-1842", "CHG-1838", "RB-017"},
            cited,
        )

    def test_planner_anchors_come_from_declared_relationships(self) -> None:
        from backend.app.agent import decompose_question_impl

        # A background incident has its own runbook and no lock capture. The
        # planner has to name that runbook, not the focused fixture's, and has to
        # stay generic where the corpus declares nothing.
        plan = decompose_question_impl(
            "Which customer was affected by INC-BG-00020 and what runbook "
            "prevents a recurrence?"
        )
        sq5 = plan["subquestions"][-1]["text"]

        self.assertIn("RB-BG-00020", sq5)
        self.assertNotIn("RB-017", sq5)
        self.assertIn("the lock evidence", sq5)
        self.assertNotIn("LOCK-2047-001", sq5)

    def test_transport_contract_persists_versioned_hashes(self) -> None:
        from backend.app.contracts import InvocationContext, invoke_contract
        from backend.app.models import SearchRequest
        from backend.app.search import run_hybrid_search

        request = SearchRequest(
            query="CHG-1842",
            mode="lexical",
            rerank=False,
            limit=3,
        )
        response = invoke_contract(
            InvocationContext(
                transport="http",
                request_id="req-integration-contract",
            ),
            "search_evidence",
            request.model_dump(mode="json"),
            lambda: run_hybrid_search(request),
        )

        self.assertEqual(response["contract_version"], "1.0.0")
        self.assertEqual(response["request_id"], "req-integration-contract")
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM proof.transport_invocations
                WHERE metadata ->> 'request_id' = 'req-integration-contract'
                """
            )
            receipt = cursor.fetchone()
        self.assertEqual(str(receipt["run_id"]), response["run_id"])
        self.assertEqual(receipt["transport"], "http")
        self.assertEqual(receipt["status"], "succeeded")
        self.assertEqual(len(receipt["request_hash"]), 64)
        self.assertEqual(len(receipt["normalized_response_hash"]), 64)

    def test_tombstone_supersedes_search_index_and_completes_queue(self) -> None:
        target = evidence_id("support_case", "CASE-7424")
        with self.conn.transaction():
            with self.conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE casework.evidence_items
                    SET is_deleted = true,
                        deleted_at = now(),
                        source_revision = source_revision || '-deleted'
                    WHERE evidence_id = %s
                    """,
                    (target,),
                )
                cursor.execute("SELECT casework.queue_evidence(%s)", (target,))

        receipt = rebuild_search_index(
            self.conn,
            model_id="local-hash-embedding-v1",
            cache_path=Path(self.cache_dir.name) / "embeddings.jsonl",
            embed_missing=False,
        )
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT is_current, index_state
                FROM retrieval.documents
                WHERE evidence_id = %s
                ORDER BY indexed_at DESC NULLS LAST
                LIMIT 1
                """,
                (target,),
            )
            document = cursor.fetchone()
            cursor.execute(
                """
                SELECT status
                FROM retrieval.search_index_queue
                WHERE evidence_id = %s
                ORDER BY requested_at DESC
                LIMIT 1
                """,
                (target,),
            )
            outbox = cursor.fetchone()

        self.assertGreaterEqual(receipt["documents_superseded"], 1)
        self.assertFalse(document["is_current"])
        self.assertEqual(document["index_state"], "superseded")
        self.assertEqual(outbox["status"], "complete")


if __name__ == "__main__":
    unittest.main()
