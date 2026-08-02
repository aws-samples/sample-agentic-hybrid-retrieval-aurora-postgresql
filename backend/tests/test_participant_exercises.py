from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_checkpoint_module() -> ModuleType:
    module_path = REPOSITORY_ROOT / "labs" / "exercises" / "checkpoint.py"
    spec = importlib.util.spec_from_file_location("participant_checkpoint", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKPOINT = load_checkpoint_module()


class ParticipantCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.suffix = "A1B2C3D4"
        self.run_keys = {
            "incident_key": f"INC-{self.suffix}",
            "unsafe_change_key": f"CHG-{self.suffix}-01",
            "repair_change_key": f"CHG-{self.suffix}-02",
            "lock_key": f"LOCK-{self.suffix}-01",
        }
        self.receipt = self.write(
            "indexing-receipt.json",
            {"run_suffix": self.suffix, **self.run_keys},
        )

    def write(self, name: str, payload: dict) -> str:
        path = self.root / name
        path.write_text(json.dumps(payload))
        return str(path)

    @staticmethod
    def result(
        external_key: str,
        *,
        text_position: int | None,
        semantic_position: int | None,
        fuzzy_position: int | None,
        weights: dict[str, float],
        rrf_k: int = 60,
    ) -> dict:
        positions = {
            "full_text": text_position,
            "semantic": semantic_position,
            "fuzzy": fuzzy_position,
        }
        weighted_positions = (
            ("text", text_position),
            ("vector", semantic_position),
            ("fuzzy", fuzzy_position),
        )
        score = sum(
            0.0 if position is None else weights[arm] / (rrf_k + position)
            for arm, position in weighted_positions
        )
        return {
            "external_key": external_key,
            "source_system": CHECKPOINT.PARTICIPANT_SOURCE_SYSTEM,
            "rrf_score": score,
            "explanation": {"positions": positions},
        }

    def test_filter_requires_mixed_baseline_and_only_live_changes(self) -> None:
        baseline = self.write(
            "baseline.json",
            {
                "results": [
                    {
                        "external_key": self.run_keys["incident_key"],
                        "source_system": CHECKPOINT.PARTICIPANT_SOURCE_SYSTEM,
                        "evidence_kind": "incident",
                    },
                    {
                        "external_key": self.run_keys["unsafe_change_key"],
                        "source_system": CHECKPOINT.PARTICIPANT_SOURCE_SYSTEM,
                        "evidence_kind": "change",
                    }
                ]
            },
        )
        filtered = self.write(
            "filtered.json",
            {
                "results": [
                    {
                        "external_key": self.run_keys["unsafe_change_key"],
                        "source_system": CHECKPOINT.PARTICIPANT_SOURCE_SYSTEM,
                        "evidence_kind": "change",
                    },
                    {
                        "external_key": self.run_keys["repair_change_key"],
                        "source_system": CHECKPOINT.PARTICIPANT_SOURCE_SYSTEM,
                        "evidence_kind": "change",
                    },
                ]
            },
        )

        CHECKPOINT.check_filter(baseline, filtered, self.receipt)

    def test_filter_rejects_an_out_of_scope_result(self) -> None:
        baseline = self.write(
            "baseline.json",
            {
                "results": [
                    {
                        "external_key": "UNEXPECTED-001",
                        "source_system": "unexpected_source",
                        "evidence_kind": "incident",
                    }
                ]
            },
        )
        filtered = self.write(
            "filtered.json",
            {
                "results": [
                    {
                        "external_key": self.run_keys["unsafe_change_key"],
                        "source_system": CHECKPOINT.PARTICIPANT_SOURCE_SYSTEM,
                        "evidence_kind": "change",
                    }
                ]
            },
        )

        with self.assertRaisesRegex(SystemExit, "outside pg_incident_capture"):
            CHECKPOINT.check_filter(baseline, filtered, self.receipt)

    def test_fusion_recomputes_observed_live_scores(self) -> None:
        baseline_weights = {"text": 2.0, "vector": 1.0, "fuzzy": 1.0}
        tuned_weights = {"text": 0.0, "vector": 4.0, "fuzzy": 0.0}
        baseline = self.write(
            "baseline.json",
            {
                "knobs": {"weights": baseline_weights, "rrf_k": 60},
                "results": [
                    self.result(
                        self.run_keys["incident_key"],
                        text_position=1,
                        semantic_position=2,
                        fuzzy_position=None,
                        weights=baseline_weights,
                    )
                ],
            },
        )
        tuned = self.write(
            "tuned.json",
            {
                "knobs": {"weights": tuned_weights, "rrf_k": 60},
                "results": [
                    self.result(
                        self.run_keys["unsafe_change_key"],
                        text_position=3,
                        semantic_position=1,
                        fuzzy_position=None,
                        weights=tuned_weights,
                    )
                ],
            },
        )

        CHECKPOINT.check_fusion(baseline, tuned, self.receipt)

    def test_agent_requires_traversal_and_comparison_independently(self) -> None:
        plan, traversal, comparison = self.agent_payloads()
        CHECKPOINT.check_agent(plan, traversal, comparison, self.receipt)

        comparison = self.write("empty-comparison.json", {"relationships": []})
        with self.assertRaisesRegex(SystemExit, "source comparison is missing"):
            CHECKPOINT.check_agent(
                plan,
                traversal,
                comparison,
                self.receipt,
            )

    def agent_payloads(self) -> tuple[str, str, str]:
        plan = self.write(
            "plan.json",
            {
                "identified_keys": sorted(self.run_keys.values()),
                "subquestions": [
                    {"required_kinds": sorted(CHECKPOINT.REQUIRED_KINDS)}
                ],
            },
        )
        traversal = self.write(
            "traversal.json",
            {
                "reached": [
                    {"via_relation": relation}
                    for relation in sorted(CHECKPOINT.REQUIRED_RELATIONS)
                ]
            },
        )
        comparison = self.write(
            "comparison.json",
            {
                "relationships": [
                    {"relation": relation}
                    for relation in sorted(CHECKPOINT.REQUIRED_RELATIONS)
                ]
            },
        )
        return plan, traversal, comparison


if __name__ == "__main__":
    unittest.main()
