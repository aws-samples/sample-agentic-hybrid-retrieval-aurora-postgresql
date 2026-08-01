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
            "rrf_score": score,
            "explanation": {"positions": positions},
        }

    def test_filter_requires_the_seeded_distractor_and_target_scope(self) -> None:
        before = self.write(
            "before.json",
            {
                "results": [
                    {
                        "external_key": "CHG-1840",
                        "cluster_id": "checkout-stage-cluster-01",
                    }
                ]
            },
        )
        after = self.write(
            "after.json",
            {
                "results": [
                    {
                        "external_key": "INC-2047",
                        "cluster_id": CHECKPOINT.TARGET_CLUSTER,
                    }
                ]
            },
        )

        CHECKPOINT.check_filter(before, after)

    def test_filter_rejects_an_out_of_scope_result(self) -> None:
        before = self.write(
            "before.json",
            {"results": [{"external_key": "INC-2044"}]},
        )
        after = self.write(
            "after.json",
            {
                "results": [
                    {
                        "external_key": "INC-2044",
                        "cluster_id": "checkout-stage-cluster-01",
                    }
                ]
            },
        )

        with self.assertRaisesRegex(SystemExit, "out-of-scope evidence"):
            CHECKPOINT.check_filter(before, after)

    def test_fusion_requires_recomputed_scores_and_the_expected_leader_change(
        self,
    ) -> None:
        baseline_weights = {"text": 2.0, "vector": 1.0, "fuzzy": 1.0}
        tuned_weights = {"text": 0.0, "vector": 4.0, "fuzzy": 0.0}
        baseline = self.write(
            "baseline.json",
            {
                "knobs": {"weights": baseline_weights, "rrf_k": 60},
                "results": [
                    self.result(
                        "INC-2047",
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
                        "CASE-7419",
                        text_position=3,
                        semantic_position=1,
                        fuzzy_position=None,
                        weights=tuned_weights,
                    )
                ],
            },
        )

        CHECKPOINT.check_fusion(baseline, tuned)

    def test_agent_requires_traversal_and_comparison_independently(self) -> None:
        plan, traversal, comparison = self.agent_payloads()
        CHECKPOINT.check_agent(plan, traversal, comparison)

        comparison = self.write("empty-comparison.json", {"relationships": []})
        with self.assertRaisesRegex(SystemExit, "source comparison is missing"):
            CHECKPOINT.check_agent(plan, traversal, comparison)

    def agent_payloads(self) -> tuple[str, str, str]:
        plan = self.write(
            "plan.json",
            {
                "identified_keys": ["CHG-1842", "INC-2047"],
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
