#!/usr/bin/env python3
"""Stage Amazon PQA buyer questions and community answers for products in a staged catalog.

Amazon PQA (https://registry.opendata.aws/amazon-pqa/, CDLA-Permissive-1.0) holds
questions asked on product listings and the answers other customers gave. Only
questions for products in the staged catalog are kept, at most --per-product
each, joined by the listing ASIN or a review-evidence variant ASIN. Answers are
other customers' opinions and are labelled as such wherever they appear.

`stage` selects from the downloaded files against the staged catalog, writes a
compact export the release archive carries, and loads it. `load` loads such an
export, which is what a fresh bootstrap does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_real_catalog import canonical, sha256
from scripts.stage_real_catalog import require_aurora_writer, validate_dsn

SOURCE = "https://registry.opendata.aws/amazon-pqa/"
FILE_URL = "https://amazon-pqa.s3.amazonaws.com/{name}"
LICENSE = "CDLA-Permissive-1.0"
FILES = (
    "amazon_pqa_monitors.json",
    "amazon_pqa_over-ear_headphones.json",
    "amazon_pqa_earbud_headphones.json",
    "amazon_pqa_headsets.json",
    "amazon_pqa_chairs.json",
)


def create_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mosaic_catalog_stage.question_evidence (
            dataset_id text NOT NULL REFERENCES mosaic_catalog_stage.dataset,
            question_id text NOT NULL,
            parent_asin text NOT NULL,
            asin text NOT NULL,
            original jsonb NOT NULL,
            source_record_sha256 text NOT NULL,
            source_file text NOT NULL,
            source_file_sha256 text NOT NULL,
            source_reference text NOT NULL,
            license text NOT NULL,
            PRIMARY KEY (dataset_id, question_id),
            FOREIGN KEY (dataset_id, parent_asin)
                REFERENCES mosaic_catalog_stage.product(dataset_id, parent_asin),
            CHECK (original->>'asin' = asin)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS staged_question_product_idx ON mosaic_catalog_stage.question_evidence(dataset_id, parent_asin)"
    )


def question_record(raw: dict) -> dict | None:
    """Keep the question, its answers and the listing facts PQA attached; drop malformed rows."""
    question = raw.get("question_text")
    answers = [
        answer.get("answer_text").strip()
        for answer in raw.get("answers") or []
        if isinstance(answer, dict)
        and isinstance(answer.get("answer_text"), str)
        and answer["answer_text"].strip()
    ]
    if (
        not isinstance(raw.get("asin"), str)
        or not isinstance(question, str)
        or not question.strip()
        or not answers
    ):
        return None
    return {
        "question_id": raw.get("question_id"),
        "asin": raw["asin"],
        "question_text": question.strip(),
        "answers": answers[:3],
        "question_type": raw.get("question_type"),
        "item_name": raw.get("item_name"),
        "brand_name": raw.get("brand_name"),
    }


def question_row(record: dict, parent: str, name: str, file_digest: str) -> dict:
    digest = sha256(canonical(record))
    return {
        "question_id": "question-" + digest,
        "parent_asin": parent,
        "asin": record["asin"],
        "original": record,
        "source_record_sha256": digest,
        "source_file": name,
        "source_file_sha256": file_digest,
    }


def verify_question(row: dict) -> None:
    """Reject altered question text, answers or product attribution before ingestion."""
    rebuilt = question_row(
        row["original"],
        row["parent_asin"],
        row["source_file"],
        row["source_file_sha256"],
    )
    if rebuilt != row:
        raise ValueError(
            f"Question integrity rule: {row.get('question_id')} changed; restore the pinned export."
        )


def select_questions(
    directory: Path, parents: set[str], variants: dict[str, str], per_product: int
) -> tuple[list[dict], list[dict]]:
    """Read the downloaded PQA files once, keeping bounded questions per staged product."""
    rows: list[dict] = []
    files: list[dict] = []
    kept_per_product: dict[str, int] = defaultdict(int)
    for name in FILES:
        path = directory / name
        if not path.exists():
            files.append({"name": name, "missing": True})
            continue
        with path.open("rb") as stream:
            file_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        seen = kept = 0
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    raw = json.loads(line)
                except ValueError:
                    continue
                seen += 1
                asin = raw.get("asin")
                parent = asin if asin in parents else variants.get(asin)
                if parent is None:
                    continue
                record = question_record(raw)
                if record is None or kept_per_product[parent] >= per_product:
                    continue
                kept_per_product[parent] += 1
                kept += 1
                rows.append(question_row(record, parent, name, file_digest))
        files.append(
            {
                "name": name,
                "sha256": file_digest,
                "rows_read": seen,
                "questions_kept": kept,
            }
        )
        print(json.dumps(files[-1]), flush=True)
    return rows, files


def export_document(
    dataset: str, per_product: int, rows: list[dict], files: list[dict]
) -> dict:
    return {
        "dataset_id": dataset,
        "source": SOURCE,
        "source_reference": FILE_URL,
        "license": LICENSE,
        "questions_per_product": per_product,
        "files": files,
        "scope": "Buyer questions with community answers for staged products only; answers are other customers' opinions, not specifications.",
        "questions": rows,
    }


def verified_export(path: Path) -> dict:
    document = json.loads(path.read_text())
    if document.get("license") != LICENSE or document.get("source") != SOURCE:
        raise ValueError(
            f"Question source rule: {path.name} names another source or license; use the pinned Amazon PQA export."
        )
    seen: set[str] = set()
    for row in document["questions"]:
        verify_question(row)
        if row["question_id"] in seen:
            raise ValueError(
                f"Question identity rule: {row['question_id']} repeats in {path.name}; rebuild the export."
            )
        seen.add(row["question_id"])
    return document


def load_questions(conn, dataset: str, document: dict) -> dict:
    """Insert verified questions for products the staged dataset really holds."""
    if document["dataset_id"] != dataset:
        raise ValueError(
            f"Question dataset rule: export names {document['dataset_id']!r}, not {dataset!r}; use the matching export."
        )
    rows = document["questions"]
    parents = {row["parent_asin"] for row in rows}
    known = {
        row[0]
        for row in conn.execute(
            "SELECT parent_asin FROM mosaic_catalog_stage.product WHERE dataset_id=%s AND parent_asin=ANY(%s)",
            (dataset, sorted(parents)),
        )
    }
    if parents != known:
        raise ValueError(
            f"Question parent rule: missing staged products {sorted(parents - known)[:5]}; import their exact parent records before joining questions."
        )
    create_table(conn)
    with conn.cursor() as cursor:
        for start in range(0, len(rows), 2000):
            cursor.executemany(
                """INSERT INTO mosaic_catalog_stage.question_evidence
                   (dataset_id,question_id,parent_asin,asin,original,source_record_sha256,source_file,source_file_sha256,source_reference,license)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dataset_id,question_id) DO NOTHING""",
                [
                    (
                        dataset,
                        row["question_id"],
                        row["parent_asin"],
                        row["asin"],
                        Jsonb(row["original"]),
                        row["source_record_sha256"],
                        row["source_file"],
                        row["source_file_sha256"],
                        FILE_URL.format(name=row["source_file"]),
                        LICENSE,
                    )
                    for row in rows[start : start + 2000]
                ],
            )
    conn.commit()
    return {
        "dataset_id": dataset,
        "questions": len(rows),
        "products": len(parents),
        "files": document["files"],
        "scope": document["scope"],
    }


def staged_parents(conn, dataset: str) -> tuple[set[str], dict[str, str]]:
    parents = {
        row[0]
        for row in conn.execute(
            "SELECT parent_asin FROM mosaic_catalog_stage.product WHERE dataset_id=%s",
            (dataset,),
        )
    }
    variants: dict[str, str] = {}
    if conn.execute(
        "SELECT to_regclass('mosaic_catalog_stage.review_evidence') IS NOT NULL"
    ).fetchone()[0]:
        variants = dict(
            conn.execute(
                "SELECT DISTINCT variant_asin, parent_asin FROM mosaic_catalog_stage.review_evidence WHERE dataset_id=%s",
                (dataset,),
            ).fetchall()
        )
    return parents, variants


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "load"))
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--directory", type=Path, help="downloaded PQA files (stage)")
    parser.add_argument("--per-product", type=int, default=12)
    args = parser.parse_args()
    if args.action == "stage" and args.directory is None:
        parser.error("stage needs --directory")
    dsn = os.environ.get("DATABASE_URL", "")
    validate_dsn(dsn)
    started = time.monotonic()
    with psycopg.connect(
        dsn, connect_timeout=10, application_name="mosaic-question-evidence-stage"
    ) as conn:
        require_aurora_writer(conn, args.dataset_id)
        if args.action == "stage":
            parents, variants = staged_parents(conn, args.dataset_id)
            rows, files = select_questions(
                args.directory, parents, variants, args.per_product
            )
            document = export_document(args.dataset_id, args.per_product, rows, files)
            args.export.parent.mkdir(parents=True, exist_ok=True)
            args.export.write_text(json.dumps(document, ensure_ascii=False) + "\n")
        document = verified_export(args.export)
        report = load_questions(conn, args.dataset_id, document)
    report["seconds"] = round(time.monotonic() - started, 1)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "files"}), flush=True)


if __name__ == "__main__":
    main()
