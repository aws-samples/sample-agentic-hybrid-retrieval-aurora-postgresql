"""Source-faithful product and evidence projections for the staged catalog."""

from __future__ import annotations

import inspect
import json
import math
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from scripts.fetch_catalog_metadata import REVISION
from scripts.prepare_real_catalog import canonical, embedding_text, sha256, source_image

SOURCE_NAME = "Amazon Reviews 2023"


def rerank_document(parent_asin: str, source_text: str) -> str:
    """Keep the source identity available when the model reorders search rows."""
    return f"Catalog identity: parent ASIN {parent_asin}.\n{source_text}"


def historical_price(value: Any) -> int | None:
    """Normalize reported USD amounts without turning missing prices into zero."""
    if value is None or (
        isinstance(value, str) and value.strip().lower() in {"", "none", "null", "—"}
    ):
        return None
    try:
        amount = Decimal(str(value))
        cents = amount * 100
        if not amount.is_finite() or amount < 0 or cents != cents.to_integral_value():
            raise InvalidOperation
        return int(cents)
    except InvalidOperation:
        raise ValueError(
            f"Source price rule: {value!r} is not a non-negative USD amount; keep it unnormalized and inspect the source."
        ) from None


def product_kind(categories: list[str]) -> str:
    """Use source taxonomy, never a compatible product name in accessory text."""
    leaf = categories[-1].casefold() if categories else ""
    if leaf == "monitors":
        return "monitor"
    if leaf in {"monitor arms", "monitor stands"}:
        return "monitor_stand"
    if leaf in {
        "over-ear headphones",
        "on-ear headphones",
        "earbud headphones",
        "open-ear headphones",
        "headphones & earbuds",
        "headphones",
        "computer headsets",
        "bluetooth headsets",
        "cell phone headsets",
        "car headphones",
    }:
        return "headphones"
    # A bicycle headset is a different product; a broad substring match would
    # also turn replacement parts and mixed accessory categories into products.
    if leaf == "headsets" and any(
        parent.casefold() in {"telephone accessories", "pc gaming accessories"}
        for parent in categories[:-1]
    ):
        return "headphones"
    if leaf in {
        "managerial & executive chairs",
        "home office desk chairs",
        "home office chairs",
        "desk chairs",
        "task chairs",
        "computer gaming chairs",
        "video game chairs",
        "gaming chairs",
        "kneeling chairs",
        "guest & reception chairs",
        "drafting chairs",
        "stacking chairs",
    }:
        return "chair"
    if leaf in {"chair mats", "carpet chair mats", "hard-floor chair mats"}:
        return "chair_mat"
    if leaf in {"cases", "headphone cases"} and any(
        "headphone" in part.casefold() for part in categories
    ):
        return "headphone_case"
    return "other"


# The source taxonomy files some curtains under Headphones and replacement
# chair bases under Desk Chairs. For the three lab categories the decision is
# made per listing: what the listing sells, read from the first phrase of its
# title, supported by the product type Amazon ranks it in or type-defining
# details. Source records, embedding text and vectors never change.
ACCESSORY_KINDS = {
    "headphones": "headphone_accessory",
    "monitor": "monitor_accessory",
    "chair": "chair_accessory",
}
_TYPE_NOUNS = {
    "headphones": r"head ?phones?|headph|head ?sets?|ear ?buds?|ear ?phones?|earpieces?|stereophones?"
    r"|earsets?|in[- ]ear|airpods|buds|kopfh(?:ö|oe)rer",
    "monitor": r"monitors?|displays?|mntr|lcd|tft",
    "chair": r"\w*chairs?|stools?|seats?|seating|recliners?|rockers?|loungers?",
}
_ACCESSORY_NOUNS = {
    "headphones": r"ear ?pads?|ear ?cushions?|cushions?|padding|headband (?:pads?|cushions?|covers?)"
    r"|ear ?tips|foam tips|tips|ear ?hooks?|ear ?loops?|cables?|cords?|adapters?|splitters?"
    r"|extensions?|stands?|hangers?|holders?|hooks?|cases?|pouch(?:es)?|covers?|skins?"
    r"|decals?|stickers?|chargers?|charging (?:docks?|cases?|cables?)|batter(?:y|ies)"
    r"|dongles?|straps?|clips?|wraps?|protectors?|amplifiers?|amps?|dacs?",
    "monitor": r"arms?|mounts?|stands?|risers?|brackets?|filters?|protectors?|covers?|cases?"
    r"|bags?|sleeves?|cables?|cords?|adapters?|power supply|chargers?|batter(?:y|ies)"
    r"|remotes?|remote controls?|controller boards?|memo boards?|light ?bars?"
    r"|hoods?|shades?|visors?",
    "chair": r"bases?|casters?|wheels?|cylinders?|gas (?:lifts?|springs?)|cushions?"
    r"|slip ?covers?|covers?|arm ?rests?|arm ?pads?|head ?rests?|lumbar (?:pillows?|cushions?)"
    r"|pillows?|glides?|mats?|parts?|kits?|savers?|foot ?rests?|levers?|mechanisms?"
    r"|plates?|pads?|seat pans?|pans?",
}
# Words that make a listing a part for something else, unless the product
# itself follows them, as in "Replacement Headset".
_REPLACEMENT = re.compile(r"\b(?:replacement|spare|conversion|repair)\b", re.IGNORECASE)
# Parts that name the product type they are cut from.
_PARTS = {
    "headphones": None,
    "monitor": re.compile(
        r"\b(?:lcd|led|tft)\s+(?:screen\s+)?panels?\b(?!\s+monitor)|\bcontroller boards?\b",
        re.IGNORECASE,
    ),
    "chair": None,
}
# The sold item ends where the title starts describing inclusions or targets;
# the description ends only where it names another product it serves.
_SOLD_ITEM_END = re.compile(
    r"\s(?:for|with|compatible with|fits|including|includes|plus)\s|\sw/|[,(|:;\[–—]|\s-\s",
    re.IGNORECASE,
)
_TARGET = re.compile(r"\s(?:for|compatible with|fits|designed for)\s", re.IGNORECASE)
_QUANTITY = r"(?:\s+(?:sets?|kits?|packs?|pairs?|pcs|pieces?)(?:\s+of\s+\d+)?)?"
_RANKED_TYPES = {
    "headphones": re.compile(r"headphones|earbuds|headsets", re.IGNORECASE),
    "monitor": re.compile(r"^computer monitors$", re.IGNORECASE),
    "chair": re.compile(r"chairs$", re.IGNORECASE),
}
_RANK_NOT_A_PRODUCT = re.compile(
    r"accessor|case|cable|cord|pad|cushion|mat|part|arm|mount|stand", re.IGNORECASE
)
_DETAIL_TYPES = {
    "headphones": re.compile(
        r"\b(?:in|over|on|open|around|behind)[- ](?:the[- ])?(?:ear|neck)\b"
        r"|earbud|ear ?cup|neckband|true wireless",
        re.IGNORECASE,
    ),
    "monitor": ("Display Resolution Maximum", "Refresh Rate", "Max Screen Resolution"),
    "chair": ("Back Style", "Seat Material Type"),
}
# A screen size with a panel or resolution term names a display even when the
# listing never says "monitor", as in "Samsung S24D300H LED 61CM 24IN Wide".
_MONITOR_SPEC = (
    re.compile(r"\b\d{2}(?:\.\d)?\s*(?:\"|''|in\b|-?inch)", re.IGNORECASE),
    re.compile(
        r"\b(?:led|ips|va|tn|fhd|qhd|wqhd|uhd|1080p|1440p|4k|\d{3,4}\s*x\s*\d{3,4})\b",
        re.IGNORECASE,
    ),
)


def sold_item(title: str) -> str:
    """Return the title's first phrase, which names what the listing sells."""
    end = _SOLD_ITEM_END.search(title)
    return (title[: end.start()] if end else title).strip()


def _type_noun(kind: str) -> re.Pattern[str]:
    return re.compile(rf"\b(?:{_TYPE_NOUNS[kind]})\b", re.IGNORECASE)


def _replaced_part(kind: str, item: str) -> str | None:
    """Name a replacement signal unless it names a complete replacement product."""
    replacement = _REPLACEMENT.search(item)
    if not replacement:
        return None
    # "Headphones Replacement for iPhone" and "Replacement Headset" sell the
    # product itself; "Chair Base Replacement" sells a part.
    before = item[: replacement.start()].rstrip()
    if re.search(rf"\b(?:{_TYPE_NOUNS[kind]})$", before, re.IGNORECASE):
        return None
    rest = item[replacement.end() :]
    product = _type_noun(kind).search(rest)
    accessory = re.compile(rf"\b(?:{_ACCESSORY_NOUNS[kind]})\b", re.IGNORECASE)
    if product and not accessory.search(rest[product.end() :]):
        return None
    return replacement.group(0)


def _accessory_phrase(kind: str, title: str) -> str | None:
    """Name the accessory a listing sells, or None for a complete product."""
    item = sold_item(title)
    if replaced := _replaced_part(kind, item):
        return replaced
    if _PARTS[kind] and (part := _PARTS[kind].search(item)):
        return part.group(0)
    accessory = re.compile(rf"\b(?:{_ACCESSORY_NOUNS[kind]})\b", re.IGNORECASE)
    products = _type_noun(kind).findall(item)
    if not products:
        # "Headrest for Office Chair" sells a headrest; "Flip-up Armrests,
        # ... Swivel Chair" describes a chair whose name comes later.
        description = title[: m.start()] if (m := _TARGET.search(title)) else title
        found = accessory.search(item)
        if found and not _type_noun(kind).search(description):
            return found.group(0)
        return None
    # "Office Chair Base" ends in what it sells; "Earbuds ... Earphone Cable"
    # already named the product before listing its cable.
    trailing = re.search(
        rf"\b(?:{_TYPE_NOUNS[kind]})\s+((?:{_ACCESSORY_NOUNS[kind]})){_QUANTITY}$",
        item,
        re.IGNORECASE,
    )
    return trailing.group(1) if trailing and len(products) == 1 else None


def _title_evidence(kind: str, title: str) -> str | None:
    if _type_noun(kind).search(title):
        return "title names the product type"
    if kind == "monitor" and all(pattern.search(title) for pattern in _MONITOR_SPEC):
        return "title gives a screen size and panel specification"
    return None


def _type_evidence(kind: str, title: str, details: dict) -> str | None:
    """Name the source field that establishes the product type, if any."""
    if found := _title_evidence(kind, title):
        return found
    ranks = details.get("Best Sellers Rank")
    for ranked in ranks if isinstance(ranks, dict) else ():
        if _RANKED_TYPES[kind].search(ranked) and not _RANK_NOT_A_PRODUCT.search(
            ranked
        ):
            return f"best-seller category {ranked!r}"
    rule = _DETAIL_TYPES[kind]
    if isinstance(rule, re.Pattern):
        form = details.get("Form Factor")
        return (
            f"form factor {form!r}"
            if isinstance(form, str) and rule.search(form)
            else None
        )
    present = next((key for key in rule if details.get(key)), None)
    return f"detail {present!r}" if present else None


def classify_product(
    categories: list[str],
    title: str,
    details: dict | None,
    listing_text: str = "",
) -> tuple[str, str]:
    """Classify what a listing sells; return the category key and the reason.

    Args:
        categories: The source taxonomy path, unchanged.
        title: The source title, unchanged.
        details: The source `details` object; missing or malformed counts as empty.
        listing_text: The source features and description, unchanged.

    Returns:
        The derived category key and a reviewable reason for it.
    """
    kind = product_kind(categories)
    if kind not in ACCESSORY_KINDS:
        return kind, "source taxonomy"
    details = details if isinstance(details, dict) else {}
    evidence = _type_evidence(kind, title, details)
    if accessory := _accessory_phrase(kind, title):
        if evidence:
            return ACCESSORY_KINDS[
                kind
            ], f"sells an accessory ({accessory!r}); {evidence}"
        return "other", f"sells {accessory!r} for another product type"
    if evidence:
        return kind, evidence
    # A model-only title such as "Skullcandy Skullcrusher" still describes
    # itself in its features; a curtain filed under Headphones does not.
    if _type_noun(kind).search(listing_text):
        return kind, "features or description name the product type"
    return (
        "other",
        f"no {kind} evidence in title, best-seller categories, details or listing text",
    )


CATEGORY_KEYS = frozenset(
    {
        *ACCESSORY_KINDS,
        *ACCESSORY_KINDS.values(),
        "headphone_case",
        "monitor_stand",
        "chair_mat",
        "other",
    }
)


def reviewed_decisions(lines: list[str], dataset_id: str) -> dict[str, tuple[str, str]]:
    """Parse reviewed per-listing category decisions for one catalog selection.

    The first line names the selection and how the decisions were made; each
    following line is {"parent_asin", "category", "reason"}. A reviewed
    decision replaces the rules' category for that listing, on any source path.

    Args:
        lines: The decisions file, one JSON object per line.
        dataset_id: The catalog selection being prepared.

    Returns:
        Category key and reason for each reviewed parent ASIN.
    """
    header = json.loads(lines[0]) if lines else {}
    if header.get("dataset_id") != dataset_id:
        raise ValueError(
            f"Category decision rule: decisions were reviewed for {header.get('dataset_id')!r}, "
            f"not {dataset_id!r}; review decisions for this selection before preparing it."
        )
    decisions: dict[str, tuple[str, str]] = {}
    for number, line in enumerate(lines[1:], 2):
        row = json.loads(line)
        asin, category = row.get("parent_asin"), row.get("category")
        if category not in CATEGORY_KEYS or not asin or asin in decisions:
            raise ValueError(
                f"Category decision rule: line {number} has {asin!r} -> {category!r}; "
                "use one decision per listing and a known category key."
            )
        decisions[asin] = (category, str(row.get("reason", "")))
    return decisions


def classification_sha256() -> str:
    """Version the complete category decision, rules and code together."""
    module = sys.modules[__name__]
    parts = [
        inspect.getsource(function)
        for function in (
            product_kind,
            sold_item,
            _type_noun,
            _replaced_part,
            _accessory_phrase,
            _title_evidence,
            _type_evidence,
            classify_product,
        )
    ]
    parts += [
        repr(getattr(module, name))
        for name in (
            "ACCESSORY_KINDS",
            "_TYPE_NOUNS",
            "_ACCESSORY_NOUNS",
            "_REPLACEMENT",
            "_PARTS",
            "_SOLD_ITEM_END",
            "_TARGET",
            "_QUANTITY",
            "_RANKED_TYPES",
            "_RANK_NOT_A_PRODUCT",
            "_DETAIL_TYPES",
            "_MONITOR_SPEC",
        )
    ]
    return sha256("\n".join(parts))


def verify_source_product(row: dict) -> dict:
    """Bind every displayed fact to the preserved product and embedding inputs."""
    original = row["original"]
    if (
        original.get("parent_asin") != row["parent_asin"]
        or sha256(canonical(original)) != row["source_record_sha256"]
        or embedding_text(original) != row["embedding_text"]
        or sha256(row["embedding_text"]) != row["embedding_text_sha256"]
    ):
        raise ValueError(
            f"Source product integrity rule: {row['parent_asin']} changed; restore the selected source record and its hashed projection."
        )
    return original


def project_product(row: dict) -> dict:
    """Separate historical offers, source ratings and unreported current facts."""
    original = verify_source_product(row)
    if row["image_url"] != source_image(original):
        raise ValueError(
            f"Source photo rule: {row['parent_asin']} points outside its primary source image; restore the preserved photo URL."
        )
    details = original["details"]
    average, count = original.get("average_rating"), original.get("rating_number")
    rating = None
    if (
        type(average) in (int, float)
        and math.isfinite(average)
        and 1 <= average <= 5
        and type(count) is int
        and count > 0
    ):
        rating = {
            "average": average,
            "count": count,
            "basis": "historical_rating_aggregate",
        }
    brand = details.get("Brand")
    model = details.get("Model Name") or details.get("Item model number")
    condition = (
        "refurbished"
        if re.search(r"\b(?:renewed|refurbished)\b", original["title"], re.IGNORECASE)
        else "unspecified"
    )
    source_price = original.get("price")
    starting_price = isinstance(source_price, str) and source_price.startswith("from ")
    amount = historical_price(source_price[5:] if starting_price else source_price)
    return {
        "identity": f"amazon_reviews_2023:parent:{row['parent_asin']}",
        "parent_asin": row["parent_asin"],
        "identity_kind": "parent_asin",
        "source_name": SOURCE_NAME,
        "source_revision": REVISION,
        "source_record_sha256": row["source_record_sha256"],
        "embedding_text_sha256": row["embedding_text_sha256"],
        "title": original["title"],
        "brand": brand if isinstance(brand, str) and brand.strip() else None,
        "model": model if isinstance(model, str) and model.strip() else None,
        "categories": original["categories"],
        "product_kind": product_kind(original["categories"]),
        "condition": condition,
        "condition_source": "/title" if condition != "unspecified" else None,
        "description": original["description"],
        "features": original["features"],
        "specifications": details,
        "image_url": row["image_url"],
        "listing_url": f"https://www.amazon.com/dp/{row['parent_asin']}",
        "historical_price_cents": None if starting_price else amount,
        "historical_price_min_cents": amount if starting_price else None,
        "historical_price_basis": "starting_at"
        if starting_price
        else "exact"
        if amount is not None
        else "not_reported",
        "historical_price_source_value": source_price,
        "historical_price_currency": "USD",
        "current_price_cents": None,
        "availability": None,
        "inventory_count": None,
        "rating": rating,
        "embedded": row.get("embedding_model_key") is not None,
    }


def specification_evidence(row: dict) -> dict:
    """Reuse source text as evidence without rewriting it into stronger claims."""
    original = verify_source_product(row)
    return {
        "evidence_id": "spec-" + row["source_record_sha256"],
        "parent_asin": row["parent_asin"],
        "variant_asin": None,
        "evidence_type": "product_spec",
        "title": original["title"],
        "text": row["embedding_text"],
        "source_name": SOURCE_NAME,
        "source_revision": REVISION,
        "source_record_sha256": row["source_record_sha256"],
        "source_reference": "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
        f"blob/{REVISION}/raw/meta_categories/meta_{row['source_department']}.jsonl",
        "source_date": None,
        "verified_purchase": None,
        "rating": None,
        "scope": "Historical parent-product listing. Confirm exact variant and current offer separately.",
    }


def question_evidence(row: dict) -> dict:
    """Expose a buyer question with its community answers as its own evidence kind.

    Answers are what other customers said, so the record is labelled as an
    opinion and never carries a rating or a purchase flag.
    """
    original = row["original"]
    if (
        sha256(canonical(original)) != row["source_record_sha256"]
        or original["asin"] != row["asin"]
    ):
        raise ValueError(
            f"Question boundary rule: {row['question_id']} has inconsistent source identity; restore its original record."
        )
    answers = original["answers"]
    text = "Question: " + original["question_text"] + "\n\nAnswer: " + answers[0]
    if len(answers) > 1:
        text += "\n\nOther answers:\n" + "\n".join(
            "- " + answer for answer in answers[1:]
        )
    return {
        "evidence_id": row["question_id"],
        "parent_asin": row["parent_asin"],
        "variant_asin": row["asin"] if row["asin"] != row["parent_asin"] else None,
        "evidence_type": "product_qa",
        "title": original["question_text"],
        "text": text,
        "source_name": "Amazon PQA",
        "source_revision": row.get("source_file_sha256"),
        "source_record_sha256": row["source_record_sha256"],
        "source_reference": row["source_reference"],
        "source_date": None,
        "verified_purchase": None,
        "rating": None,
        "answers": len(answers),
        "license": row.get("license"),
        "scope": "A buyer question and the answers other customers gave about the recorded listing; answers are opinions, not specifications.",
    }


def review_evidence(row: dict) -> dict:
    """Expose the source's review attribution without exposing reviewer identity."""
    original = row["original"]
    if (
        sha256(canonical(original)) != row["source_record_sha256"]
        or original["parent_asin"] != row["parent_asin"]
        or original["asin"] != row["variant_asin"]
    ):
        raise ValueError(
            f"Review product boundary rule: {row['evidence_id']} has inconsistent source identity; restore its original parent and variant."
        )
    return {
        "evidence_id": row["evidence_id"],
        "parent_asin": row["parent_asin"],
        "variant_asin": row["variant_asin"],
        "evidence_type": "customer_review",
        "title": original["title"],
        "text": original["text"],
        "source_name": SOURCE_NAME,
        "source_revision": REVISION,
        "source_record_sha256": row["source_record_sha256"],
        "source_reference": row["source_reference"],
        "source_location": row["source_location"],
        "source_date": datetime.fromtimestamp(original["timestamp"] / 1000, UTC)
        .date()
        .isoformat(),
        "verified_purchase": original["verified_purchase"],
        "rating": original["rating"],
        "helpful_votes": original["helpful_vote"],
        "scope": "One customer's experience of the recorded variant; it does not establish another variant's specifications.",
    }
