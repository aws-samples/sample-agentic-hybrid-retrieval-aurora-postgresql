"""Category-specific synthetic specifications and conservative catalog diagnostics.

Existing identities and offers are inputs, not generation targets. These templates
repair documented category collisions; they do not describe real retail products.
"""

from __future__ import annotations

import random
from typing import Any

# Exact category names prevent "monitor" from claiming heart-rate sensors and
# "desk" from claiming lamps. Each entry names evidence of the old wrong schema.
WRONG_SCHEMA_FIELDS: dict[str, set[str]] = {
    "Mesh Office Chairs": {
        "wifi_generation",
        "ethernet_ports",
        "mesh_ready",
        "max_speed_mbps",
    },
    "Monitor Arms": {
        "resolution",
        "refresh_hz",
        "panel",
        "color_gamut_pct",
        "usb_c_power_w",
    },
    "Monitor Light Bars": {"resolution", "refresh_hz", "panel", "color_gamut_pct"},
    "Air Quality Monitors": {"resolution", "refresh_hz", "panel", "size_in"},
    "Heart Rate Monitors": {"resolution", "refresh_hz", "panel", "size_in"},
    "Desk Lamps": {"load_capacity_lb", "depth_in", "width_in"},
    "Desk Dividers": {
        "memory_presets",
        "load_capacity_lb",
        "height_range_in",
        "depth_in",
    },
    "Desk Fans": {"memory_presets", "load_capacity_lb", "height_range_in", "depth_in"},
    "Desktop Organizers": {"moisture_wicking", "sizes", "weather_protection", "fit"},
    "Desktop Air Purifiers": {"moisture_wicking", "sizes", "weather_protection", "fit"},
    "Cable Management": {"gan", "usb_c_pd", "ports", "capacity_mah"},
    "Keyboard Trays": {
        "switch_type",
        "hot_swappable",
        "backlit",
        "quiet_typing",
        "os_compatibility",
    },
    "Game Controllers": {"firmness", "length_cm", "washable"},
    "Shoe Care": {"carbon_plate", "drop_mm", "terrain", "distance", "widths"},
    "Camera Lenses": {"resolution_mp", "video"},
    "Gimbals": {"resolution_mp", "video"},
    "Graphic Tablets": {"processor_tier", "memory_gb", "storage_gb"},
}


def misplaced_fields(category: str, attributes: dict[str, Any]) -> set[str]:
    """Return fields that unambiguously belong to a different product type."""
    return WRONG_SCHEMA_FIELDS.get(category, set()) & attributes.keys()


def category_specifications(
    category: str, rng: random.Random
) -> tuple[dict[str, Any], str, str] | None:
    """Build a plausible fictional specification for an explicitly supported type.

    Args:
        category: Exact catalog subcategory, including capitalization.
        rng: Product-local random source; repairs never depend on row order.

    Returns:
        Attributes, a concise factual description, and a use/trade-off sentence;
        None when the category has no correction template.
    """
    choose = rng.choice
    if category == "Mesh Office Chairs":
        a = {
            "material": "Mesh",
            "lumbar_support": choose(["Fixed", "Adjustable", "Dynamic"]),
            "armrests": choose(["Fixed", "2D", "3D", "4D"]),
            "seat_depth_adjustable": choose([True, False]),
            "max_user_weight_lb": choose([250, 275, 300, 350]),
            "recommended_hours": choose([4, 6, 8, 10]),
            "recline_deg": choose([110, 120, 135]),
            "headrest": choose([True, False]),
        }
        short = f"Mesh chair with {a['lumbar_support'].lower()} lumbar support, {a['armrests']} arms and a {a['max_user_weight_lb']} lb capacity."
        detail = f"The catalog recommends up to {a['recommended_hours']} hours of daily use. The back reclines to {a['recline_deg']} degrees; seat depth is {'adjustable' if a['seat_depth_adjustable'] else 'fixed'}."
    elif category == "Monitor Arms":
        a = {
            "min_screen_in": 17,
            "max_screen_in": choose([27, 32, 34, 38, 49]),
            "max_weight_lb": choose([17.6, 19.8, 22, 26.4]),
            "vesa_pattern_mm": ["75x75", "100x100"],
            "mounting": choose(["Clamp", "Clamp or grommet"]),
            "tilt_deg": [-45, 90],
            "swivel_deg": 180,
            "gas_spring": choose([True, False]),
            "cable_management": True,
        }
        short = f"Monitor arm for 17–{a['max_screen_in']}-inch screens up to {a['max_weight_lb']:g} lb, with VESA mounting."
        detail = f"Supports 75×75 and 100×100 mm VESA patterns with {a['mounting'].lower()} attachment. Check both screen size and weight; a display is not included."
    elif category in {"Desk Lamps", "Monitor Light Bars"}:
        a = {
            "lumens": choose([300, 400, 500, 700]),
            "color_temperature_k": choose(["2700-5000", "3000-6500"]),
            "dimmable": True,
            "power_w": choose([5, 7, 10]),
            "usb_power": True,
            "mounting": "Monitor clip"
            if category == "Monitor Light Bars"
            else "Weighted desk base",
        }
        short = f"Dimmable {a['lumens']}-lumen {'monitor light bar' if category == 'Monitor Light Bars' else 'desk lamp'} with {a['color_temperature_k']} K adjustable light."
        detail = f"Uses {a['power_w']} W through USB power. The {a['mounting'].lower()} keeps the light at the workspace; automatic brightness adjustment is not included."
    elif category == "Air Quality Monitors":
        a = {
            "measures": choose(
                [
                    ["PM2.5", "Temperature", "Humidity"],
                    ["CO2", "Temperature", "Humidity"],
                    ["PM2.5", "VOC", "Temperature", "Humidity"],
                ]
            ),
            "display_type": "LCD",
            "usb_power": True,
            "app_control": choose([True, False]),
            "battery_hours": choose([0, 6, 8]),
        }
        short = "Desktop air monitor for " + ", ".join(a["measures"]) + "."
        detail = f"Readings appear on an LCD screen. {'A companion app is supported.' if a['app_control'] else 'Readings are available on the device only.'} This monitor measures conditions; it does not filter the air."
    elif category == "Heart Rate Monitors":
        a = {
            "sensor_type": "Electrical chest strap",
            "connectivity": ["Bluetooth", "ANT+"],
            "battery_hours": choose([200, 300, 400]),
            "water_rating": "IPX7",
            "weight_g": choose([45, 55, 65]),
            "adjustable_strap": True,
            "onboard_storage": choose([True, False]),
        }
        short = f"Chest-strap heart-rate sensor with Bluetooth, ANT+ and up to {a['battery_hours']} hours of battery life."
        detail = f"The {a['weight_g']} g sensor uses an adjustable strap. {'Onboard storage can retain workouts.' if a['onboard_storage'] else 'A connected receiver is needed to retain workout readings.'} A screen is not included."
    elif category == "Desk Dividers":
        a = {
            "width_in": choose([24, 36, 48, 60]),
            "height_in": choose([16, 18, 24]),
            "material": choose(["Felt", "Recycled PET felt", "Fabric-covered board"]),
            "mounting": choose(["Clamp", "Freestanding"]),
            "thickness_in": 0.5,
        }
        short = f"{a['width_in']} × {a['height_in']}-inch {a['material'].lower()} desk divider with {a['mounting'].lower()} mounting."
        detail = "Adds visual separation between workspaces. It is a privacy divider; no sound-isolation rating is specified."
    elif category == "Desk Fans":
        a = {
            "blade_diameter_in": choose([4, 5, 6]),
            "speed_levels": choose([2, 3, 4]),
            "oscillating": choose([True, False]),
            "power_w": choose([3, 5, 7]),
            "usb_power": True,
            "tilt_adjustable": True,
        }
        short = f"{a['blade_diameter_in']}-inch USB desk fan with {a['speed_levels']} speeds and an adjustable tilt."
        detail = f"Draws {a['power_w']} W. {'Oscillation spreads airflow across the desk.' if a['oscillating'] else 'Airflow stays in one direction; reposition the fan to change it.'} It circulates nearby air rather than cooling an entire room."
    elif category == "Desktop Organizers":
        a = {
            "material": choose(["Bamboo", "Steel", "Recycled plastic", "Felt"]),
            "compartments": choose([3, 4, 5, 6]),
            "width_in": choose([8, 10, 12, 14]),
            "depth_in": choose([4, 5, 6]),
            "modular": choose([True, False]),
            "mounting": "Desktop",
        }
        short = f"{a['width_in']}-inch {a['material'].lower()} desk organizer with {a['compartments']} compartments."
        detail = f"The organizer is {a['depth_in']} inches deep. {'Modular sections can be rearranged.' if a['modular'] else 'The compartment layout is fixed.'} Check the dimensions of the items you plan to store."
    elif category == "Desktop Air Purifiers":
        a = {
            "coverage_sqft": choose([80, 100, 150, 200]),
            "filter_type": "HEPA and activated carbon",
            "speed_levels": 3,
            "power_w": choose([10, 15, 20]),
            "replaceable_filter": True,
            "filter_change_months": choose([3, 6]),
            "app_control": choose([True, False]),
        }
        short = f"Desktop air purifier for up to {a['coverage_sqft']} sq ft, with HEPA and activated-carbon filtration."
        detail = f"Three fan speeds are available. Replace the filter about every {a['filter_change_months']} months under the catalog's stated use; actual replacement depends on conditions. It does not control room temperature."
    elif category == "Cable Management":
        a = {
            "material": choose(["Steel", "Recycled plastic", "Fabric"]),
            "width_in": choose([12, 16, 20, 24]),
            "mounting": choose(["Clamp", "Screw mount"]),
            "max_load_lb": choose([5, 8, 10]),
            "cable_capacity": choose([6, 8, 10, 12]),
        }
        short = f"{a['width_in']}-inch cable organizer with {a['mounting'].lower()} attachment and a {a['max_load_lb']} lb load limit."
        detail = f"Holds up to {a['cable_capacity']} typical desk cables. This is a passive organizer; it supplies neither power nor data connections."
    elif category == "Keyboard Trays":
        a = {
            "width_in": choose([24, 26, 28]),
            "depth_in": choose([10, 11, 12]),
            "mounting": choose(["Clamp", "Under-desk screws"]),
            "tilt_adjustable": choose([True, False]),
            "max_load_lb": choose([10, 15, 20]),
            "slide_out": True,
        }
        short = f"{a['width_in']} × {a['depth_in']}-inch slide-out keyboard tray with a {a['max_load_lb']} lb load limit."
        detail = f"Attaches with {a['mounting'].lower()}. The tray angle is {'adjustable' if a['tilt_adjustable'] else 'fixed'}; the keyboard and mouse are sold separately."
    elif category == "Game Controllers":
        a = {
            "buttons": choose([12, 14, 16]),
            "wireless": choose([True, False]),
            "connectivity": ["USB-C", "Bluetooth"],
            "battery_hours": choose([12, 20, 30]),
            "vibration": True,
            "platforms": choose(
                [["Windows", "Android"], ["Windows", "Linux"], ["Windows", "macOS"]]
            ),
        }
        if not a["wireless"]:
            a.update(connectivity=["USB-C"], battery_hours=0)
        short = f"{a['buttons']}-button {'wireless' if a['wireless'] else 'wired USB'} game controller with vibration feedback."
        detail = f"Supports {', '.join(a['platforms'])}. {'Battery runtime is listed as ' + str(a['battery_hours']) + ' hours.' if a['wireless'] else 'A USB connection is required during play.'} Console compatibility is not specified."
    elif category == "Shoe Care":
        a = {
            "kit_contents": choose(
                [
                    ["Soft brush", "Microfiber cloth", "Cleaning solution"],
                    ["Soft brush", "Microfiber cloth"],
                ]
            ),
            "suitable_materials": ["Mesh", "Synthetic fabric"],
            "portable": True,
            "waterproofing": False,
        }
        short = (
            "Running-shoe care kit with "
            + ", ".join(x.lower() for x in a["kit_contents"])
            + "."
        )
        detail = "Intended for mesh and synthetic-fabric uppers. Test on a small area first; this cleaning kit does not add waterproofing."
    elif category == "Camera Lenses":
        focal, aperture, weight = choose(
            [
                ("35", "f/1.8", 250),
                ("50", "f/1.8", 250),
                ("24-70", "f/2.8", 900),
                ("70-200", "f/4", 900),
            ]
        )
        a = {
            "focal_length_mm": focal,
            "max_aperture": aperture,
            "mount": choose(["E mount", "RF mount", "L mount"]),
            "autofocus": True,
            "stabilization": choose([True, False]),
            "weight_g": weight,
        }
        short = f"{a['focal_length_mm']} mm {a['max_aperture']} autofocus lens for {a['mount']}."
        detail = f"Weighs {a['weight_g']} g. {'Optical stabilization is included.' if a['stabilization'] else 'The lens has no optical stabilization.'} Check camera-mount compatibility; the camera body is not included."
    elif category == "Gimbals":
        a = {
            "axes": 3,
            "payload_kg": choose([1.5, 2, 3, 4.5]),
            "battery_hours": choose([8, 10, 12]),
            "weight_kg": choose([0.8, 1.1, 1.3]),
            "foldable": choose([True, False]),
        }
        short = f"Three-axis camera gimbal with a {a['payload_kg']:g} kg payload limit and {a['battery_hours']}-hour battery rating."
        detail = f"The gimbal weighs {a['weight_kg']:g} kg. {'It folds for transport.' if a['foldable'] else 'The frame does not fold.'} Check the combined camera and lens weight and balance before use."
    elif category == "Graphic Tablets":
        a = {
            "active_area_in": choose(["6x4", "8x5", "10x6"]),
            "pressure_levels": 8192,
            "express_keys": choose([4, 6, 8]),
            "connection": "USB-C",
            "pen_battery_free": True,
            "integrated_display": False,
            "platforms": ["Windows", "macOS"],
        }
        short = f"Pen tablet with a {a['active_area_in'].replace('x', ' × ')}-inch active area and {a['express_keys']} shortcut keys."
        detail = "A battery-free pen supports 8,192 pressure levels. Connect the tablet to a Windows or macOS computer; it has no built-in display or standalone operating system."
    else:
        return None
    return a, short, detail


def repair_catalog_row(source: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Correct documented defects without changing identity, price or stock.

    The returned list explains each correction. Warranty-only repairs change the
    structured offer to agree with the already published description and therefore
    require no new document vector. An unchanged row is returned byte-for-byte.
    """
    import json
    import re

    from scripts.catalog_overrides import compact, text_parts

    row = dict(source)
    category = row["subcategory"]
    attrs = json.loads(row["attributes_json"])
    rng = random.Random(f"mosaic-category-repair-v1:{row['product_id']}")
    changes: list[str] = []
    rewritten = False
    if misplaced_fields(category, attrs):
        generated = category_specifications(category, rng)
        if generated is None:
            raise ValueError(
                f"Catalog category rule: {category} has misplaced fields; add a reviewed correction template."
            )
        original_color = attrs.get("color")
        attrs, short, detail = generated
        if original_color:
            attrs["color"] = original_color
        row["short_description"] = short
        row["long_description"] = short + " " + detail
        changes.append("category-specifications")
        rewritten = True
    if category == "Mechanical Keyboards" and attrs.get("switch_type") == "Scissor":
        attrs["switch_type"] = (
            "Silent Tactile"
            if attrs.get("quiet_typing")
            else rng.choice(["Linear", "Tactile"])
        )
        row["short_description"] = (
            f"{attrs.get('layout', 'Mechanical')} keyboard with {attrs['switch_type'].lower()} switches and {'wireless' if attrs.get('wireless') else 'wired'} input."
        )
        row["long_description"] = (
            row["short_description"]
            + f" The switches are {'hot-swappable' if attrs.get('hot_swappable') else 'not hot-swappable'}. Key backlighting is {'included' if attrs.get('backlit') else 'not included'}. Compatible operating systems: {', '.join(attrs.get('os_compatibility', []))}."
        )
        changes.append("mechanical-switch-type")
        rewritten = True
    if category == "Portable Monitors" and attrs.get("size_in", 0) > 18.5:
        attrs.update(
            size_in=rng.choice([14, 15.6, 16, 17.3]),
            usb_c_power_w=0,
            height_adjustable=False,
            refresh_hz=60,
        )
        attrs["resolution"] = "1920x1200" if attrs["size_in"] == 16 else "1920x1080"
        row["short_description"] = (
            f"{attrs['size_in']:g}-inch portable {attrs.get('panel', 'LCD')} monitor with {attrs['resolution']} resolution at 60 Hz."
        )
        row["long_description"] = (
            row["short_description"]
            + " Provides a second screen for a mobile workspace. The stand has a fixed height, and the monitor does not supply USB-C charging power to a laptop. Check the device's display connection separately from its charging connection."
        )
        changes.append("portable-display-size")
        rewritten = True
    if category == "Acoustic Headphones" and attrs.get("form_factor") == "in-ear":
        attrs.update(
            form_factor="over-ear",
            weight_g=rng.choice([225, 245, 275, 295]),
            water_rating="None",
        )
        row["short_description"] = (
            f"Over-ear wireless headphones, {attrs['weight_g']} g, with {attrs.get('battery_hours', 28)}-hour battery life and {'active noise cancellation' if attrs.get('active_noise_cancellation') else 'passive isolation'}."
        )
        row["long_description"] = (
            row["short_description"]
            + f" {'Multipoint pairing connects to two devices.' if attrs.get('multipoint') else 'Multipoint pairing is not supported.'} A microphone supports calls; no outgoing voice-noise suppression rating is specified. No water-resistance rating is listed."
        )
        changes.append("headphone-form-factor")
        rewritten = True
    # Hard negatives remain unsuitable for the original requested feature, but
    # their product names and category must state what the item actually is.
    if category == "Carbon Racing Shoes" and attrs.get("carbon_plate") is False:
        row["subcategory"] = "Road Running Shoes"
        old = "Carbon Racing Shoe"
        for key in ["title", "short_description", "long_description"]:
            row[key] = row[key].replace(old, "Non-Plated Road Running Shoe")
        changes.append("nonplated-shoe-category")
        rewritten = True
    if (
        category == "Electric Standing Desks"
        and attrs.get("height_adjustable") is False
    ):
        row["subcategory"] = "Fixed Desks"
        for key in ["title", "short_description", "long_description"]:
            row[key] = row[key].replace("Electric Standing Desk", "Fixed-Height Desk")
        attrs.update(height_range_in="29-30", memory_presets=0)
        row["short_description"] = (
            f"Fixed-height desk with a {attrs.get('width_in', 48)} × {attrs.get('depth_in', 24)}-inch work surface."
        )
        row["long_description"] = (
            row["short_description"]
            + f" Supports up to {attrs.get('load_capacity_lb', 110)} lb. The worktop height is fixed; it has no electric lift or sitting-to-standing adjustment."
        )
        changes.append("fixed-height-desk-category")
        rewritten = True
    if category == "Fixed Desks" and attrs.get("height_adjustable") is True:
        attrs.update(height_adjustable=False, height_range_in="29-30", memory_presets=0)
        row["short_description"] = (
            f"Fixed-height desk with a {attrs.get('width_in', 48)} × {attrs.get('depth_in', 24)}-inch work surface."
        )
        row["long_description"] = (
            row["short_description"]
            + f" Supports up to {attrs.get('load_capacity_lb', 110)} lb. The desktop stays at its set height; it does not move between sitting and standing positions."
        )
        changes.append("fixed-desk-height")
        rewritten = True
    leak = " This product intentionally resembles a nearby search intent but lacks one decisive requested capability."
    if (
        "certified_platforms" in attrs
        and "No platform approvals are claimed" in row["long_description"]
    ):
        del attrs["certified_platforms"]
        row["attributes_json"] = compact(attrs)
        changes.append("disclaimed-certification")
    if leak in row["long_description"]:
        row["long_description"] = row["long_description"].replace(leak, "")
        changes.append("authoring-instruction")
    malformed = {
        "AR Glasse": "AR Glasses",
        "Sports Sunglasse": "Sports Sunglasses",
        "Camera Lense": "Camera Lens",
        "Network Switche": "Network Switch",
        "KVM Switche": "KVM Switch",
        "Weight Benche": "Weight Bench",
        "Pilates Accessorie": "Pilates Accessory",
    }
    for old, new in malformed.items():
        # Word boundary prevents repairing an already-correct plural again.
        pattern = re.compile(re.escape(old) + r"\b")
        if pattern.search(row["title"]):
            for key in ["title", "short_description", "long_description"]:
                row[key] = pattern.sub(new, row[key])
            changes.append("product-name-grammar")
    match = re.search(r"Warranty: (\d+) months", row["long_description"])
    if match and int(match[1]) != int(row["warranty_months"]):
        row["warranty_months"] = match[1]
        changes.append("warranty-offer-agreement")
    if rewritten:
        row["attributes_json"] = compact(attrs)
        row["tags_json"] = compact(
            [row["category"].lower(), row["subcategory"].lower()]
        )
        aliases = [
            row["brand"],
            row["model"],
            f"{row['brand']} {row['model']}",
            row["subcategory"],
        ]
        row["aliases_json"] = compact(aliases)
    if any(
        row[k] != source[k]
        for k in [
            "title",
            "short_description",
            "long_description",
            "attributes_json",
            "tags_json",
            "aliases_json",
            "subcategory",
        ]
    ):
        row["search_text"], row["embedding_text"] = text_parts(
            row,
            json.loads(row["attributes_json"]),
            json.loads(row["tags_json"]),
            json.loads(row["aliases_json"]),
        )
    return row, changes
