import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PremiumCohortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads((ROOT / "data" / "premium_cohort_120.json").read_text())

    def test_size_and_distribution(self):
        self.assertEqual(len(self.rows), 120)
        self.assertEqual(
            Counter(row["domain"] for row in self.rows),
            Counter(
                {"consumer_electronics": 48, "running_fitness": 36, "home_office": 36}
            ),
        )

    def test_flagships_and_anchors(self):
        self.assertEqual(sum(row["is_flagship"] for row in self.rows), 6)
        self.assertEqual(sum(row["is_retrieval_anchor"] for row in self.rows), 30)

    def test_shop_pages_are_complete(self):
        self.assertEqual(
            Counter(row["shop_page"] for row in self.rows),
            Counter({i: 12 for i in range(1, 11)}),
        )


if __name__ == "__main__":
    unittest.main()
