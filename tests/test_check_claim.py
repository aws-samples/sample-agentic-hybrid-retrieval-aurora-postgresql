"""`scripts/check_claim.py` runs a sentence through the agent's answer-of-record checks."""

import pytest

from scripts import check_claim
from service.models import EvidenceRecord, ProductSummary

VIEWSONIC = 1551237


def summary():
    return ProductSummary(
        product_id=VIEWSONIC,
        sku="B08T7G2TDG",
        title="ViewSonic VG2756-4K 27 Inch 4K Monitor",
        short_description="",
        domain="consumer_electronics",
        category_key="monitor",
        category_path="Electronics > Monitors",
        brand="ViewSonic",
        model="VG2756-4K",
        price_cents=None,
        list_price_cents=None,
        review_count=40,
        availability=None,
        inventory_count=None,
        attributes={},
        tags=[],
    )


def listing():
    return EvidenceRecord(
        evidence_id=901,
        product_id=VIEWSONIC,
        evidence_type="product_spec",
        source_name="Amazon Reviews 2023",
        source_uri="https://example/meta_Electronics.jsonl",
        revision="fdb89c37616d7786",
        title="ViewSonic VG2756-4K listing",
        text="27-inch 4K IPS monitor. USB-C power delivery up to 90W over one cable.",
    )


@pytest.fixture
def records(monkeypatch):
    monkeypatch.setattr(check_claim, "get_product_summaries", lambda ids: [summary()])
    monkeypatch.setattr(check_claim, "listing_record", lambda product_id: listing())


def test_a_figure_the_listing_states_passes(records):
    passed, detail = check_claim.check(
        VIEWSONIC, "The ViewSonic VG2756-4K delivers up to 90W over USB-C [1]."
    )
    assert passed, detail


def test_a_figure_the_listing_does_not_state_is_blocked(records):
    passed, detail = check_claim.check(
        VIEWSONIC, "The ViewSonic VG2756-4K delivers 100W over USB-C [1]."
    )
    assert not passed
    assert "100W" in detail or "100" in detail


def test_a_sentence_without_a_citation_is_blocked(records):
    passed, detail = check_claim.check(
        VIEWSONIC, "The ViewSonic VG2756-4K is a monitor."
    )
    assert not passed
    assert "did not cite" in detail


def test_main_prints_the_record_and_the_verdict(records, capsys):
    sentence = "The ViewSonic VG2756-4K delivers 100W over USB-C [1]."
    code = check_claim.main([str(VIEWSONIC), sentence])
    out = capsys.readouterr().out
    assert code == 1
    assert "[1] product_spec  1551237" in out
    assert out.strip().splitlines()[-1].startswith("BLOCKED")


def test_an_unknown_product_is_named(monkeypatch, capsys):
    monkeypatch.setattr(check_claim, "get_product_summaries", lambda ids: [])
    assert check_claim.main(["42", "Anything [1]."]) == 2
    assert "product 42" in capsys.readouterr().err


def test_the_command_string_is_the_one_participants_type():
    from service.participant_commands import check_claim as command

    assert command(1551237, "…") == 'uv run python scripts/check_claim.py 1551237 "…"'


def test_a_product_without_a_current_listing_is_named_not_a_traceback(
    monkeypatch, capsys
):
    def no_listing(product_id):
        raise LookupError(f"product {product_id} has no current listing record")

    monkeypatch.setattr(check_claim, "get_product_summaries", lambda ids: [summary()])
    monkeypatch.setattr(check_claim, "listing_record", no_listing)

    assert check_claim.main([str(VIEWSONIC), "Anything [1]."]) == 2

    captured = capsys.readouterr()
    assert captured.err.startswith(
        f"Claim check rule: product {VIEWSONIC} has no current"
    )
    assert "Traceback" not in captured.err
    assert captured.out == ""
