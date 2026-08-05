"""Contracts for the config-gated incident lab API routes."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import lab_routes


REPO_ROOT = Path(__file__).resolve().parents[2]


class LabRouteContractTests(unittest.TestCase):
    def test_hot_write_holds_set_local_and_update_in_one_transaction(self) -> None:
        source = (REPO_ROOT / "backend" / "app" / "lab_routes.py").read_text(
            encoding="utf-8"
        )
        body = source.split("def _hot_write")[1].split("\ndef ")[0]
        self.assertIn("with conn.transaction():", body)
        self.assertIn("SET LOCAL statement_timeout", body)
        self.assertIn("SET LOCAL application_name", body)
        transaction_at = body.index("with conn.transaction():")
        for statement in (
            "SET LOCAL statement_timeout",
            "SET LOCAL application_name",
            "UPDATE workbench_lab.orders",
        ):
            self.assertGreater(
                body.index(statement),
                transaction_at,
                f"HC-2 violated: {statement} runs outside the explicit transaction",
            )

    def test_hot_write_sets_both_timeouts(self) -> None:
        source = (REPO_ROOT / "backend" / "app" / "lab_routes.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("connection(timeout=", source)
        self.assertIn("SET LOCAL statement_timeout", source)

    def test_pool_status_performs_no_checkout(self) -> None:
        source = (REPO_ROOT / "backend" / "app" / "lab_routes.py").read_text(
            encoding="utf-8"
        )
        body = source.split("def _pool_status")[1].split("\ndef ")[0]
        self.assertIn("get_stats()", body)
        self.assertNotIn(".connection(", body)
        self.assertNotIn("get_conn", body)

    def test_lab_endpoints_require_a_preopened_pool(self) -> None:
        with patch.object(
            lab_routes,
            "get_settings",
            return_value=SimpleNamespace(
                lab_endpoints_enabled=True,
                db_pool_min_size=1,
                db_pool_max_size=10,
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                lab_routes._require_lab_endpoints()
        self.assertEqual(caught.exception.status_code, 503)
