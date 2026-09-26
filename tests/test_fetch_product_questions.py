"""Buyer questions keep their source identity from selection through export to load."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from scripts import fetch_product_questions as questions


def raw(asin="B000000001", text="Does it charge a MacBook?"):
    return {
        "question_id": "Q1",
        "asin": asin,
        "question_text": text,
        "answers": [{"answer_text": "Yes, at 65 W."}, {"answer_text": " "}],
        "question_type": "yesno",
        "item_name": "Monitor",
        "brand_name": "Acme",
    }


def test_select_keeps_bounded_questions_per_staged_product_by_parent_or_variant(
    tmp_path,
):
    path = tmp_path / questions.FILES[0]
    rows = [
        raw(),
        raw(text="Second?"),
        raw(text="Third?"),
        raw(asin="V0000000001", text="Variant?"),
        raw(asin="X000000000", text="Unknown?"),
        raw(text=" "),
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + "not json\n")
    kept, files = questions.select_questions(
        tmp_path, {"B000000001"}, {"V0000000001": "B000000001"}, per_product=3
    )
    assert [row["original"]["question_text"] for row in kept] == [
        "Does it charge a MacBook?",
        "Second?",
        "Third?",
    ]
    assert kept[0]["parent_asin"] == "B000000001"
    assert files[0]["rows_read"] == 6 and files[0]["questions_kept"] == 3
    assert [f["name"] for f in files if f.get("missing")] == list(questions.FILES[1:])


def test_export_round_trip_verifies_every_row_and_rejects_tampering(tmp_path):
    record = questions.question_record(raw())
    row = questions.question_row(record, "B000000001", "f.json", "0" * 64)
    document = questions.export_document("d", 12, [row], [])
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(document))
    assert questions.verified_export(path)["questions"][0] == row
    tampered = json.loads(path.read_text())
    tampered["questions"][0]["original"]["answers"] = ["No."]
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="Question integrity rule"):
        questions.verified_export(path)
    duplicated = json.loads(json.dumps(document))
    duplicated["questions"].append(row)
    path.write_text(json.dumps(duplicated))
    with pytest.raises(ValueError, match="repeats"):
        questions.verified_export(path)
    path.write_text(json.dumps({**document, "license": "other"}))
    with pytest.raises(ValueError, match="Question source rule"):
        questions.verified_export(path)


def test_load_refuses_a_foreign_dataset_or_a_missing_staged_parent():
    record = questions.question_record(raw())
    row = questions.question_row(record, "B000000001", "f.json", "0" * 64)
    document = questions.export_document("d", 12, [row], [])
    conn = MagicMock()
    with pytest.raises(ValueError, match="Question dataset rule"):
        questions.load_questions(conn, "other", document)
    conn.execute.return_value = []
    with pytest.raises(ValueError, match="Question parent rule"):
        questions.load_questions(conn, "d", document)
    conn.execute.return_value = [("B000000001",)]
    report = questions.load_questions(conn, "d", document)
    assert report["questions"] == 1 and report["products"] == 1
    inserted = conn.cursor.return_value.__enter__.return_value.executemany.call_args[0][
        1
    ]
    assert inserted[0][1] == row["question_id"] and inserted[0][9] == questions.LICENSE
