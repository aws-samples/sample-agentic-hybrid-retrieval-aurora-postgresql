from scripts.filter_case_copy import describe_filter_case


def test_false_requirement_is_not_described_as_present():
    text = describe_filter_case("Headphones", 200, {"active_noise_cancellation": False})
    assert "active noise cancellation: no" in text


def test_exact_wattage_is_not_promised_as_minimum():
    text = describe_filter_case("Monitors", 500, {"usb_c_power_w": 90})
    assert "USB-C charging output: 90 W" in text
    assert "at least" not in text


def test_every_predicate_is_visible_with_units():
    text = describe_filter_case(
        "Headphones",
        200,
        {"battery_hours": 35, "weight_g": 192, "active_noise_cancellation": True},
    )
    assert all(
        part in text
        for part in ["35 hours", "192 g", "cancellation: yes", "at most $200"]
    )
