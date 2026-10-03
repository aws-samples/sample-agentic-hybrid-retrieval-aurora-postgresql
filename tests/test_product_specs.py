"""Typed listing specs: exact on the lab products, silent when the listing is ambiguous."""

import json
from pathlib import Path

import pytest

from service.product_specs import listing_specs, quote_is_verbatim

FIXTURE = Path(__file__).parent / "fixtures" / "listing_specs_lab_products.json"
LISTINGS = {
    row["parent_asin"]: row for row in json.loads(FIXTURE.read_text())["listings"]
}


def specs_of(asin: str) -> dict:
    row = LISTINGS[asin]
    return listing_specs(row["category_key"], row["original"])


def values(specs: dict) -> dict:
    return {key: spec.value for key, spec in specs.items()}


def test_monitor_states_the_lab_2_requirements():
    assert values(specs_of("B0BSHZHKB7")) == {
        "size_in": 27.0,
        "resolution": "3840x2160",
        "refresh_hz": 60,
        "usb_c_power_w": 90,
    }


def test_headphones_state_noise_cancelling_and_a_microphone():
    assert values(specs_of("B07G95TJ3P")) == {
        "anc": True,
        "microphone": True,
        "wireless": True,
        "form_factor": "over-ear",
    }


def test_chair_states_adjustable_support():
    assert values(specs_of("B095V7RS6S")) == {
        "lumbar_support": "adjustable",
        "armrests": "adjustable",
        "headrest": True,
        "max_weight_lb": 400,
    }


@pytest.mark.parametrize("asin", sorted(LISTINGS))
def test_every_quote_is_verbatim_in_its_named_field(asin):
    row = LISTINGS[asin]
    for key, spec in specs_of(asin).items():
        assert quote_is_verbatim(row["original"], spec), (asin, key, spec)


def test_monitor_charging_ignores_a_numeric_power_source_detail():
    # ViewSonic's details carry "Power Source": "10"; the wattage must come from the USB-C sentence.
    spec = specs_of("B0BSHZHKB7")["usb_c_power_w"]
    assert spec.source == "features[1]"
    assert "90W charging over one cable" in spec.quote


def listing(**fields) -> dict:
    return {
        "title": fields.pop("title", ""),
        "features": fields.pop("features", []),
        "description": [],
        **fields,
    }


@pytest.mark.parametrize(
    "field", ["Connectivity Technology", "Connectivity technologies"]
)
@pytest.mark.parametrize(
    "title", ["USB headset", "Sony WH-CH710N Wireless Bluetooth Headphones"]
)
@pytest.mark.parametrize("connection", ["USB", "USB-C"])
def test_usb_connection_alone_does_not_establish_wired_headphones(
    field, title, connection
):
    original = listing(
        title=title, details={field: connection, "Form Factor": "Over Ear"}
    )
    specs = listing_specs("headphones", original)
    assert "wireless" not in specs
    assert specs["form_factor"].value == "over-ear"


@pytest.mark.parametrize(
    ("connection", "wireless"),
    [("Wired, USB", False), ("Bluetooth, USB", True), ("Wireless", True)],
)
def test_explicit_headphone_connection_keeps_its_evidence(connection, wireless):
    original = listing(details={"Connectivity Technology": connection})
    spec = listing_specs("headphones", original)["wireless"]
    assert spec.value is wireless
    assert spec.source == "details.Connectivity Technology"
    assert spec.quote == connection
    assert quote_is_verbatim(original, spec)


@pytest.mark.parametrize(
    ("category", "original", "key"),
    [
        (
            "headphones",
            listing(features=["Passive noise cancellation minimizes ambient sounds"]),
            "anc",
        ),
        (
            "headphones",
            listing(features=["Noise cancelling microphone for clear calls"]),
            "anc",
        ),
        (
            "headphones",
            listing(
                details={
                    "Special Feature": "Microphone, USB connectivity, Noise-Canceling"
                }
            ),
            "anc",
        ),
        (
            "headphones",
            listing(features=["Wired stereo sound, no microphone"]),
            "microphone",
        ),
        (
            "chair",
            listing(description=["Adjustable arms are sold separately."]),
            "armrests",
        ),
        ("chair", listing(features=["Headrest not included."]), "headrest"),
        (
            "monitor",
            listing(features=["USB-C input and 2 x 3W speakers"]),
            "usb_c_power_w",
        ),
        (
            "monitor",
            listing(
                features=["65W laptop charger sold with the dock, USB-C video input"]
            ),
            "usb_c_power_w",
        ),
        # A details size that contradicts the title with no evidence either way.
        (
            "monitor",
            listing(
                title='Dell UltraSharp U2720Q 27" LCD LED Monitor - 3840 x 2160 4K',
                details={"Screen Size": "14 Inches"},
            ),
            "size_in",
        ),
    ],
)
def test_ambiguous_or_negated_statements_stay_unknown(category, original, key):
    original.setdefault("description", [])
    assert key not in listing_specs(category, original)


@pytest.mark.parametrize(
    ("category", "original", "key", "value"),
    [
        (
            "headphones",
            listing(details={"Noise Control": "Sound Isolation"}),
            "anc",
            False,
        ),
        (
            "headphones",
            listing(title="Studio Headphones with Active Noise Cancelling"),
            "anc",
            True,
        ),
        (
            "monitor",
            listing(features=["USB Type-C with 65W Power Delivery, HDMI, DisplayPort"]),
            "usb_c_power_w",
            65,
        ),
        (
            "chair",
            listing(title="Mesh Office Chair with 4D Adjustable Armrests"),
            "armrests",
            "4D adjustable",
        ),
        (
            "chair",
            listing(details={"Maximum Weight Recommendation 300 Pounds": "Unknown"}),
            "max_weight_lb",
            300,
        ),
        ("chair", listing(details={"Arm Style": "Armless"}), "armrests", "none"),
        # A nominal size beside a viewable one is two statements of the same screen.
        (
            "monitor",
            listing(
                title='Samsung SyncMaster 214T 21.3" LCD Monitor-Silver',
                details={"Screen Size": "21 Inches"},
            ),
            "size_in",
            21.0,
        ),
        # A decimal point does not end the sentence that states the size.
        (
            "monitor",
            listing(features=['Slim 23.8" IPS display with thin bezels']),
            "size_in",
            23.8,
        ),
        # A size in another unit is not read as inches; the title states it.
        (
            "monitor",
            listing(
                title='15" Wide LCD Black', details={"Screen Size": "38.1 Centimeters"}
            ),
            "size_in",
            15.0,
        ),
    ],
)
def test_explicit_statements_are_read(category, original, key, value):
    original.setdefault("description", [])
    assert listing_specs(category, original)[key].value == value


def test_other_categories_have_no_typed_specs():
    assert listing_specs("monitor_stand", LISTINGS["B0BSHZHKB7"]["original"]) == {}


@pytest.mark.parametrize(
    ("original", "size"),
    [
        # AOC E2260SD (1102432): the details carry 22" in centimetres as "Inches".
        (
            listing(
                title='AOC E2260SD 22" LED LCD Monitor - 5 ms',
                details={"Screen Size": "55.8 Inches"},
            ),
            22.0,
        ),
        # Dell U2720Q (1531801): the details block describes a laptop.
        (
            listing(
                title='Dell UltraSharp U2720Q 27" LCD LED Monitor - 3840 x 2160 4K',
                details={
                    "Screen Size": "14 Inches",
                    "Ram Memory Installed Size": "32 GB",
                    "Flash Memory Size": "1 TB",
                },
            ),
            27.0,
        ),
    ],
)
def test_a_disagreement_with_evidence_resolves_to_the_title(original, size):
    original.setdefault("description", [])
    spec = listing_specs("monitor", original)["size_in"]
    assert (spec.value, spec.source) == (size, "title")
    assert quote_is_verbatim(original, spec)


def test_computer_details_do_not_pick_between_several_title_sizes():
    original = listing(
        title='Screen Extender for 13-16" laptops, 14" 1080P',
        details={"Screen Size": "11.6 Inches", "CPU Model": "Unknown"},
    )
    original.setdefault("description", [])
    assert "size_in" not in listing_specs("monitor", original)
