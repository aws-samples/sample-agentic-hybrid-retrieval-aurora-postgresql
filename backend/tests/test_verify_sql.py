"""The _verify_sql descriptor contract (A3 identity envelope).

Pure string construction — no database. These assertions are the reason the
envelope can be trusted: they prove the pasted text and the replayed statement
carry the same SELECT and the same identity.
"""

from __future__ import annotations

import unittest

from backend.app import db, verify_sql


class VerifySqlEnvelopeTests(unittest.TestCase):
    def test_descriptor_carries_the_statement_binds_role_and_rendering(self) -> None:
        descriptor = verify_sql.receipt_verify_sql("rr_9b41d7", "admin")["run"]
        self.assertEqual(descriptor["binds"], {"run_id": "rr_9b41d7"})
        self.assertEqual(descriptor["set_role"], "SET LOCAL ROLE persona_admin")
        self.assertNotIn("SET LOCAL ROLE", descriptor["statement"])
        self.assertTrue(descriptor["statement"].lstrip().upper().startswith("SELECT"))

    def test_rendered_text_is_the_pasteable_envelope(self) -> None:
        rendered = verify_sql.receipt_verify_sql("rr_9b41d7", "auditor")["run"][
            "rendered"
        ]
        lines = [line for line in rendered.splitlines() if line.strip()]
        self.assertEqual(lines[0], "BEGIN;")
        self.assertEqual(lines[1], "SET LOCAL ROLE persona_auditor;")
        self.assertEqual(lines[-1], "ROLLBACK;")

    def test_rendered_text_inlines_the_binds_so_a_paste_runs_as_is(self) -> None:
        rendered = verify_sql.receipt_verify_sql("rr_9b41d7", "analyst")["run"][
            "rendered"
        ]
        self.assertIn("'rr_9b41d7'", rendered)
        self.assertNotIn("%(run_id)s", rendered)

    def test_every_persona_is_accepted_and_nothing_else_is(self) -> None:
        for persona in ("analyst", "admin", "auditor"):
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
        named = list(verify_sql.receipt_verify_sql("rr_1", "analyst").items())
        named.append(("graph.edge", verify_sql.edge_verify_sql("edge-1", "analyst")))
        named.append(
            (
                "timeline.event",
                verify_sql.event_verify_sql(
                    "11111111-1111-1111-1111-111111111111", "analyst"
                ),
            )
        )
        return named

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
            (verify_sql.edge_verify_sql, ("edge-1",)),
            (verify_sql.event_verify_sql, ("11111111-1111-1111-1111-111111111111",)),
        ):
            with self.subTest(factory=factory.__name__):
                with self.assertRaises(TypeError):
                    factory(*args)  # type: ignore[call-arg]

    def test_element_grain_descriptors_carry_the_envelope_too(self) -> None:
        edge = verify_sql.edge_verify_sql("edge-1", "admin")
        event = verify_sql.event_verify_sql(
            "11111111-1111-1111-1111-111111111111", "admin"
        )
        for descriptor in (edge, event):
            with self.subTest(descriptor=descriptor["statement"][:40]):
                self.assertEqual(
                    descriptor["set_role"], "SET LOCAL ROLE persona_admin"
                )
                self.assertEqual(descriptor["rendered"].splitlines()[0], "BEGIN;")
