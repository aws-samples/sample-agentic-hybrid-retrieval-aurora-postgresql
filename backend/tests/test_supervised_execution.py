"""Supervised-execution schema tests.

Every interesting property here is a negative one: the fingerprint must NOT
change across formatting variance, must NOT match on reversed key order, and a
successful execution must NOT make an ineligible proposal eligible.
"""
from __future__ import annotations

import os
import unittest

import psycopg

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
SECURITY_ENABLED = os.environ.get("WORKBENCH_SECURITY_ENABLED") == "1"
SECURITY_DATABASE_TESTS = bool(TEST_DATABASE_URL and SECURITY_ENABLED)

FIXTURE_EXTERNAL_KEY = "INC-SUPERVISED-EXECUTION-TEST"
FIXTURE_CLUSTER_ID = "cluster-supervised-execution-test"
FIXTURE_CAPTURE_IDS = (
    "00000000-0000-4000-8000-0000000000a1",
    "00000000-0000-4000-8000-0000000000b2",
)
FIXTURE_INGEST_IDS = (
    "00000000-0000-4000-8000-0000000001a1",
    "00000000-0000-4000-8000-0000000001b2",
)

CANON = (
    "SELECT proof.canonical_index_key(%s, %s, NULL, NULL)"
)
FINGERPRINT = (
    "SELECT proof.index_action_fingerprint("
    "'create_index', 'workbench_lab', 'orders', 'btree', false, %s, '{}', NULL)"
)


def _assert_disposable_database(connection) -> None:
    name = connection.execute("SELECT current_database()").fetchone()[0]
    if not name.endswith("_test"):
        raise RuntimeError(f"SAFETY ABORT: refusing to run against {name}")


def _ensure_proof_fixture(connection) -> dict:
    """Create test-only FK targets without relying on a prior live capture."""
    _assert_disposable_database(connection)
    connection.execute(
        """
        INSERT INTO casework.database_clusters(
          cluster_id, engine, engine_version, aws_region, environment,
          service_name, writer_endpoint_alias, instance_class
        )
        VALUES (%s, 'postgresql', '18.4', 'local', 'development',
                'supervised-execution-test', 'localhost', 'local')
        ON CONFLICT (cluster_id) DO NOTHING
        """,
        (FIXTURE_CLUSTER_ID,),
    )
    evidence_id = connection.execute(
        """
        INSERT INTO casework.evidence_items(
          evidence_kind, external_key, title, source_system, source_uri,
          source_revision, source_updated_at, acl
        )
        VALUES (
          'incident', %s, 'Supervised execution contract fixture',
          'contract_test', 'test://supervised-execution/incident', 'r1', now(),
          '{"visibility":"workshop"}'::jsonb
        )
        ON CONFLICT (evidence_kind, external_key) DO UPDATE
          SET source_updated_at = EXCLUDED.source_updated_at
        RETURNING evidence_id
        """,
        (FIXTURE_EXTERNAL_KEY,),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO casework.incidents(
          evidence_id, incident_id, cluster_id, severity, status, started_at,
          resolved_at, summary, impact_summary, resolution
        )
        VALUES (%s, %s, %s, 'SEV-3', 'resolved', now() - interval '1 minute',
                now(), 'Test-only incident', 'No participant impact',
                'Test fixture only')
        ON CONFLICT (evidence_id) DO NOTHING
        """,
        (evidence_id, FIXTURE_EXTERNAL_KEY, FIXTURE_CLUSTER_ID),
    )
    build_id = connection.execute(
        """
        INSERT INTO retrieval.search_index_builds(
          search_index_version, embedding_model, embedding_dimensions,
          renderer_version, chunker_version, status, completed_at,
          document_count, chunk_count
        )
        VALUES ('supervised-execution-test/1', 'test-only', 1024,
                'test/1', 'test/1', 'complete', now(), 1, 1)
        RETURNING build_id
        """
    ).fetchone()[0]
    document_version_id = connection.execute(
        """
        INSERT INTO retrieval.documents(
          evidence_id, build_id, search_index_version, search_document_hash,
          source_revision, evidence_kind, external_key, title, source_system,
          source_uri, source_updated_at, acl, acl_visibility, occurred_at,
          metadata, index_state, is_current, indexed_at
        )
        VALUES (
          %s, %s, 'supervised-execution-test/1', 'fixture-document-hash', 'r1',
          'incident', %s, 'Supervised execution contract fixture',
          'contract_test', 'test://supervised-execution/incident', now(),
          '{"visibility":"workshop"}'::jsonb, 'workshop', now(), '{}'::jsonb,
          'ready', false, now()
        )
        ON CONFLICT (
          evidence_id, search_index_version, search_document_hash
        ) DO UPDATE SET indexed_at = EXCLUDED.indexed_at
        RETURNING document_version_id
        """,
        (evidence_id, build_id, FIXTURE_EXTERNAL_KEY),
    ).fetchone()[0]
    chunk_version_id = connection.execute(
        """
        INSERT INTO retrieval.chunks(
          document_version_id, evidence_id, chunk_ordinal, section_title,
          chunk_text, chunk_hash, embedding_state, is_current, evidence_kind,
          source_system, source_updated_at, occurred_at, acl, acl_visibility
        )
        VALUES (
          %s, %s, 1, 'Contract fixture',
          'This test-only citation supports the supervised execution contract.',
          'fixture-chunk-hash', 'pending', false, 'incident', 'contract_test',
          now(), now(), '{"visibility":"workshop"}'::jsonb, 'workshop'
        )
        ON CONFLICT (document_version_id, chunk_ordinal) DO UPDATE
          SET chunk_text = EXCLUDED.chunk_text
        RETURNING chunk_version_id
        """,
        (document_version_id, evidence_id),
    ).fetchone()[0]

    receipt_pairs = []
    for ordinal, (capture_id, ingest_id) in enumerate(
        zip(FIXTURE_CAPTURE_IDS, FIXTURE_INGEST_IDS, strict=True), start=1
    ):
        bundle_uri = f"test://supervised-execution/wave-b/{ordinal}"
        connection.execute(
            """
            INSERT INTO casework.incident_capture_runs(
              capture_id, capture_key, wave, incident_evidence_id, cluster_id,
              capture_origin, engine_version, instance_class, database_name,
              table_schema, table_name, relation_oid, configured_row_count,
              observed_row_count, table_size_bytes, steady_state_connections,
              capture_started_at, capture_ended_at, capture_tool_version,
              source_bundle_sha256, source_bundle_uri,
              observability_verified_at, manifest
            )
            VALUES (
              %s, %s, 'B', %s, %s, 'participant_induced', '18.4', 'local',
              'dat410_review_remediation_test', 'workbench_lab', 'orders', 1,
              1, 1, 1, 1, now() - interval '1 second', now(),
              'supervised-execution-test/1', %s, %s, now(),
              '{"contract_test":true}'::jsonb
            )
            ON CONFLICT (capture_id) DO NOTHING
            """,
            (
                capture_id,
                f"CAP-SUPERVISED-EXECUTION-{ordinal}",
                evidence_id,
                FIXTURE_CLUSTER_ID,
                f"fixture-capture-hash-{ordinal}",
                bundle_uri,
            ),
        )
        connection.execute(
            """
            INSERT INTO casework.ingest_receipts(
              ingest_id, source_uri, content_hash, evidence_id, external_key,
              evidence_kind, payload_hash, rows_written, edges_written, queued,
              available_at
            )
            VALUES (%s, %s, %s, %s, %s, 'incident', %s, 0, 0, 0, now())
            ON CONFLICT (ingest_id) DO NOTHING
            """,
            (
                ingest_id,
                bundle_uri,
                f"fixture-content-hash-{ordinal}",
                evidence_id,
                FIXTURE_EXTERNAL_KEY,
                f"fixture-payload-hash-{ordinal}",
            ),
        )
        receipt_pairs.append((capture_id, ingest_id))

    connection.execute("CREATE SCHEMA IF NOT EXISTS workbench_lab")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workbench_lab.orders(
          order_id bigint PRIMARY KEY,
          priority_tier text,
          created_at timestamptz
        )
        """
    )
    return {
        "evidence_id": evidence_id,
        "document_version_id": document_version_id,
        "chunk_version_id": chunk_version_id,
        "source_uri": "test://supervised-execution/incident",
        "source_revision": "r1",
        "quote_text": (
            "This test-only citation supports the supervised execution contract."
        ),
        "receipt_pairs": receipt_pairs,
    }


def _seed_agent_answer_run(connection, *, role: str = "app_engineer") -> tuple[str, str]:
    run_id = connection.execute(
        """
        INSERT INTO proof.retrieval_runs(
          query_text, retrieval_mode, role, rrf_k, text_weight,
          vector_weight, fuzzy_weight
        )
        VALUES ('supervised-execution test', 'hybrid', %s, 60, 1, 1, 1)
        RETURNING run_id
        """,
        (role,),
    ).fetchone()[0]
    agent_run_id = connection.execute(
        """
        INSERT INTO proof.agent_runs(
          question, role, controls_initial, contract_version
        )
        VALUES ('supervised-execution test', %s, '{}'::jsonb, 'test')
        RETURNING agent_run_id
        """,
        (role,),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO proof.agent_answers(
          run_id, agent_run_id, question, answer_text, synthesis_mode,
          validation_status
        )
        VALUES (
          %s, %s, 'supervised-execution test', 'test answer',
          'checkpoint', 'valid'
        )
        """,
        (run_id, agent_run_id),
    )
    return str(agent_run_id), str(run_id)


@unittest.skipUnless(TEST_DATABASE_URL, "requires TEST_DATABASE_URL")
class FingerprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        name = cls.conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: refusing to run against {name}")
        _ensure_proof_fixture(cls.conn)
        # The fingerprint tests need real indexes to read back out of the catalog,
        # and they build them in their own throwaway schema rather than touching
        # workbench_lab -- an index created here on the real lab table would change
        # the plan Lab 4 is supposed to measure.
        cls.conn.execute("DROP SCHEMA IF EXISTS fp_check CASCADE")
        cls.conn.execute("CREATE SCHEMA fp_check")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.execute("DROP SCHEMA IF EXISTS fp_check CASCADE")
        cls.conn.close()

    def _fingerprint(self, keys: list[tuple[str, str]]) -> str:
        canonical = [
            self.conn.execute(CANON, (expression, direction)).fetchone()[0]
            for expression, direction in keys
        ]
        return self.conn.execute(FINGERPRINT, (canonical,)).fetchone()[0]

    def test_formatting_variance_produces_one_fingerprint(self) -> None:
        plain = self._fingerprint([("priority_tier", "asc"), ("created_at", "desc")])
        noisy = self._fingerprint(
            [("  PRIORITY_TIER ", "ASC"), ("created_at\n", "DESC")]
        )
        self.assertEqual(
            plain, noisy,
            "casing and whitespace must not change the canonical fingerprint",
        )

    def test_reversed_key_order_produces_a_different_fingerprint(self) -> None:
        forward = self._fingerprint([("priority_tier", "asc"), ("created_at", "desc")])
        reversed_ = self._fingerprint([("created_at", "desc"), ("priority_tier", "asc")])
        self.assertNotEqual(
            forward, reversed_,
            "key column order is semantically load-bearing and must change the "
            "fingerprint",
        )

    def test_comma_in_a_key_expression_cannot_forge_a_collision(self) -> None:
        left = self.conn.execute(FINGERPRINT, (["a,b", "c"],)).fetchone()[0]
        right = self.conn.execute(FINGERPRINT, (["a", "b,c"],)).fetchone()[0]
        self.assertNotEqual(
            left, right,
            "a comma inside a key expression must not collapse two different "
            "key lists into one fingerprint",
        )

    def test_no_key_columns_is_rejected(self) -> None:
        with self.assertRaises(psycopg.errors.RaiseException):
            self.conn.execute(FINGERPRINT, ([],)).fetchone()

    def test_proposal_and_catalog_fingerprints_agree(self) -> None:
        """The two derivations must agree for an identical action.

        This is the test whose absence hid a real defect. The earlier draft
        compared observed indexes only against other observed indexes, which
        cannot detect a proposal-side/observation-side disagreement because both
        sides of that comparison pass through pg_get_expr(). Compare ACROSS the
        two derivations or the assertion is vacuous.
        """
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS fp_check.orders ("
            "  order_id bigint, status text, priority_tier text,"
            "  created_at timestamptz)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fp_check_probe"
            "  ON fp_check.orders (priority_tier, created_at DESC)"
        )
        row = self.conn.execute(
            """
            WITH proposed AS (
              SELECT proof.index_action_fingerprint(
                'create_index', 'fp_check', 'orders', 'btree', false,
                ARRAY[
                  proof.canonical_index_key('priority_tier', 'asc', NULL, NULL),
                  proof.canonical_index_key('created_at', 'desc', NULL, NULL)
                ],
                '{}'::text[], NULL) AS fp
            ), observed AS (
              SELECT f.fingerprint AS fp
              FROM pg_class c
              CROSS JOIN proof.observed_index_fingerprint(c.oid) f
              WHERE c.relname = 'idx_fp_check_probe'
            )
            SELECT p.fp, o.fp FROM proposed p CROSS JOIN observed o
            """
        ).fetchone()
        self.assertEqual(
            row[0], row[1],
            "the proposal-side and catalog-side fingerprints must agree for an "
            "identical action; a mismatch tells a correct participant they "
            "executed the wrong thing",
        )

    def test_a_partial_index_predicate_is_rejected(self) -> None:
        """The unfingerprintable case must be unrepresentable, not merely unused.

        Measured on PostgreSQL 17.10: proposed `status = 'open'` reads back from
        the catalog as `(status = 'open'::text)`, so the fingerprints disagree for
        an identical index. The CHECK is what keeps that row from existing.
        """
        agent_run_id, run_id = _seed_agent_answer_run(self.conn)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute(
                "INSERT INTO proof.action_proposals ("
                "  agent_run_id, run_id, action_type, target_schema,"
                "  target_table, key_columns, predicate, proposed_fingerprint,"
                "  proposed_sql, proposed_sql_sha256, preconditions,"
                "  expected_effect, rollback_guidance, statement_timeout,"
                "  lock_timeout)"
                " VALUES (%s, %s, 'create_index', 'workbench_lab',"
                "  'orders', ARRAY['created_at asc nulls_last default'],"
                "  'status = ''open''', 'x', 'y', 'z', '[]'::jsonb, 'e', 'r',"
                "  '5s', '5s')",
                (agent_run_id, run_id),
            )

    def test_a_quoted_relation_does_not_match_the_lower_case_one(self) -> None:
        """A different table must never fingerprint as the proposed one.

        MEASURED FALSE MATCH this guards (PostgreSQL 17.10, 2026-08-04): with
        `lower(btrim(relname))` on the observed side, an index built on
        fp_check."ORDERS" produced the SAME fingerprint as the proposal for
        fp_check.orders. The workshop would report a match for an action taken
        against a different table. quote_ident() on the observed side plus
        proof.canonical_sql_name()'s whole-string test is the fix; this test is
        what keeps either half from being simplified away.
        """
        self.conn.execute(
            'CREATE TABLE IF NOT EXISTS fp_check."ORDERS" ('
            "  priority_tier text, created_at timestamptz)"
        )
        self.conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_fp_check_quoted'
            '  ON fp_check."ORDERS" (priority_tier, created_at DESC)'
        )
        row = self.conn.execute(
            """
            SELECT proof.index_action_fingerprint(
                     'create_index', 'fp_check', 'orders', 'btree', false,
                     ARRAY[
                       proof.canonical_index_key('priority_tier','asc',NULL,NULL),
                       proof.canonical_index_key('created_at','desc',NULL,NULL)
                     ], '{}'::text[], NULL),
                   (SELECT f.fingerprint
                      FROM pg_class c
                      CROSS JOIN proof.observed_index_fingerprint(c.oid) f
                     WHERE c.relname = 'idx_fp_check_quoted')
            """
        ).fetchone()
        self.assertNotEqual(
            row[0], row[1],
            'an index on fp_check."ORDERS" must not fingerprint as the proposal '
            "for fp_check.orders; those are different tables",
        )

    def test_include_columns_match_across_casing(self) -> None:
        """INCLUDE columns must fold the same way key columns do.

        MEASURED FALSE MISMATCH this guards: the earlier draft sorted the INCLUDE
        array but never folded it, so a proposal naming `Created_At` produced a
        different fingerprint from the catalog's `created_at` for the identical
        index. Two columns, not one, because a single-element list also passes if
        the sort key and the stored value are folded inconsistently.
        """
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS fp_check.payload ("
            "  priority_tier text, created_at timestamptz, amount numeric)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fp_check_include"
            "  ON fp_check.payload (priority_tier) INCLUDE (created_at, amount)"
        )
        row = self.conn.execute(
            """
            SELECT proof.index_action_fingerprint(
                     'create_index', 'fp_check', 'payload', 'btree', false,
                     ARRAY[proof.canonical_index_key('priority_tier','asc',NULL,NULL)],
                     ARRAY['Created_At', 'AMOUNT'], NULL),
                   (SELECT f.fingerprint
                      FROM pg_class c
                      CROSS JOIN proof.observed_index_fingerprint(c.oid) f
                     WHERE c.relname = 'idx_fp_check_include')
            """
        ).fetchone()
        self.assertEqual(
            row[0], row[1],
            "mixed-case INCLUDE columns must canonicalize to the catalog's form",
        )

    def test_a_string_literal_in_an_expression_is_not_case_folded(self) -> None:
        """Two expression indexes differing only in a literal are different.

        MEASURED FALSE MATCH this guards: the earlier fold rule tested for a
        double quote anywhere in the string, which never fires on a single-quoted
        literal, so regexp_replace(note,'A','B') and regexp_replace(note,'a','b')
        -- different indexes -- collapsed to one fingerprint.
        """
        upper = self.conn.execute(
            CANON, ("regexp_replace(note,'A','B')", "asc")
        ).fetchone()[0]
        lower = self.conn.execute(
            CANON, ("regexp_replace(note,'a','b')", "asc")
        ).fetchone()[0]
        self.assertNotEqual(
            upper, lower,
            "a case-different string literal is a different index and must not "
            "share a canonical form",
        )

    def test_whitespace_in_a_string_literal_is_not_collapsed(self) -> None:
        two_spaces = self.conn.execute(
            "SELECT proof.canonical_sql_name(%s)",
            ("regexp_replace(note,'A  B','X')",),
        ).fetchone()[0]
        one_space = self.conn.execute(
            "SELECT proof.canonical_sql_name(%s)",
            ("regexp_replace(note,'A B','X')",),
        ).fetchone()[0]
        self.assertNotEqual(
            two_spaces,
            one_space,
            "whitespace inside a string literal is data, not formatting",
        )


@unittest.skipUnless(TEST_DATABASE_URL, "requires TEST_DATABASE_URL")
class ObservedFingerprintTests(unittest.TestCase):
    """Round-trip: an index CREATEd from the proposal's fields must observe back
    to the proposal's own fingerprint."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        name = cls.conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: refusing to run against {name}")
        cls.conn.execute("CREATE SCHEMA IF NOT EXISTS sup_exec_probe")
        cls.conn.execute(
            "CREATE TABLE IF NOT EXISTS sup_exec_probe.orders "
            "(order_id bigint, priority_tier text, created_at timestamptz)"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.execute("DROP SCHEMA IF EXISTS sup_exec_probe CASCADE")
        cls.conn.close()

    def _observe(self, index_name: str) -> str:
        return self.conn.execute(
            "SELECT f.fingerprint FROM pg_class c "
            "CROSS JOIN proof.observed_index_fingerprint(c.oid) f "
            "WHERE c.relname = %s",
            (index_name,),
        ).fetchone()[0]

    def _propose(self, keys: list[tuple[str, str]], *, unique: bool = False) -> str:
        canonical = [
            self.conn.execute(
                "SELECT proof.canonical_index_key(%s, %s, NULL, NULL)",
                (expression, direction),
            ).fetchone()[0]
            for expression, direction in keys
        ]
        return self.conn.execute(
            "SELECT proof.index_action_fingerprint("
            "'create_index', 'sup_exec_probe', 'orders', 'btree', %s, %s, '{}', NULL)",
            (unique, canonical),
        ).fetchone()[0]

    def test_proposed_and_observed_fingerprints_match(self) -> None:
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS probe_match ON sup_exec_probe.orders "
            "(priority_tier, created_at DESC)"
        )
        self.assertEqual(
            self._propose([("priority_tier", "asc"), ("created_at", "desc")]),
            self._observe("probe_match"),
            "a proposal's fingerprint must equal the fingerprint observed from "
            "the catalog after the same index is created",
        )

    def test_reversed_key_order_does_not_match_the_observed_index(self) -> None:
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS probe_order ON sup_exec_probe.orders "
            "(priority_tier, created_at DESC)"
        )
        self.assertNotEqual(
            self._propose([("created_at", "desc"), ("priority_tier", "asc")]),
            self._observe("probe_order"),
            "an index with reversed key order must not be reported as a match",
        )

    def test_unique_index_does_not_match_a_non_unique_proposal(self) -> None:
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS probe_uniq ON sup_exec_probe.orders "
            "(order_id)"
        )
        self.assertNotEqual(
            self._propose([("order_id", "asc")], unique=False),
            self._observe("probe_uniq"),
            "uniqueness is part of the action; a UNIQUE index must not match a "
            "non-unique proposal",
        )

    def test_raw_sql_hashes_differ_where_the_fingerprint_matches(self) -> None:
        """The contrast that justifies the fingerprint's existence."""
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS probe_spacing ON sup_exec_probe.orders "
            "(  PRIORITY_TIER ,\n   created_at    DESC  )"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS probe_tidy ON sup_exec_probe.orders "
            "(priority_tier, created_at DESC)"
        )
        self.assertEqual(
            self._observe("probe_spacing"),
            self._observe("probe_tidy"),
            "formatting variance must not change the canonical fingerprint",
        )
        raw_a, raw_b = (
            self.conn.execute(
                "SELECT encode(sha256(convert_to(%s, 'UTF8')), 'hex')", (text,)
            ).fetchone()[0]
            for text in (
                "CREATE INDEX i ON sup_exec_probe.orders (priority_tier, created_at DESC)",
                "create index i on sup_exec_probe.orders ( priority_tier , created_at desc )",
            )
        )
        self.assertNotEqual(
            raw_a, raw_b,
            "raw SQL hashes must differ across formatting -- this is precisely "
            "why they are audit-only and not the equality test",
        )
BASE_PROPOSAL = {
    "action_type": "create_index",
    "target_schema": "workbench_lab",
    "target_table": "orders",
    "key_columns": ["priority_tier asc nulls_last default"],
    "preconditions": '[{"check": "no_index_exists", "satisfied": true}]',
    "rollback_sql": "DROP INDEX workbench_lab.idx_orders_priority_created",
    "statement_timeout": "5min",
    "lock_timeout": "5s",
}

INSERT_PROPOSAL = """
INSERT INTO proof.action_proposals(
  agent_run_id, run_id, action_type, target_schema, target_table,
  key_columns, proposed_fingerprint, proposed_sql, proposed_sql_sha256,
  preconditions, expected_effect, rollback_sql, statement_timeout, lock_timeout
) VALUES (
  %(agent_run_id)s, %(run_id)s, %(action_type)s, %(target_schema)s,
  %(target_table)s, %(key_columns)s, 'fp', 'CREATE INDEX ...', 'raw-hash',
  %(preconditions)s::jsonb, 'index scan replaces the sequential scan',
  %(rollback_sql)s, %(statement_timeout)s, %(lock_timeout)s
) RETURNING proposal_id
"""


@unittest.skipUnless(TEST_DATABASE_URL, "requires TEST_DATABASE_URL")
class AutonomyReadinessTests(unittest.TestCase):
    """Every requirement removed in isolation must produce false with a NAMED
    reason. Eight independent negative cases, not one bundled check, plus the
    retroactive-safety test, two covering citation ownership and the
    validated-count polarity, and six covering the append-only rule, the receipt
    attachment, and the recorded_seq tiebreak."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        name = cls.conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: refusing to run against {name}")
        cls.fixture = _ensure_proof_fixture(cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def _seed_run(self) -> tuple[str, str]:
        """A real agent run and retrieval run to reference. The FK is not
        optional: a proposal that references no run is not auditable."""
        return _seed_agent_answer_run(self.conn)

    def _propose(self, **overrides) -> str:
        agent_run_id, run_id = self._seed_run()
        params = dict(BASE_PROPOSAL, agent_run_id=agent_run_id, run_id=run_id)
        params.update(overrides)
        return str(self.conn.execute(INSERT_PROPOSAL, params).fetchone()[0])

    def _verdict(self, proposal_id: str) -> tuple:
        return self.conn.execute(
            "SELECT pre_execution_eligible, pre_execution_reasons, "
            "       post_execution_validated, post_execution_reasons "
            "FROM proof.autonomy_readiness(%s)",
            (proposal_id,),
        ).fetchone()

    def _cite(self, proposal_id: str) -> None:
        """Attach a citation that proof.validate_answer_citations() accepts.
        Uses a test-scoped indexed row on this disposable database."""
        row = self.conn.execute(
            "SELECT run_id FROM proof.action_proposals WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()
        self.conn.execute(
            "INSERT INTO proof.answer_citations(run_id, citation_number, "
            "  evidence_id, document_version_id, chunk_version_id, source_uri, "
            "  source_revision, quote_text) "
            "VALUES (%s, 1, %s, %s, %s, %s, %s, %s)",
            (
                row[0],
                self.fixture["evidence_id"],
                self.fixture["document_version_id"],
                self.fixture["chunk_version_id"],
                self.fixture["source_uri"],
                self.fixture["source_revision"],
                self.fixture["quote_text"],
            ),
        )
        self.conn.execute(
            "INSERT INTO proof.action_proposal_citations(proposal_id, run_id, "
            "  citation_number, claim) VALUES (%s, %s, 1, 'supporting claim')",
            (proposal_id, row[0]),
        )

    def test_complete_proposal_is_eligible(self) -> None:
        proposal_id = self._propose()
        self._cite(proposal_id)
        eligible, reasons, validated, post_reasons = self._verdict(proposal_id)
        self.assertTrue(eligible, f"expected eligible, got reasons {reasons}")
        self.assertEqual(reasons, [])
        self.assertFalse(validated, "nothing has been executed yet")
        self.assertIn("no execution has been recorded yet", post_reasons)

    def test_uncited_proposal_is_ineligible(self) -> None:
        eligible, reasons, _, _ = self._verdict(self._propose())
        self.assertFalse(eligible)
        self.assertIn("the proposal cites no evidence", reasons)

    def test_unapproved_target_is_ineligible(self) -> None:
        proposal_id = self._propose(target_schema="casework")
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible)
        self.assertTrue(
            any("not an approved target" in reason for reason in reasons),
            f"expected an approved-target reason, got {reasons}",
        )

    def test_unsatisfied_precondition_is_ineligible(self) -> None:
        proposal_id = self._propose(
            preconditions='[{"check": "no_index_exists", "satisfied": false}]'
        )
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible)
        self.assertIn("at least one precondition is unsatisfied", reasons)

    def test_no_preconditions_recorded_is_ineligible(self) -> None:
        proposal_id = self._propose(preconditions="[]")
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible, "nothing checked is not everything passed")
        self.assertIn("no preconditions were recorded", reasons)

    def test_object_valued_preconditions_are_refused_at_insert(self) -> None:
        """Measured: without step 3's jsonb_typeof CHECK, an object here makes
        proof.autonomy_readiness() raise `cannot get array length of a
        non-array` instead of returning a verdict — the proposal becomes
        unjudgeable rather than ineligible. The CHECK moves the failure to
        insert time, where it names the column."""
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._propose(preconditions='{"satisfied": true}')

    def test_a_link_cannot_name_a_run_the_proposal_does_not_own(self) -> None:
        """Measured defect, guarded here. With step 3's link table referencing
        proof.action_proposals(proposal_id) ALONE, nothing required the link's
        run_id to equal the proposal's: a link naming this proposal with another
        run's run_id inserted cleanly. Requirement 6 then evaluated it against
        proof.validate_answer_citations(PROPOSAL.run_id) while the link's own FK
        had been satisfied against the OTHER run -- two sides validating
        different rows, measured verdict `PASSES requirement 6` for a proposal
        supported by a foreign run's invalid citation. The composite FK refuses
        the INSERT outright.
        """
        proposal_id = self._propose()
        self._cite(proposal_id)
        foreign_agent_run_id, foreign_run_id = self._seed_run()
        del foreign_agent_run_id
        source = self.conn.execute(
            """
            SELECT evidence_id, document_version_id, chunk_version_id,
                   source_uri, source_revision, quote_text
            FROM proof.answer_citations
            WHERE run_id = (
              SELECT run_id
              FROM proof.action_proposals
              WHERE proposal_id = %s
            )
            """,
            (proposal_id,),
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO proof.answer_citations(
              run_id, citation_number, evidence_id, document_version_id,
              chunk_version_id, source_uri, source_revision, quote_text
            )
            VALUES (%s, 2, %s, %s, %s, %s, %s, %s)
            """,
            (foreign_run_id, *source),
        )
        with self.assertRaises(psycopg.errors.ForeignKeyViolation) as caught:
            self.conn.execute(
                "INSERT INTO proof.action_proposal_citations(proposal_id, "
                "  run_id, citation_number, claim) VALUES (%s, %s, 2, 'borrowed')",
                (proposal_id, foreign_run_id),
            )
        self.assertEqual(
            caught.exception.diag.constraint_name,
            "action_proposal_citations_proposal_id_run_id_fkey",
            "the test must fail on proposal/run ownership, not another FK",
        )

    @unittest.skipUnless(
        SECURITY_DATABASE_TESTS,
        "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for RLS checks",
    )
    def test_a_persona_that_cannot_read_the_citation_gets_the_same_verdict(
        self,
    ) -> None:
        """MEASURED fail-open, and the reason requirement 6 counts VALIDATED
        citations instead of invalid ones.

        Deleting a citation cannot reproduce this: step 3's composite FK to
        proof.answer_citations CASCADEs the link away with it, and re-inserting
        the orphan link is refused with foreign_key_violation (measured) -- an
        unreachable-by-deletion link is unrepresentable. RLS is different: the
        rows all exist and satisfy every constraint, because referential
        integrity checks run with row_security off. Only the READ is filtered.

        proof.validate_answer_citations (sql/06_receipts.sql:67) INNER JOINs
        retrieval.documents and retrieval.chunks, both FORCE RLS with policies on
        acl_visibility (sql/11_roles_rls.sql:522-536), and the API runs the
        verdict under the requesting persona (backend/app/db.py:169 issues
        SET LOCAL ROLE per transaction). So a persona who cannot see the cited
        document loses the validation row while keeping the link -- the link
        table has no evidence_id, so its policy is the bare parent-run check,
        strictly weaker than proof.answer_citations' policy, which carries the
        evidence-reachability clause (lines 963-979).

        Measured before the fix: owner `1 cited claims failed`, persona
        `PASSES requirement 6` -- identical rows, no tampering, opposite
        verdicts. After: both `1 of 1 cited claims could not be validated`.
        """
        proposal_id = self._propose()
        self._cite(proposal_id)
        owner_eligible, _, _, _ = self._verdict(proposal_id)

        with self.conn.cursor() as cursor:
            cursor.execute("BEGIN")
            try:
                cursor.execute("SET LOCAL ROLE persona_app_engineer")
                visible = cursor.execute(
                    "SELECT count(*) FROM proof.validate_answer_citations("
                    "  (SELECT run_id FROM proof.action_proposals "
                    "   WHERE proposal_id = %s))",
                    (proposal_id,),
                ).fetchone()[0]
                persona = cursor.execute(
                    "SELECT pre_execution_eligible, pre_execution_reasons "
                    "FROM proof.autonomy_readiness(%s)",
                    (proposal_id,),
                ).fetchone()
            finally:
                cursor.execute("ROLLBACK")

        if visible:
            # The cited evidence happens to be workshop-visible, so this run
            # cannot exercise the gap. Then the two verdicts must simply agree.
            self.assertEqual(
                persona[0],
                owner_eligible,
                "with the citation readable, both roles must agree",
            )
            return
        self.assertFalse(
            persona[0],
            "a persona that cannot read the citation must never be told the "
            f"proposal is eligible; owner said {owner_eligible}",
        )
        self.assertTrue(
            any("could not be validated" in reason for reason in persona[1]),
            f"expected an unvalidatable-citation reason, got {persona[1]}",
        )

    def test_replacing_the_answer_citations_does_not_wedge_the_run(self) -> None:
        """Measured defect, guarded here. backend/app/agent.py:737 DELETEs a
        run's proof.answer_citations rows on every _persist_answer() call, and
        that function's own INSERT is ON CONFLICT (run_id) DO UPDATE -- so
        re-answering a run is a supported path. With ON DELETE RESTRICT on
        step 3's composite FK, the first proposal written against a run
        permanently wedged that run: the re-persist failed with `violates
        foreign key constraint
        "action_proposal_citations_run_id_citation_number_fkey"`. CASCADE drops
        the stale LINK and keeps the proposal, which then honestly reports
        `the proposal cites no evidence` until Task D2a relinks it.
        """
        proposal_id = self._propose()
        self._cite(proposal_id)
        run_id = self.conn.execute(
            "SELECT run_id FROM proof.action_proposals WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()[0]
        eligible, _, _, _ = self._verdict(proposal_id)
        self.assertTrue(eligible, "baseline must be eligible before the re-persist")

        self.conn.execute(
            "DELETE FROM proof.answer_citations WHERE run_id = %s", (run_id,)
        )

        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM proof.action_proposal_citations "
                "WHERE proposal_id = %s",
                (proposal_id,),
            ).fetchone()[0],
            0,
            "the stale citation link must be removed with the citation it names",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM proof.action_proposals WHERE proposal_id = %s",
                (proposal_id,),
            ).fetchone()[0],
            1,
            "CASCADE must delete the LINK, never the proposal",
        )
        after_eligible, after_reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(after_eligible)
        self.assertIn("the proposal cites no evidence", after_reasons)

    def test_unbounded_timeout_is_ineligible(self) -> None:
        proposal_id = self._propose(lock_timeout=None)
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible)
        self.assertIn(
            "statement_timeout and lock_timeout must both be bounded", reasons
        )

    def test_missing_rollback_guidance_is_ineligible(self) -> None:
        proposal_id = self._propose(rollback_sql=None)
        self._cite(proposal_id)
        eligible, reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(eligible)
        self.assertIn("no rollback guidance was recorded", reasons)

    def test_successful_execution_does_not_flip_pre_execution_eligibility(self) -> None:
        """The retroactive-safety test. This is the one test in this class that
        must never be skipped or weakened: it is the only thing standing between
        an autonomy-READINESS assessment and a post-hoc safety claim."""
        proposal_id = self._propose(rollback_sql=None)  # ineligible by construction
        self._cite(proposal_id)
        before_eligible, before_reasons, _, _ = self._verdict(proposal_id)
        self.assertFalse(before_eligible)
        self.assertIn("no rollback guidance was recorded", before_reasons)

        capture_id, ingest_id = self._latest_wave_b_ids()
        # run_id is NOT NULL and composite-FK-bound to this proposal's own
        # run_id (step 3). Reading it back from the proposal rather than
        # inventing one is also what the real Task D3 writer must do.
        self.conn.execute(
            "INSERT INTO proof.action_executions(proposal_id, run_id, "
            "  approved_by, outcome, observed_index_definition, "
            "  observed_fingerprint, fingerprint_matches, wave_b_capture_id, "
            "  wave_b_ingest_id) "
            "SELECT p.proposal_id, p.run_id, 'participant', 'succeeded', "
            "       'CREATE INDEX ...', 'fp', true, %s, %s "
            "FROM proof.action_proposals p WHERE p.proposal_id = %s",
            (capture_id, ingest_id, proposal_id),
        )

        after_eligible, after_reasons, validated, post_reasons = self._verdict(
            proposal_id
        )
        self.assertFalse(
            after_eligible,
            "a successful execution must NOT make an ineligible proposal "
            "eligible; post-execution evidence may never feed "
            "pre_execution_eligible",
        )
        self.assertEqual(
            before_reasons, after_reasons,
            "the pre-execution reasons must be unchanged by the execution",
        )
        self.assertTrue(validated, f"execution succeeded but post said {post_reasons}")

    def _latest_wave_b_ids(self) -> tuple:
        return self.fixture["receipt_pairs"][0]

    def _record(self, proposal_id: str, outcome: str, matches: bool) -> str:
        """One execution row with NULL Wave B identifiers, as Task D3's
        record-before-admission ordering writes it."""
        return str(
            self.conn.execute(
                "INSERT INTO proof.action_executions(proposal_id, run_id, "
                "  approved_by, outcome, observed_index_definition, "
                "  observed_fingerprint, fingerprint_matches) "
                "SELECT p.proposal_id, p.run_id, 'participant', %s, "
                "       'CREATE INDEX ...', 'fp', %s "
                "FROM proof.action_proposals p WHERE p.proposal_id = %s "
                "RETURNING execution_id",
                (outcome, matches, proposal_id),
            ).fetchone()[0]
        )

    def test_wave_b_receipt_attaches_exactly_once(self) -> None:
        """The record-before-admission ordering needs one narrow mutation. It
        must be narrow in both directions: once only, and receipt columns only."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", True)
        _, _, validated, post_reasons = self._verdict(proposal_id)
        self.assertFalse(
            validated,
            "an execution recorded before admission is not yet validated",
        )
        self.assertIn(
            "the result was not validated by an admitted Wave B capture",
            post_reasons,
        )

        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
            (execution_id, capture_id, ingest_id),
        )
        _, _, validated, post_reasons = self._verdict(proposal_id)
        self.assertTrue(validated, f"after attach, post said {post_reasons}")

        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self.conn.execute(
                "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
                (execution_id, capture_id, ingest_id),
            )
        self.assertIn("already carries a Wave B receipt", str(caught.exception))

    def test_wave_b_capture_and_receipt_must_be_one_bundle(self) -> None:
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", True)
        first_capture, _ = self.fixture["receipt_pairs"][0]
        _, second_ingest = self.fixture["receipt_pairs"][1]
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self.conn.execute(
                "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
                (execution_id, first_capture, second_ingest),
            )
        self.assertIn("not one admitted Wave B bundle", str(caught.exception))

    def test_boolean_match_cannot_override_different_fingerprints(self) -> None:
        proposal_id = self._propose()
        self._cite(proposal_id)
        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            """
            INSERT INTO proof.action_executions(
              proposal_id, run_id, approved_by, outcome,
              observed_index_definition, observed_fingerprint,
              fingerprint_matches, wave_b_capture_id, wave_b_ingest_id
            )
            SELECT proposal_id, run_id, 'participant', 'succeeded',
                   'CREATE INDEX ...', 'different-fingerprint', true, %s, %s
            FROM proof.action_proposals
            WHERE proposal_id = %s
            """,
            (capture_id, ingest_id, proposal_id),
        )
        _, _, validated, reasons = self._verdict(proposal_id)
        self.assertFalse(validated)
        self.assertIn(
            "the executed action does not match the proposed action", reasons
        )

    def test_verdict_columns_cannot_be_rewritten(self) -> None:
        """The append-only rule, tested where privilege cannot reach it: this
        connection IS the owner and holds UPDATE. Without the trigger a recorded
        mismatch could be edited into a match, which would make the whole
        fingerprint comparison decorative."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", False)
        for column, value in (
            ("fingerprint_matches", True),
            ("outcome", "failed"),
            ("observed_fingerprint", "forged"),
            ("observed_index_definition", "forged"),
            ("executed_sql", "DROP TABLE workbench_lab.orders"),
            ("executed_sql_sha256", "forged"),
            ("outcome_detail", "forged"),
            ("plan_after_checkpoint", "forged"),
            ("approved_by", "somebody-else"),
        ):
            with self.subTest(column=column):
                with self.assertRaises(psycopg.errors.RaiseException) as caught:
                    self.conn.execute(
                        f"UPDATE proof.action_executions SET {column} = %s "
                        "WHERE execution_id = %s",
                        (value, execution_id),
                    )
                self.assertIn("append-only", str(caught.exception))
        row = self.conn.execute(
            "SELECT outcome, fingerprint_matches, observed_fingerprint, "
            "       approved_by FROM proof.action_executions "
            "WHERE execution_id = %s",
            (execution_id,),
        ).fetchone()
        self.assertEqual(row, ("succeeded", False, "fp", "participant"))

    def test_bundling_a_receipt_does_not_smuggle_a_verdict_rewrite(self) -> None:
        """The measured defeat of the first trigger draft. That draft reverted
        protected columns silently instead of raising, so this exact statement
        SUCCEEDED, wrote the receipt, kept the honest verdict, and reported no
        error -- leaving the caller believing the rewrite had landed."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", False)
        capture_id, ingest_id = self._latest_wave_b_ids()
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self.conn.execute(
                "UPDATE proof.action_executions "
                "   SET fingerprint_matches = true, wave_b_capture_id = %s, "
                "       wave_b_ingest_id = %s "
                " WHERE execution_id = %s",
                (capture_id, ingest_id, execution_id),
            )
        self.assertIn("append-only", str(caught.exception))
        self.assertEqual(
            self.conn.execute(
                "SELECT fingerprint_matches, wave_b_capture_id "
                "FROM proof.action_executions WHERE execution_id = %s",
                (execution_id,),
            ).fetchone(),
            (False, None),
            "the whole statement must roll back, receipt included",
        )

    def test_the_engines_set_null_is_permitted_on_an_attached_row(self) -> None:
        """The measured defeat of the SECOND trigger draft, which refused any
        update to a row already carrying a receipt. `ON DELETE SET NULL` IS an
        UPDATE and fires the same trigger, so that draft made every referenced
        capture undeletable for as long as its execution row existed.

        This test does NOT delete a real capture run: `casework.incident_capture_runs`
        is participant-induced live evidence that other tests and the Proof
        surface read, and `casework.evidence_items` references it ON DELETE
        RESTRICT. It exercises the same trigger path the referential action takes
        -- an UPDATE clearing an attached receipt to NULL -- which is exactly what
        the second draft refused."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", True)
        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
            (execution_id, capture_id, ingest_id),
        )
        self.conn.execute(
            "UPDATE proof.action_executions SET wave_b_capture_id = NULL "
            "WHERE execution_id = %s",
            (execution_id,),
        )
        row = self.conn.execute(
            "SELECT wave_b_capture_id, wave_b_ingest_id IS NOT NULL, outcome, "
            "       fingerprint_matches FROM proof.action_executions "
            "WHERE execution_id = %s",
            (execution_id,),
        ).fetchone()
        self.assertEqual(
            row,
            (None, True, "succeeded", True),
            "clearing a receipt to NULL must be permitted, must leave the other "
            "receipt column alone, and must not touch the verdict columns",
        )

    def test_a_receipt_cannot_be_overwritten_with_a_different_one(self) -> None:
        """Clearing to NULL is permitted; substituting a DIFFERENT capture is
        not. Without this half, the transition rule that unblocked the previous
        test would also let an attached receipt be swapped for an unrelated
        one, which is provenance laundering."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        execution_id = self._record(proposal_id, "succeeded", True)
        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
            (execution_id, capture_id, ingest_id),
        )
        other = self.fixture["receipt_pairs"][1]
        with self.assertRaises(psycopg.errors.RaiseException) as caught:
            self.conn.execute(
                "UPDATE proof.action_executions SET wave_b_capture_id = %s "
                "WHERE execution_id = %s",
                (other[0], execution_id),
            )
        self.assertIn("already carries a different", str(caught.exception))

    def test_two_attempts_in_one_transaction_resolve_deterministically(self) -> None:
        """now() is transaction START time, so two rows recorded in one
        transaction share one approved_at. Ordering on approved_at alone was
        MEASURED non-deterministic: reclustering the same two rows returned
        'failed', 'succeeded', then 'failed' with no write in between. The
        verdict must name the LATER attempt every time."""
        proposal_id = self._propose()
        self._cite(proposal_id)
        with self.conn.transaction():
            self._record(proposal_id, "failed", False)
            later = self._record(proposal_id, "succeeded", True)
        capture_id, ingest_id = self._latest_wave_b_ids()
        self.conn.execute(
            "SELECT proof.attach_wave_b_receipt(%s, %s, %s)",
            (later, capture_id, ingest_id),
        )
        stamps = self.conn.execute(
            "SELECT count(DISTINCT approved_at), count(*) "
            "FROM proof.action_executions WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()
        self.assertEqual(
            stamps, (1, 2), "the premise of this test is a shared approved_at"
        )
        reported = self.conn.execute(
            "SELECT execution_id FROM proof.action_executions "
            "WHERE proposal_id = %s "
            "ORDER BY approved_at DESC, recorded_seq DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()[0]
        self.assertEqual(
            str(reported), later, "recorded_seq must break the tie toward the "
            "later attempt, which is the one the verdict and the Proof panel "
            "both report"
        )
        _, _, validated, post_reasons = self._verdict(proposal_id)
        self.assertTrue(
            validated,
            "the verdict must follow the later, succeeded attempt; got "
            f"{post_reasons}",
        )

    @unittest.skipUnless(
        SECURITY_DATABASE_TESTS,
        "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for RLS checks",
    )
    def test_a_persona_cannot_read_another_personas_proposal(self) -> None:
        proposal_id = self._propose()
        self._cite(proposal_id)
        self._record(proposal_id, "succeeded", True)
        with self.conn.cursor() as cursor:
            cursor.execute("BEGIN")
            try:
                cursor.execute("SET LOCAL ROLE persona_dba")
                visible = cursor.execute(
                    "SELECT count(*) FROM proof.action_proposals "
                    "WHERE proposal_id = %s",
                    (proposal_id,),
                ).fetchone()[0]
                executions = cursor.execute(
                    "SELECT count(*) FROM proof.action_executions "
                    "WHERE proposal_id = %s",
                    (proposal_id,),
                ).fetchone()[0]
            finally:
                cursor.execute("ROLLBACK")
        self.assertEqual(visible, 0)
        self.assertEqual(executions, 0)


@unittest.skipUnless(
    SECURITY_DATABASE_TESTS,
    "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for persona checks",
)
class WaveBAttachGrantTests(unittest.TestCase):
    def test_no_persona_holds_execute_on_the_wave_b_attach_function(self) -> None:
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            _assert_disposable_database(connection)
            for persona in (
                "persona_app_engineer",
                "persona_dba",
                "persona_auditor",
            ):
                with self.subTest(persona=persona):
                    granted = connection.execute(
                        "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (
                            persona,
                            "proof.attach_wave_b_receipt(uuid,uuid,uuid)",
                        ),
                    ).fetchone()[0]
                    self.assertFalse(granted)


@unittest.skipUnless(
    SECURITY_DATABASE_TESTS,
    "set TEST_DATABASE_URL and WORKBENCH_SECURITY_ENABLED=1 for persona checks",
)
class NoDdlPrivilegeTests(unittest.TestCase):
    PERSONAS = ("persona_app_engineer", "persona_dba", "persona_auditor")

    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        _ensure_proof_fixture(cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_no_persona_can_create_an_index_on_the_lab_table(self) -> None:
        for persona in self.PERSONAS:
            with self.subTest(persona=persona):
                row = self.conn.execute(
                    """
                    SELECT
                      has_schema_privilege(%s, 'workbench_lab', 'CREATE'),
                      pg_has_role(%s, c.relowner, 'USAGE'),
                      has_table_privilege(
                        %s, 'workbench_lab.orders', 'INSERT'
                      ),
                      has_table_privilege(
                        %s, 'workbench_lab.orders', 'UPDATE'
                      )
                    FROM pg_class c
                    WHERE c.oid = 'workbench_lab.orders'::regclass
                    """,
                    (persona, persona, persona, persona),
                ).fetchone()
                self.assertEqual(row, (False, False, False, False))

    def test_personas_can_insert_but_not_rewrite_proof(self) -> None:
        for persona in self.PERSONAS:
            for table in (
                "proof.action_proposals",
                "proof.action_proposal_citations",
                "proof.action_executions",
            ):
                with self.subTest(persona=persona, table=table):
                    row = self.conn.execute(
                        """
                        SELECT
                          has_table_privilege(%s, %s, 'UPDATE'),
                          has_table_privilege(%s, %s, 'DELETE'),
                          has_table_privilege(%s, %s, 'INSERT')
                        """,
                        (persona, table, persona, table, persona, table),
                    ).fetchone()
                    self.assertEqual(row, (False, False, True))


class AgentWriteBoundaryTests(unittest.TestCase):
    def test_agent_registry_exposes_exactly_the_seven_readonly_tools(self) -> None:
        from agent.registry import TOOLS

        self.assertEqual(
            set(TOOLS),
            {
                "answer_with_citations",
                "compare_sources",
                "decompose_question",
                "explain_ranking",
                "follow_evidence_links",
                "search_evidence",
                "synthesize_cited_answer",
            },
        )
