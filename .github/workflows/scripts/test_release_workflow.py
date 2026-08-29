from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _job(text: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [A-Za-z][\w-]*:\n|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"workflow has no {name!r} job")
    return match.group("body")


class ReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_tags_run_release_certification(self) -> None:
        self.assertRegex(self.text, r"tags:\s*\n\s+- ['\"]v\*['\"]")
        release = _job(self.text, "aurora-release")
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", release)

    def test_tag_lane_is_non_billed(self) -> None:
        release = _job(self.text, "aurora-release")
        billed = _job(self.text, "scorecard-release")
        self.assertNotIn("score-evals", release)
        self.assertEqual(self.text.count("make score-evals"), 1)
        self.assertIn("github.event_name == 'workflow_dispatch'", billed)
        self.assertIn("inputs.run_billed_scorecard", billed)
        self.assertIn("needs:", billed)
        self.assertIn("aurora-release", billed)

    def test_release_evidence_is_sha_bound_and_always_uploaded(self) -> None:
        release = _job(self.text, "aurora-release")
        billed = _job(self.text, "scorecard-release")
        self.assertIn("make check-bootstrap-release", release)
        self.assertIn("RELEASE_SOURCE_SHA: ${{ github.sha }}", self.text)
        for job in (release, billed):
            self.assertIn("if: ${{ always() }}", job)
            self.assertIn("actions/upload-artifact@", job)

    def test_ordinary_push_cannot_enter_a_release_job(self) -> None:
        release = _job(self.text, "aurora-release")
        billed = _job(self.text, "scorecard-release")
        self.assertIn("github.event_name == 'workflow_dispatch'", release)
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", release)
        self.assertIn("github.event_name == 'workflow_dispatch'", billed)


if __name__ == "__main__":
    unittest.main()
