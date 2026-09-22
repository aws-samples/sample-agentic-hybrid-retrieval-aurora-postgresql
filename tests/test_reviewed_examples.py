"""A stale teaching card must not look like verified current product evidence."""

import copy

import pytest

from scripts.prepare_real_catalog import canonical, sha256
from scripts.verify_reviewed_examples import verify_product


def records():
    original = {"title": "Stand for two screens"}
    digest = sha256(canonical(original))
    text = "Stand for two screens"
    text_hash = sha256(text)
    row = {
        "product_id": 1,
        "parent_asin": "SAMPLE",
        "original": original,
        "source_record_sha256": digest,
        "embedding_text": text,
        "embedding_text_sha256": text_hash,
        "embedded_input_sha256": text_hash,
    }
    review = {
        k: row[k]
        for k in [
            "product_id",
            "parent_asin",
            "source_record_sha256",
            "embedding_text_sha256",
        ]
    }
    review["facts"] = [{"path": ["title"], "quote": text}]
    return review, row


def test_exact_quote_and_unchanged_input_pass():
    verify_product(*records())


@pytest.mark.parametrize(
    "fault",
    ["quote", "identity", "source", "input", "vector_input", "label", "empty_facts"],
)
def test_review_gate_rejects_each_material_mismatch(fault):
    review, row = copy.deepcopy(records())
    if fault == "empty_facts":
        review["facts"] = []
    if fault == "quote":
        review["facts"][0]["quote"] = "Stand for three screens"
    if fault == "identity":
        row["parent_asin"] = "OTHER"
    if fault == "source":
        row["original"]["title"] = "Changed title"
    if fault == "input":
        row["embedding_text"] = "Changed embedding input"
    if fault == "vector_input":
        row["embedded_input_sha256"] = "wrong"
    if fault == "label":
        review["source_label"] = {"product_id": "OTHER", "locale": "us", "label": "E"}
    with pytest.raises(ValueError, match="rule:"):
        verify_product(review, row)
