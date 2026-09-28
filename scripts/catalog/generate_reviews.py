#!/usr/bin/env python3
"""Generate deterministic review evidence for a product CSV.

The default creates three reviews per sampled product. Point --products at the
500K catalog and increase --reviews-per-product to generate a much larger
review corpus without changing the canonical product data.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import random
from datetime import date, timedelta
from pathlib import Path

POSITIVE = [
    "The setup was straightforward and the core feature worked exactly as described.",
    "Comfort held up through a full day and the build feels more durable than expected.",
    "The performance-to-price balance is excellent, especially for the intended use case.",
    "I compared several alternatives and kept this one because the practical details were better.",
    "After several weeks, reliability and everyday usability remain strong.",
]
MIXED = [
    "The main feature is effective, although the controls take time to learn.",
    "Performance is good for the price, but one accessory feels less premium.",
    "It works well in my setup; buyers with a different fit or space may prefer another option.",
    "The specifications are accurate, though the real-world benefit depends on how you use it.",
]
NEGATIVE = [
    "The product matched the listing, but it did not solve my specific compatibility need.",
    "Build quality is acceptable, although the fit and finish were not ideal for me.",
    "The headline feature works, but the trade-offs were more noticeable than expected.",
]
TITLES = [
    "Strong everyday choice",
    "Better than expected",
    "Good with a few trade-offs",
    "Solid value",
    "Check compatibility first",
    "Comfortable and reliable",
]


def rng_for(product_id: int, review_no: int, seed: int) -> random.Random:
    raw = f"{seed}:{product_id}:{review_no}".encode()
    return random.Random(
        int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--products", type=Path, default=Path("data/sample/products_5000.csv.gz")
    )
    ap.add_argument(
        "--output", type=Path, default=Path("data/sample/reviews_15000.csv.gz")
    )
    ap.add_argument("--reviews-per-product", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260806)
    args = ap.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "review_id",
        "product_id",
        "rating",
        "title",
        "body",
        "verified_purchase",
        "helpful_votes",
        "review_date",
        "sentiment_score",
    ]
    review_id = 1
    with (
        gzip.open(args.products, "rt", encoding="utf-8", newline="") as src,
        gzip.open(
            args.output, "wt", encoding="utf-8", newline="", compresslevel=1
        ) as dst,
    ):
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=fields)
        writer.writeheader()
        for product in reader:
            pid = int(product["product_id"])
            product_rating = float(product["rating"])
            for n in range(args.reviews_per_product):
                rng = rng_for(pid, n, args.seed)
                rating = max(1, min(5, round(product_rating + rng.gauss(0, 0.9))))
                if rating >= 4:
                    body, sentiment = rng.choice(POSITIVE), rng.uniform(0.45, 0.95)
                elif rating == 3:
                    body, sentiment = rng.choice(MIXED), rng.uniform(-0.10, 0.35)
                else:
                    body, sentiment = rng.choice(NEGATIVE), rng.uniform(-0.85, -0.15)
                body += f" I used it primarily for {product['subcategory'].lower()} and evaluated {product['brand']} {product['model']} against similar options."
                writer.writerow(
                    {
                        "review_id": review_id,
                        "product_id": pid,
                        "rating": rating,
                        "title": rng.choice(TITLES),
                        "body": body,
                        "verified_purchase": str(rng.random() < 0.82).lower(),
                        "helpful_votes": int(rng.expovariate(1 / 8)),
                        "review_date": (
                            date(2026, 8, 6) - timedelta(days=rng.randint(0, 1200))
                        ).isoformat(),
                        "sentiment_score": round(sentiment, 4),
                    }
                )
                review_id += 1
    print(f"Wrote {review_id - 1:,} reviews to {args.output}")


if __name__ == "__main__":
    main()
