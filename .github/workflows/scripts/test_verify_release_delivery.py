from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from verify_release_delivery import ReleaseContractError, verify_delivery

SOURCE_SHA = "a" * 40
BOOTSTRAP = b"#!/bin/bash\nset -euo pipefail\n"


class ReleaseDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.workshop = self.root / "workshop"
        (self.source / "deploy").mkdir(parents=True)
        (self.workshop / "assets").mkdir(parents=True)
        (self.workshop / "static").mkdir(parents=True)
        (self.source / "deploy" / "mosaic-bootstrap.sh").write_bytes(BOOTSTRAP)
        (self.workshop / "assets" / "mosaic-bootstrap.sh").write_bytes(BOOTSTRAP)
        digest = hashlib.sha256(BOOTSTRAP).hexdigest()
        (self.workshop / "contentspec.yaml").write_text(
            "parameters:\n"
            "  - templateParameter: SourceRevision\n"
            f'    defaultValue: "{SOURCE_SHA}"\n'
            "  - templateParameter: BootstrapScriptSha256\n"
            f'    defaultValue: "{digest}"\n',
            encoding="utf-8",
        )
        (self.workshop / "static" / "hybrid-retrieval-main.yml").write_text(
            "Parameters:\n"
            "  SourceRevision:\n"
            "    Type: String\n"
            f"    Default: {SOURCE_SHA}\n"
            "  BootstrapScriptSha256:\n"
            "    Type: String\n"
            f"    Default: {digest}\n"
            "Resources:\n"
            "  CodeEditor:\n"
            "    Properties:\n"
            "      Parameters:\n"
            "        BootstrapScriptSha256: !Ref BootstrapScriptSha256\n",
            encoding="utf-8",
        )
        (self.workshop / "assets" / "hybrid-retrieval-code-editor.yml").write_text(
            "export SOURCE_REVISION='${SourceRevision}'\n"
            "printf '%s' '${BootstrapScriptSha256}' | sha256sum -c -\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def verify(self, *, workshop_dirty: bool = False):
        return verify_delivery(
            self.source,
            self.workshop,
            SOURCE_SHA,
            source_head=SOURCE_SHA,
            workshop_head="e" * 40,
            workshop_dirty=workshop_dirty,
        )

    def test_matching_delivery_emits_sha_bound_evidence(self) -> None:
        evidence = self.verify()
        self.assertEqual(evidence["source_sha"], SOURCE_SHA)
        self.assertEqual(
            evidence["bootstrap_sha256"],
            hashlib.sha256(BOOTSTRAP).hexdigest(),
        )

    def test_missing_workshop_checkout_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ReleaseContractError,
            "MOSAIC_WORKSHOP_REPO",
        ):
            verify_delivery(
                self.source,
                self.root / "missing-workshop",
                SOURCE_SHA,
                source_head=SOURCE_SHA,
            )

    def test_changed_delivery_asset_fails(self) -> None:
        (self.workshop / "assets" / "mosaic-bootstrap.sh").write_bytes(b"changed\n")
        with self.assertRaisesRegex(ReleaseContractError, "differs"):
            self.verify()

    def test_stale_bootstrap_hash_fails(self) -> None:
        path = self.workshop / "contentspec.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                hashlib.sha256(BOOTSTRAP).hexdigest(),
                "b" * 64,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ReleaseContractError,
            "contentspec.BootstrapScriptSha256",
        ):
            self.verify()

    def test_stale_source_pin_fails(self) -> None:
        path = self.workshop / "static" / "hybrid-retrieval-main.yml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(SOURCE_SHA, "c" * 40),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ReleaseContractError,
            "main.SourceRevision",
        ):
            self.verify()

    def test_claimed_sha_must_match_the_checkout(self) -> None:
        with self.assertRaisesRegex(ReleaseContractError, "checked-out source"):
            verify_delivery(
                self.source,
                self.workshop,
                SOURCE_SHA,
                source_head="d" * 40,
            )

    def test_dirty_workshop_checkout_fails(self) -> None:
        with self.assertRaisesRegex(
            ReleaseContractError,
            "uncommitted files",
        ):
            self.verify(workshop_dirty=True)


if __name__ == "__main__":
    unittest.main()
