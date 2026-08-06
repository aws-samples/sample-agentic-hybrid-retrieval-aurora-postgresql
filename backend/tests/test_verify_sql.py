"""The _verify_sql descriptor contract (A3 identity envelope).

Pure string construction — no database. These assertions are the reason the
envelope can be trusted: they prove the pasted text and the replayed statement
carry the same SELECT and the same identity.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import db, verify_sql


class VerifySqlEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Pin the mode rather than reading it: these are assertions about what
        # each mode emits, so a developer's .env must not decide which branch
        # the "core" tests exercise.
        settings_patch = patch.object(verify_sql, "get_settings")
        self.get_settings = settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.get_settings.return_value = SimpleNamespace(
            workbench_security_enabled=False
        )

    def test_core_descriptor_carries_statement_binds_and_no_role(self) -> None:
        descriptor = verify_sql.receipt_verify_sql("rr_9b41d7", "dba")["run"]
        self.assertEqual(descriptor["binds"], {"run_id": "rr_9b41d7"})
        self.assertIsNone(descriptor["set_role"])
        self.assertNotIn("SET LOCAL ROLE", descriptor["statement"])
        self.assertTrue(descriptor["statement"].lstrip().upper().startswith("SELECT"))

    def test_core_rendered_text_is_the_pasteable_envelope(self) -> None:
        rendered = verify_sql.receipt_verify_sql("rr_9b41d7", "auditor")["run"][
            "rendered"
        ]
        lines = [line for line in rendered.splitlines() if line.strip()]
        self.assertEqual(lines[0], "BEGIN;")
        self.assertTrue(lines[1].startswith("SELECT"))
        self.assertNotIn("SET LOCAL ROLE", rendered)
        self.assertEqual(lines[-1], "ROLLBACK;")

    def test_security_descriptor_includes_the_persona_role(self) -> None:
        self.get_settings.return_value = SimpleNamespace(
            workbench_security_enabled=True
        )

        descriptor = verify_sql.receipt_verify_sql("rr_9b41d7", "auditor")["run"]
        lines = [line for line in descriptor["rendered"].splitlines() if line.strip()]

        self.assertEqual(descriptor["set_role"], "SET LOCAL ROLE persona_auditor")
        self.assertEqual(lines[0], "BEGIN;")
        self.assertEqual(lines[1], "SET LOCAL ROLE persona_auditor;")
        self.assertTrue(lines[2].startswith("SELECT"))
        self.assertEqual(lines[-1], "ROLLBACK;")

    def test_rendered_text_inlines_the_binds_so_a_paste_runs_as_is(self) -> None:
        rendered = verify_sql.receipt_verify_sql("rr_9b41d7", "app_engineer")["run"][
            "rendered"
        ]
        self.assertIn("'rr_9b41d7'", rendered)
        self.assertNotIn("%(run_id)s", rendered)

    def test_every_persona_is_accepted_and_nothing_else_is(self) -> None:
        for persona in ("app_engineer", "dba", "auditor"):
            with self.subTest(persona=persona):
                verify_sql.receipt_verify_sql("rr_1", persona)
        with self.assertRaisesRegex(ValueError, "unknown persona"):
            verify_sql.receipt_verify_sql("rr_1", "support-lead")

    def test_the_role_naming_rule_matches_the_connection_layer(self) -> None:
        """verify_sql derives the role name without importing db; keep them equal."""
        for persona in db.PERSONAS:
            with self.subTest(persona=persona):
                self.assertEqual(
                    verify_sql.persona_role(persona),
                    db.persona_role(persona),
                )

    def _every_descriptor(self) -> list[tuple[str, dict[str, object]]]:
        """Return (label, descriptor) for every descriptor the registry publishes."""
        named = list(verify_sql.receipt_verify_sql("rr_1", "app_engineer").items())
        named.extend(
            verify_sql.supervision_verify_sql(
                "rr_1",
                "app_engineer",
                "22222222-2222-2222-2222-222222222222",
            ).items()
        )
        named.append(
            (
                "corpus.distribution",
                verify_sql.corpus_distribution_verify_sql("app_engineer"),
            )
        )
        named.append(("graph.edge", verify_sql.edge_verify_sql("edge-1", "app_engineer")))
        named.append(
            (
                "timeline.event",
                verify_sql.event_verify_sql(
                    "11111111-1111-1111-1111-111111111111", "app_engineer"
                ),
            )
        )
        return named

    def test_supervision_citation_descriptor_is_proposal_bound(self) -> None:
        descriptors = verify_sql.supervision_verify_sql(
            "rr_1",
            "dba",
            "22222222-2222-2222-2222-222222222222",
        )

        self.assertEqual(
            descriptors["citations"]["binds"],
            {"proposal_id": "22222222-2222-2222-2222-222222222222"},
        )
        self.assertNotIn("run_id", descriptors["citations"]["binds"])
        self.assertIn(
            "proof.validate_answer_citations",
            descriptors["citations"]["statement"],
        )
        self.assertIn(
            "WITH selected_proposal AS",
            descriptors["execution"]["statement"],
        )
        self.assertIn(
            "ON proposal.proposal_id = execution.proposal_id",
            descriptors["execution"]["statement"],
        )

    def test_no_statement_carries_a_semicolon(self) -> None:
        """The single-SELECT contract, asserted where it runs without a database.

        G-13 enforces this too, but G-13 needs a live cluster and a served run, so
        it cannot catch a stray ';' appended to a SQL constant during ordinary
        editing. A multi-statement ``statement`` is not cosmetic: psycopg cannot
        bind across unparsed statements, ``fetchall()`` returns only the first
        result set, and backend/app/agent.py executes ``statement`` directly to
        build the receipt -- so the panel 503s in production.
        """
        for label, descriptor in self._every_descriptor():
            with self.subTest(descriptor=label):
                self.assertEqual(
                    descriptor["statement"].count(";"),
                    0,
                    f"{label} statement is multi-statement; the pasteable "
                    f"envelope belongs in 'rendered'",
                )

    def test_the_persona_cannot_be_defaulted(self) -> None:
        """A defaulted persona would publish SQL under an identity nobody chose."""
        for factory, args in (
            (verify_sql.receipt_verify_sql, ("rr_1",)),
            (verify_sql.supervision_verify_sql, ("rr_1",)),
            (verify_sql.corpus_distribution_verify_sql, ()),
            (verify_sql.edge_verify_sql, ("edge-1",)),
            (verify_sql.event_verify_sql, ("11111111-1111-1111-1111-111111111111",)),
        ):
            with self.subTest(factory=factory.__name__):
                with self.assertRaises(TypeError):
                    factory(*args)  # type: ignore[call-arg]

    def test_element_grain_descriptors_use_the_core_envelope_too(self) -> None:
        edge = verify_sql.edge_verify_sql("edge-1", "dba")
        event = verify_sql.event_verify_sql(
            "11111111-1111-1111-1111-111111111111", "dba"
        )
        for descriptor in (edge, event):
            with self.subTest(descriptor=descriptor["statement"][:40]):
                self.assertIsNone(descriptor["set_role"])
                self.assertEqual(descriptor["rendered"].splitlines()[0], "BEGIN;")
                self.assertNotIn("SET LOCAL ROLE", descriptor["rendered"])
