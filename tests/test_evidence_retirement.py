"""Retiring a source must change new retrieval without breaking old citations."""

import uuid

import numpy as np
import pytest

from service.catalog_runtime import search_schema
from service.db import connect
from service.models import RetrievalProfile


@pytest.mark.aurora
def test_retired_evidence_is_excluded_from_both_search_methods():
    """Falsifier: remove either is_current predicate from production SQL."""
    profile = RetrievalProfile()
    query = "retirementwitness" + uuid.uuid4().hex
    vector = np.ones(1024, dtype=np.float32)
    with connect() as conn:
        try:
            product_id = conn.execute(
                "SELECT product_id FROM mosaic.product ORDER BY product_id LIMIT 1"
            ).fetchone()["product_id"]
            ids = []
            for current in (True, False):
                row = conn.execute(
                    """INSERT INTO mosaic.product_evidence
                    (product_id,evidence_type,source_name,evidence_title,evidence_text,
                     embedding_text,embedding,is_current)
                    VALUES (%s,'product_qa','Retirement test',%s,%s,%s,%s,%s)
                    RETURNING evidence_id""",
                    (product_id, query, query, query, vector, current),
                ).fetchone()
                ids.append(row["evidence_id"])
            for embedding in (None, vector):
                rows = conn.execute(
                    f"""SELECT evidence_id,lexical_score,semantic_score
                    FROM {search_schema()}.search_product_evidence(
                        %s,%s,%s::vector,ARRAY['product_qa']::mosaic.evidence_type[],
                        %s,%s,%s,%s)""",
                    (
                        product_id,
                        query,
                        embedding,
                        profile.result_limit,
                        profile.rrf_k,
                        profile.fts_limit,
                        profile.semantic_limit,
                    ),
                ).fetchall()
                by_id = {row["evidence_id"]: row for row in rows}
                assert ids[0] in by_id, (
                    "Production search must return the current source witness"
                )
                assert by_id[ids[0]]["lexical_score"] is not None
                if embedding is not None:
                    assert by_id[ids[0]]["semantic_score"] is not None
                assert ids[1] not in by_id, "Retired source leaked into a new result"
            old = conn.execute(
                "SELECT evidence_text FROM mosaic.product_evidence WHERE evidence_id=%s",
                (ids[1],),
            ).fetchone()
            assert old["evidence_text"] == query, (
                "A saved citation must retain its original source"
            )
        finally:
            conn.rollback()
