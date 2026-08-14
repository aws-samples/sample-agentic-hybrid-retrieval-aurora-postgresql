import json
from pathlib import Path

from scripts.build_showcase_commerce_facts import project_commerce_facts

ROOT = Path(__file__).resolve().parents[1]


def test_showcase_commerce_facts_cover_the_premium_cohort() -> None:
    cohort = json.loads(
        (ROOT / "db/data/premium_cohort_120.json").read_text(encoding="utf-8")
    )
    facts = json.loads(
        (ROOT / "data/curated/showcase_commerce_facts_120.json").read_text(
            encoding="utf-8"
        )
    )

    assert facts == project_commerce_facts()
    assert [row["product_id"] for row in facts] == [row["product_id"] for row in cohort]
    assert facts[0] == {
        "availability": "In Stock",
        "currency": "USD",
        "inventory_count": 184,
        "list_price_usd": 329.0,
        "price_usd": 299.0,
        "product_id": 1,
        "rating": 4.8,
        "review_count": 2431,
    }
