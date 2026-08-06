from __future__ import annotations

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INCIDENT_FILES = {
    "capture_observability.py",
    "evidence_builder.py",
    "hold_controller.py",
    "migration.py",
    "prepare_workload.py",
    "query_regression.py",
    "recovery_verifier.py",
    "run_live_workshop.py",
}
EXERCISE_FILES = {
    "checkpoint.py",
    "lab2-filter-request.json",
    "lab2-fusion-request.json",
    "lab2-rrf.sql",
    "lab3-plan-request.json",
    "lab3-traverse-request.json",
    "lab3-compare-request.json",
    "lab4-supervised-execution.md",
}
SECURITY_FILES = {
    "gates/checks.sh",
    "gates/masking_determinism.py",
    "gates/participant_ceremony.py",
    "gates/persona_equivalence.py",
    "gates/rls_enforcement.py",
    "sql/11_roles_rls.sql",
    "sql/12_masking.sql",
}
SUPERVISION_RUNTIME_FILES = {
    "backend/app/action_proposal.py",
    "backend/app/lab_routes.py",
    "backend/app/verify_sql.py",
    "gates/retroactive_safety.py",
    "gates/route_contract.py",
    "gates/wave_additivity.py",
    "sql/13_supervised_execution.sql",
}


class ReleaseArtifactScriptTests(unittest.TestCase):
    def test_participant_exercise_assets_exist(self) -> None:
        exercise_dir = REPOSITORY_ROOT / "labs" / "exercises"
        self.assertTrue(exercise_dir.is_dir())
        for filename in EXERCISE_FILES:
            self.assertTrue((exercise_dir / filename).is_file(), filename)

    def test_live_archive_requires_every_participant_asset(self) -> None:
        source = (
            REPOSITORY_ROOT / "scripts" / "build_live_source_archive.sh"
        ).read_text(encoding="utf-8")

        for filename in INCIDENT_FILES:
            self.assertIn(f"labs/incident/{filename}", source)
        for filename in EXERCISE_FILES:
            self.assertIn(f"labs/exercises/{filename}", source)
        for filename in SECURITY_FILES:
            self.assertIn(filename, source)
        for filename in SUPERVISION_RUNTIME_FILES:
            self.assertIn(filename, source)
        self.assertIn("gates/corpus_diversity.py", source)
        self.assertIn(".claude/skills/extend-hybrid-retrieval/SKILL.md", source)
        self.assertIn("for forbidden in admission design docs/superpowers seed", source)
        self.assertIn("generated evidence or database artifacts", source)
        self.assertNotIn("hybrid-retrieval-seed-v2.dump", source)
        self.assertNotIn("capture_release_aurora.py", source)
        self.assertNotIn("00_setup.sql", source)

    def test_archive_declares_empty_evidence_and_bootstrap_workload(self) -> None:
        source = (
            REPOSITORY_ROOT / "scripts" / "build_live_source_archive.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "evidence state: zero; bootstrap generates operational workload",
            source,
        )


if __name__ == "__main__":
    unittest.main()
