"""Readable descriptions of deterministic filter fixtures, not relevance labels."""

from __future__ import annotations

from typing import Any

LABELS = {
    "active_noise_cancellation": "active noise cancellation",
    "height_adjustable": "height adjustment",
    "carbon_plate": "carbon plate",
    "quiet_typing": "quiet typing",
    "lumbar_support": "lumbar support",
    "support": "support",
    "terrain": "terrain",
    "sensor_type": "sensor type",
    "mounting": "mounting",
    "dimmable": "dimming",
    "tilt_adjustable": "tilt adjustment",
    "oscillating": "oscillation",
    "usb_power": "USB power",
    "resolution": "resolution",
}
UNITS = {
    "battery_hours": ("battery life", "hours"),
    "weight_g": ("weight", "g"),
    "usb_c_power_w": ("USB-C charging output", "W"),
    "noise_level_db": ("noise level", "dB"),
    "size_in": ("screen size", "inches"),
}


def describe_attribute(key: str, value: Any) -> str:
    """Describe the exact equality predicate used by the filter contract."""
    label = LABELS.get(key, key.replace("_", " "))
    if isinstance(value, bool):
        return f"{label}: {'yes' if value else 'no'}"
    if key in UNITS:
        label, unit = UNITS[key]
        return f"{label}: {value} {unit}"
    return f"{label}: {value}"


def describe_filter_case(subcategory: str, ceiling: int, attributes: dict) -> str:
    """State every required feature, including false values and exact amounts."""
    base = f"Find {subcategory.lower()} priced at most ${ceiling}"
    details = "; ".join(describe_attribute(k, v) for k, v in attributes.items())
    return f"{base}; {details}" if details else base
