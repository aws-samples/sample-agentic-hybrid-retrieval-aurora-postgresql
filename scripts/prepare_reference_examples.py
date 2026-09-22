#!/usr/bin/env python3
"""Extract reviewed ESCI/WANDS records without modifying the searchable catalog."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_real_catalog import canonical, sha256


def validate_bundle(bundle: dict) -> dict:
    """Check source identity, unambiguous labels, coverage, and exact feature quotes."""
    categories, datasets, identities = set(), set(), set()
    product_count = 0
    for case in bundle["cases"]:
        categories.add(case["category"])
        dataset = case["dataset"]
        datasets.add(dataset)
        if dataset == "wands" and (
            case["original_query"]["query"] != case["query"]
            or str(case["original_query"]["query_id"]) != str(case["query_id"])
        ):
            raise ValueError(
                "WANDS query rule: wording or ID differs from the source; restore the original query."
            )
        if len(case["products"]) < 2:
            raise ValueError(
                f"Comparison rule: {case['id']} has fewer than two products; add a reviewed contrast."
            )
        for product in case["products"]:
            original = product["original"]
            if sha256(canonical(original)) != product["original_sha256"]:
                raise ValueError(
                    f"Reference integrity rule: {product['source_product_id']} changed; rebuild from the pinned source."
                )
            if str(original["product_id"]) != product["source_product_id"]:
                raise ValueError(
                    "Reference identity rule: product ID differs from its source; join by the original ID."
                )
            labels = product["original_judgments"]
            if (
                not labels
                or len({r.get("esci_label", r.get("label")) for r in labels}) != 1
            ):
                raise ValueError(
                    "Reference label rule: missing or conflicting judgments; exclude the pair and review it."
                )
            for label in labels:
                raw_label = label.get("esci_label", label.get("label"))
                vocabulary = (
                    {"E", "S", "C", "I"}
                    if dataset == "esci"
                    else {"Exact", "Partial", "Irrelevant"}
                )
                if (
                    str(label["query_id"]) != str(case["query_id"])
                    or str(label["product_id"]) != product["source_product_id"]
                    or raw_label != product["label"]
                    or raw_label not in vocabulary
                ):
                    raise ValueError(
                        "Reference label rule: query, product or label differs; preserve the source judgment without relabeling."
                    )
                if dataset == "esci" and (
                    label["product_locale"] != "us"
                    or original["product_locale"] != "us"
                    or label["query"] != case["query"]
                ):
                    raise ValueError(
                        "ESCI join rule: locale or query differs; match product ID and locale together."
                    )
            key = (dataset, case["query_id"], product["source_product_id"])
            if key in identities:
                raise ValueError(
                    f"Reference uniqueness rule: duplicate {key}; keep one reviewed pair."
                )
            identities.add(key)
            for fact in product.get("facts", []):
                if fact["source_token"] not in original.get(
                    "product_features", ""
                ).split("|"):
                    raise ValueError(
                        f"Source feature rule: {fact['source_token']!r} is absent; quote the original feature token."
                    )
                expected = fact["source_token"].split(":", 1)[1].strip().capitalize()
                if fact["value"] != expected:
                    raise ValueError(
                        f"Displayed feature rule: {fact['value']!r} differs from {expected!r}; display the source value."
                    )
            if dataset == "wands" and product.get("catalog_product_id") is not None:
                raise ValueError(
                    "Dataset boundary rule: WANDS has an Amazon catalog ID; remove the invented cross-dataset join."
                )
            product_count += 1
    if categories != {"headphones", "chairs", "monitors"} or datasets != {
        "esci",
        "wands",
    }:
        raise ValueError(
            f"Coverage rule: categories={sorted(categories)}, datasets={sorted(datasets)}; retain all three needs and both sources."
        )
    return {
        "cases": len(bundle["cases"]),
        "products": product_count,
        "categories": sorted(categories),
        "datasets": sorted(datasets),
    }


def file_receipt(path: Path, url: str) -> dict:
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {
        "file": path.name,
        "url": url,
        "sha256": digest,
        "bytes": path.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--esci-products", type=Path, required=True)
    parser.add_argument("--esci-judgments", type=Path, required=True)
    parser.add_argument("--wands-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/evals/references/reviewed_sources.json",
    )
    args = parser.parse_args()
    import pyarrow.parquet as pq

    selection = json.loads((ROOT / "data/evals/references/selection.json").read_text())
    reviewed = json.loads(
        (ROOT / "data/evals/reviewed_product_examples.json").read_text()
    )
    links = {p["parent_asin"]: p for c in reviewed["cases"] for p in c["products"]}
    esci_cases = [c for c in selection["cases"] if c["dataset"] == "esci"]
    asins = list({p["source_product_id"] for c in esci_cases for p in c["products"]})
    esci = pq.read_table(
        args.esci_products,
        filters=[("product_id", "in", asins), ("product_locale", "=", "us")],
    ).to_pylist()
    products = {(r["product_id"], r["product_locale"]): r for r in esci}
    if len(products) != len(esci):
        raise ValueError(
            "ESCI identity rule: duplicate product/locale rows; inspect the source snapshot before joining."
        )
    labels = pq.read_table(
        args.esci_judgments,
        filters=[
            ("query_id", "in", [c["query_id"] for c in esci_cases]),
            ("product_locale", "=", "us"),
        ],
    ).to_pylist()
    esci_labels = defaultdict(list)
    for row in labels:
        esci_labels[(row["query_id"], row["product_id"])].append(row)

    def tsv(name):
        with (args.wands_dir / name).open(newline="") as source:
            return list(csv.DictReader(source, delimiter="\t"))

    wands_products = {r["product_id"]: r for r in tsv("product.csv")}
    wands_queries = {int(r["query_id"]): r for r in tsv("query.csv")}
    wands_labels = defaultdict(list)
    for row in tsv("label.csv"):
        wands_labels[(int(row["query_id"]), row["product_id"])].append(row)
    for case in selection["cases"]:
        if case["dataset"] == "wands":
            case["original_query"] = wands_queries[case["query_id"]]
            if case["query"] != case["original_query"]["query"]:
                raise ValueError(
                    "WANDS query rule: selected query differs; retain its original wording."
                )
        for product in case["products"]:
            pid = product["source_product_id"]
            if case["dataset"] == "esci":
                original = products[(pid, "us")]
                judgments = esci_labels[(case["query_id"], pid)]
                link = links[pid]
                product.update(
                    catalog_product_id=link["product_id"],
                    catalog_source_sha256=link["source_record_sha256"],
                    title_unchanged=original["product_title"]
                    == link["source_label"]["original_title"]
                    and link["source_label"]["title_unchanged"],
                )
                if (
                    not judgments
                    or link["source_label"]["label"] != judgments[0]["esci_label"]
                    or link["source_label"]["query_id"] != case["query_id"]
                ):
                    raise ValueError(
                        "ESCI review rule: saved label differs from the released judgment; correct the review."
                    )
            else:
                original = wands_products[pid]
                judgments = wands_labels[(case["query_id"], pid)]
            product.update(
                original=original,
                original_sha256=sha256(canonical(original)),
                original_judgments=judgments,
            )
    selection["files"] = [
        file_receipt(
            args.esci_products,
            "https://github.com/amazon-science/esci-data/blob/main/shopping_queries_dataset/shopping_queries_dataset_products.parquet",
        ),
        file_receipt(
            args.esci_judgments,
            "https://github.com/amazon-science/esci-data/blob/main/shopping_queries_dataset/shopping_queries_dataset_examples.parquet",
        ),
        *[
            file_receipt(
                args.wands_dir / n,
                f"https://github.com/wayfair/WANDS/blob/main/dataset/{n}",
            )
            for n in ("product.csv", "query.csv", "label.csv")
        ],
    ]
    receipt = validate_bundle(selection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(selection, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    print(json.dumps({**receipt, "bundle_sha256": sha256(canonical(selection))}))


if __name__ == "__main__":
    main()
