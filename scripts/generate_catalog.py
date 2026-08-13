#!/usr/bin/env python3
"""Generate the Mosaic synthetic product catalog and retrieval evaluation assets.

The generator is deterministic, streaming, dependency-light, and designed for:
- PostgreSQL FTS and exact lexical retrieval
- pg_trgm typo recovery
- semantic retrieval and HNSW
- metadata filtering
- RRF / weighted fusion
- reranking and explainability

It writes a full gzip-compressed CSV plus compact samples and evaluation files.
Embeddings are intentionally generated separately so the workshop can switch
between Bedrock, local, or deterministic development providers.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import re
import sys
import uuid
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.scripts.transform_legacy_catalog import resolve_category_keys  # noqa: E402

NAMESPACE = uuid.UUID("a6b65282-ccf5-4f7b-9aa4-a0b72bf26420")
TODAY = date(2026, 8, 6)

FIELDS = [
    "product_id", "product_uid", "sku", "domain", "category", "subcategory",
    "brand", "model", "title", "short_description", "long_description",
    "price_usd", "list_price_usd", "currency", "rating", "review_count",
    "availability", "inventory_count", "seller_count", "shipping_days",
    "warranty_months", "return_rate", "popularity_score", "quality_score",
    "freshness_score", "metadata_completeness", "launch_date", "updated_at",
    "source_system", "language", "is_refurbished", "is_sponsored",
    "attributes_json", "tags_json", "aliases_json", "search_text",
    "embedding_text", "challenge_cohorts_json", "canonical_group_id", "image_key"
]

DOMAIN_COUNTS = {
    "consumer_electronics": 210_000,
    "running_fitness": 160_000,
    "home_office": 130_000,
}

FULL_DATASET_FILES = {
    domain: f"products_{domain}.csv.gz"
    for domain in DOMAIN_COUNTS
}

DISTRIBUTION: dict[str, dict[str, dict[str, int]]] = {
    "consumer_electronics": {
        "Audio": {
            "Over-Ear Headphones": 17_000, "True Wireless Earbuds": 13_000,
            "Portable Speakers": 8_000, "Studio Microphones": 5_000,
            "Gaming Headsets": 5_000, "Soundbars": 4_000, "DACs & Amplifiers": 3_000,
        },
        "Computing": {
            "Laptops": 9_000, "Tablets": 7_000, "Portable Monitors": 6_000,
            "Mechanical Keyboards": 5_000, "Wireless Mice": 4_000,
            "Mini PCs": 3_000, "External Storage": 2_000,
        },
        "Mobile & Power": {
            "USB-C Chargers": 7_000, "Power Banks": 6_000, "Phone Cases": 4_000,
            "Charging Docks": 4_000, "Cables & Adapters": 4_000,
        },
        "Wearables": {
            "Smartwatches": 8_000, "Fitness Trackers": 5_000,
            "Smart Rings": 3_000, "Sleep Trackers": 2_000, "AR Glasses": 2_000,
        },
        "Networking": {
            "Wi-Fi Routers": 7_000, "Mesh Wi-Fi Systems": 5_000,
            "Network Switches": 3_000, "Mobile Hotspots": 2_000, "Range Extenders": 1_000,
        },
        "Smart Home": {
            "Security Cameras": 5_000, "Smart Lighting": 4_000,
            "Smart Thermostats": 3_000, "Video Doorbells": 3_000,
            "Smart Plugs": 2_000, "Home Hubs": 1_000,
        },
        "Imaging": {
            "Mirrorless Cameras": 4_000, "Action Cameras": 3_000,
            "Camera Lenses": 3_000, "Photo Printers": 2_000,
            "Gimbals": 1_000, "Digital Binoculars": 1_000,
        },
        "Gaming": {
            "Game Controllers": 4_000, "Gaming Monitors": 4_000,
            "Streaming Capture Cards": 2_000, "Racing Wheels": 2_000,
            "Handheld Consoles": 2_000,
        },
        "Accessories": {
            "Device Stands": 2_500, "Protective Sleeves": 2_000,
            "Travel Organizers": 2_000, "Screen Protectors": 1_500,
            "Cleaning Kits": 1_000, "Remote Controls": 1_000,
        },
    },
    "running_fitness": {
        "Footwear": {
            "Road Running Shoes": 14_000, "Trail Running Shoes": 10_000,
            "Carbon Racing Shoes": 8_000, "Stability Running Shoes": 7_000,
            "Walking Shoes": 6_000, "Cross-Training Shoes": 5_000,
        },
        "Apparel": {
            "Running Tops": 7_000, "Running Shorts": 6_000,
            "Leggings & Tights": 6_000, "Weatherproof Jackets": 5_000,
            "Sports Bras": 3_000, "Compression Wear": 3_000,
        },
        "Wearables": {
            "GPS Running Watches": 6_000, "Heart Rate Monitors": 4_000,
            "Running Pods": 3_000, "Cycling Computers": 3_000,
            "Smart Scales": 2_000,
        },
        "Strength": {
            "Adjustable Dumbbells": 4_000, "Kettlebells": 3_000,
            "Resistance Bands": 3_000, "Weight Benches": 3_000,
            "Pull-Up Systems": 2_000, "Barbells & Plates": 3_000,
        },
        "Yoga & Mobility": {
            "Yoga Mats": 3_500, "Foam Rollers": 2_500,
            "Mobility Tools": 2_000, "Yoga Blocks": 1_500,
            "Balance Trainers": 1_500, "Pilates Accessories": 1_000,
        },
        "Cardio Equipment": {
            "Treadmills": 3_000, "Exercise Bikes": 2_500,
            "Rowing Machines": 1_500, "Ellipticals": 1_500,
            "Jump Ropes": 1_500,
        },
        "Hydration": {
            "Hydration Vests": 2_500, "Running Bottles": 2_000,
            "Insulated Bottles": 1_500, "Electrolyte Mixers": 1_000,
            "Soft Flasks": 1_000,
        },
        "Recovery": {
            "Massage Guns": 2_500, "Recovery Boots": 1_500,
            "Compression Sleeves": 1_500, "Cold Therapy": 1_500,
            "Sleep & Recovery Sensors": 1_000,
        },
        "Accessories": {
            "Running Belts": 1_500, "Sports Sunglasses": 1_500,
            "Running Socks": 1_200, "Reflective Gear": 900,
            "Race Bib Holders": 500, "Shoe Care": 400,
        },
    },
    "home_office": {
        "Seating": {
            "Ergonomic Office Chairs": 9_000, "Mesh Office Chairs": 5_000,
            "Executive Chairs": 3_000, "Kneeling Chairs": 2_000,
            "Active Stools": 2_000, "Guest Chairs": 3_000,
        },
        "Desks": {
            "Electric Standing Desks": 7_000, "Fixed Desks": 4_000,
            "Corner Desks": 3_000, "Standing Desk Converters": 3_000,
            "Compact Desks": 2_000, "Drafting Tables": 1_000,
        },
        "Displays": {
            "Productivity Monitors": 6_000, "Ultrawide Monitors": 3_000,
            "Portable Monitors": 2_000, "Monitor Arms": 3_000,
            "Privacy Screens": 1_000,
        },
        "Input Devices": {
            "Quiet Keyboards": 4_000, "Ergonomic Keyboards": 3_000,
            "Vertical Mice": 2_500, "Trackballs": 1_500,
            "Presentation Remotes": 1_000, "Graphic Tablets": 1_000,
        },
        "Lighting": {
            "Desk Lamps": 4_000, "Monitor Light Bars": 2_000,
            "Video Conference Lights": 2_000, "Floor Lamps": 1_000,
            "Circadian Lighting": 1_000,
        },
        "Video & Audio": {
            "Conference Webcams": 3_000, "Speakerphones": 2_000,
            "USB Microphones": 2_000, "Conference Headsets": 2_000,
            "Acoustic Headphones": 1_000,
        },
        "Organization": {
            "Drawer Units": 2_000, "Desktop Organizers": 2_000,
            "Cable Management": 2_000, "File Cabinets": 1_500,
            "Pegboards": 1_500, "Whiteboards": 1_000,
        },
        "Ergonomics": {
            "Footrests": 2_000, "Laptop Stands": 2_000,
            "Keyboard Trays": 1_500, "Anti-Fatigue Mats": 1_500,
            "Wrist Rests": 1_500, "Lumbar Supports": 1_500,
        },
        "Power & Connectivity": {
            "Docking Stations": 3_000, "USB Hubs": 2_000,
            "Surge Protectors": 1_500, "UPS Battery Backups": 1_500,
            "Wireless Chargers": 1_000, "KVM Switches": 1_000,
        },
        "Acoustics": {
            "Acoustic Panels": 1_500, "Desk Dividers": 1_000,
            "Door Seals": 500, "Sound Masking Devices": 1_000,
        },
        "Air & Environment": {
            "Desktop Air Purifiers": 1_500, "Air Quality Monitors": 1_000,
            "Humidifiers": 750, "Desk Fans": 750,
        },
    },
}

DOMAIN_PREFIXES = {
    "consumer_electronics": ["Auri", "Nova", "Volt", "Pixel", "Luma", "Sonic", "Nexa", "Orbit", "Flux", "Vero", "Echo", "Quantum", "Prism", "Cobalt", "Zenith", "Halo", "Vector", "Meridian", "Nimbus", "Axion"],
    "running_fitness": ["Aero", "Pace", "Stride", "Kinetic", "Peak", "Tempo", "Endura", "Velo", "Motion", "Summit", "Cadence", "Pulse", "Trail", "Forge", "Atlas", "Core", "Swift", "Rise", "Terrain", "Flex"],
    "home_office": ["Ergo", "Form", "Luma", "Desk", "Nook", "Modu", "Work", "Haven", "Axis", "Calm", "Studio", "Frame", "Balance", "Nest", "Arc", "Craft", "Quiet", "Space", "Focus", "Contour"],
}
DOMAIN_SUFFIXES = {
    "consumer_electronics": ["Wave", "Core", "Labs", "Edge", "Works", "Logic", "Tech", "Audio", "Link", "One", "Forge", "Grid", "Pulse", "Vision", "Beam"],
    "running_fitness": ["Run", "Lab", "Works", "One", "Sport", "Motion", "Peak", "Trail", "Fit", "Gear", "Active", "Dynamics", "Endurance", "Athletics"],
    "home_office": ["Works", "Studio", "Office", "Living", "Form", "Space", "Craft", "Systems", "Desk", "Home", "Lab", "Design", "Ergonomics", "Collective"],
}

SOURCE_SYSTEMS = ["PIM", "ERP", "Marketplace", "Catalog API", "Vendor Feed"]
COLORS = ["Midnight", "Graphite", "Cloud White", "Slate", "Silver", "Sand", "Forest", "Ocean", "Plum", "Coral", "Navy", "Charcoal", "Stone", "Sage"]
QUALITY_WORDS = ["Essential", "Core", "Plus", "Pro", "Elite", "Ultra", "Studio", "Air", "Max", "Prime", "Flex", "Tour", "Active", "Edge"]

USE_CASES = {
    "consumer_electronics": ["travel", "hybrid work", "gaming", "content creation", "daily commuting", "small spaces", "home entertainment", "remote collaboration", "mobile productivity", "family use"],
    "running_fitness": ["marathon training", "daily miles", "trail racing", "strength training", "low-impact cardio", "race day", "recovery", "mobility work", "travel workouts", "hot-weather training"],
    "home_office": ["all-day work", "small apartments", "video meetings", "deep focus", "shared workspaces", "creative work", "multi-monitor setups", "standing routines", "quiet offices", "compact rooms"],
}

SYNONYMS = {
    "noise cancelling": ["active noise control", "cabin-noise reduction", "ambient sound suppression", "quiet listening"],
    "long battery life": ["multi-day runtime", "extended playback", "all-day power", "endurance battery"],
    "carbon plate": ["propulsive composite plate", "race-day plate", "rigid energy-return plate", "plated geometry"],
    "ergonomic": ["posture-supportive", "body-aligned", "comfort engineered", "all-day support"],
    "quiet keyboard": ["low-noise typing", "meeting-friendly keystrokes", "soft acoustic profile", "muted key action"],
    "standing desk": ["sit-stand workstation", "height-adjustable desk", "electric lift desk", "variable-height workspace"],
    "water resistant": ["sweat ready", "weather protected", "splash tolerant", "rain-friendly"],
    "lightweight": ["low-mass", "easy-carry", "featherweight feel", "reduced-weight design"],
}

@dataclass(frozen=True)
class ProductContext:
    product_id: int
    domain: str
    category: str
    subcategory: str
    ordinal: int


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def stable_unit(*parts: Any) -> float:
    digest = hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def weighted_choice(rng: random.Random, choices: list[tuple[Any, float]]) -> Any:
    total = sum(w for _, w in choices)
    pick = rng.random() * total
    upto = 0.0
    for value, weight in choices:
        upto += weight
        if pick <= upto:
            return value
    return choices[-1][0]


def make_brands(domain: str, count: int) -> list[str]:
    candidates = []
    for p in DOMAIN_PREFIXES[domain]:
        for s in DOMAIN_SUFFIXES[domain]:
            candidates.append(f"{p}{s}")
    rng = random.Random(f"brands:{domain}")
    rng.shuffle(candidates)
    return candidates[:count]


BRANDS = {
    "consumer_electronics": make_brands("consumer_electronics", 120),
    "running_fitness": make_brands("running_fitness", 90),
    "home_office": make_brands("home_office", 80),
}

CHARGING_SUBCATEGORIES = {
    "usb-c chargers",
    "power banks",
    "charging docks",
    "cables & adapters",
}

APPAREL_SUBCATEGORIES = {
    "running tops",
    "running shorts",
    "leggings & tights",
    "weatherproof jackets",
    "sports bras",
    "compression wear",
    "running socks",
}

ORGANIZATION_SUBCATEGORIES = {
    "drawer units",
    "desktop organizers",
    "cable management",
    "file cabinets",
    "pegboards",
    "whiteboards",
}


def product_rng(seed: int, product_id: int) -> random.Random:
    return random.Random((seed << 32) ^ product_id ^ 0x9E3779B97F4A7C15)


def challenge_cohorts(rng: random.Random, product_id: int) -> list[str]:
    cohorts: list[str] = []
    tests = [
        ("typo_target", 0.040), ("semantic_only", 0.045), ("lexical_only", 0.030),
        ("hard_negative", 0.030), ("hybrid_conflict", 0.025), ("selective_filter", 0.050), ("sparse_metadata", 0.020), ("stale_inventory", 0.020),
        ("fresh_launch", 0.025), ("popularity_bias", 0.030), ("compatibility", 0.050),
        ("review_evidence", 0.080), ("sponsored_low_relevance", 0.012),
    ]
    for name, probability in tests:
        if rng.random() < probability:
            cohorts.append(name)
    if not cohorts and product_id % 17 == 0:
        cohorts.append("baseline")
    return cohorts


def base_price(subcategory: str, rng: random.Random) -> float:
    s = subcategory.lower()
    ranges = [
        (["laptop", "treadmill", "elliptical", "rowing", "standing desk", "executive chair", "mirrorless", "recovery boots"], (350, 2400)),
        (["monitor", "tablet", "smartwatch", "router", "camera lens", "exercise bike", "adjustable dumbbell", "office chair", "desk"], (120, 1100)),
        (["headphone", "earbud", "speaker", "microphone", "keyboard", "mouse", "shoe", "jacket", "webcam", "dock", "air purifier"], (35, 420)),
        (["charger", "power bank", "case", "cable", "band", "bottle", "mat", "roller", "lamp", "organizer", "footrest", "stand"], (9, 180)),
    ]
    lo, hi = (20, 300)
    for needles, bounds in ranges:
        if any(n in s for n in needles):
            lo, hi = bounds
            break
    # Log-ish distribution gives many mid-priced products and a meaningful tail.
    x = rng.betavariate(2.1, 3.2)
    return round(lo + (hi - lo) * x, 2)


def common_metrics(rng: random.Random, cohorts: list[str], launch_date: date) -> dict[str, Any]:
    quality = clamp(rng.betavariate(5.0, 2.1), 0, 1)
    popularity = clamp(rng.betavariate(1.7, 4.0), 0, 1)
    if "popularity_bias" in cohorts:
        popularity = clamp(0.85 + rng.random() * 0.14, 0, 1)
        quality = clamp(0.45 + rng.random() * 0.25, 0, 1)
    rating = round(clamp(3.0 + quality * 2.0 + rng.gauss(0, 0.16), 2.5, 5.0), 1)
    reviews = max(0, int(math.exp(2 + popularity * 7 + rng.gauss(0, 0.7))))
    if "fresh_launch" in cohorts:
        reviews = min(reviews, rng.randint(0, 90))
    completeness = clamp(rng.betavariate(12, 1.8), 0.3, 1.0)
    if "sparse_metadata" in cohorts:
        completeness = rng.uniform(0.35, 0.62)
    age_days = max(0, (TODAY - launch_date).days)
    freshness = math.exp(-age_days / 900)
    return {
        "quality_score": round(quality, 4),
        "popularity_score": round(popularity, 4),
        "rating": rating,
        "review_count": reviews,
        "metadata_completeness": round(completeness, 4),
        "freshness_score": round(freshness, 4),
        "return_rate": round(clamp(0.16 - quality * 0.11 + rng.gauss(0, 0.015), 0.005, 0.35), 4),
    }


def make_model(subcategory: str, ordinal: int, rng: random.Random) -> str:
    prefix = "".join(word[0] for word in subcategory.split()[:3]).upper()
    series = rng.choice(["A", "C", "E", "F", "K", "M", "N", "P", "R", "S", "V", "X", "Z"])
    return f"{prefix}-{series}{(ordinal * 37) % 997:03d}{rng.choice(['', 'X', 'P', 'S'])}"


def sku_segment(subcategory: str) -> str:
    segment = re.sub(r"[^a-z0-9]", "", slug(subcategory))
    if not segment:
        raise ValueError(f"Subcategory cannot form an SKU segment: {subcategory!r}")
    return segment[:5].upper()


def specialized_attributes(ctx: ProductContext, rng: random.Random, cohorts: list[str]) -> tuple[dict[str, Any], list[str], str, str]:
    s = ctx.subcategory.lower()
    attrs: dict[str, Any] = {}
    tags: list[str] = []
    feature = "balanced everyday performance"
    benefit = "reliable performance for everyday use"

    if "headphone" in s or "earbud" in s or "headset" in s:
        anc = rng.random() < (0.72 if "over-ear" in s or "earbud" in s else 0.45)
        battery = rng.randint(14, 82)
        form = "over-ear" if "over-ear" in s or "headset" in s else "in-ear"
        attrs.update({"form_factor": form, "active_noise_cancellation": anc, "battery_hours": battery,
                      "multipoint": rng.random() < 0.62, "microphone": True,
                      "weight_g": rng.randint(190, 360) if form == "over-ear" else rng.randint(4, 10),
                      "codec": rng.choice(["AAC", "aptX Adaptive", "LC3", "SBC", "LDAC"]),
                      "connectivity": ["Bluetooth", rng.choice(["USB-C", "3.5mm", "Wireless USB"])],
                      "water_rating": rng.choice(["None", "IPX4", "IP55", "IP67"]),
                      "foldable": rng.random() < 0.45})
        feature = rng.choice(["adaptive noise control", "clear call pickup", "spatial audio", "low-latency wireless", "natural transparency mode"])
        benefit = rng.choice(["quiet focus on long flights", "clearer calls in noisy rooms", "comfortable all-day listening", "immersive sound without cable clutter"])
        tags += ["audio", form, "wireless"] + (["noise cancelling"] if anc else ["passive isolation"])
    elif "speaker" in s or "soundbar" in s or "amplifier" in s or "dac" in s:
        attrs.update({"power_w": rng.randint(10, 420), "channels": rng.choice(["2.0", "2.1", "3.1", "5.1", "7.1"]),
                      "bluetooth": rng.random() < 0.8, "wifi": rng.random() < 0.55,
                      "water_rating": rng.choice(["None", "IPX5", "IP67"]),
                      "voice_assistant_ready": rng.random() < 0.48})
        feature, benefit = "room-filling tuned audio", "balanced sound across music, film, and calls"
        tags += ["audio", "speaker", "wireless"]
    elif "monitor" in s:
        size = rng.choice([14, 15.6, 24, 27, 32, 34, 38, 40, 49])
        res = rng.choice(["1920x1080", "2560x1440", "3440x1440", "3840x2160", "5120x1440"])
        attrs.update({"size_in": size, "resolution": res, "refresh_hz": rng.choice([60, 75, 100, 120, 144, 165, 240]),
                      "panel": rng.choice(["IPS", "OLED", "VA", "Mini-LED"]), "usb_c_power_w": rng.choice([0, 45, 65, 90, 100]),
                      "color_gamut_pct": rng.randint(88, 100), "height_adjustable": rng.random() < 0.72,
                      "vesa": rng.random() < 0.86})
        feature, benefit = "high-density workspace display", "crisp text and room for side-by-side work"
        tags += ["display", f"{size} inch", res]
    elif "keyboard" in s:
        quiet = "quiet" in s or rng.random() < 0.45
        attrs.update({"layout": rng.choice(["Full Size", "TKL", "75%", "65%", "Split"]),
                      "switch_type": rng.choice(["Linear", "Tactile", "Low Profile", "Scissor", "Silent Tactile"]),
                      "wireless": rng.random() < 0.7, "backlit": rng.random() < 0.65,
                      "hot_swappable": rng.random() < 0.42, "quiet_typing": quiet,
                      "os_compatibility": rng.sample(["Windows", "macOS", "Linux", "ChromeOS"], k=rng.randint(2, 4))})
        feature = "muted key action" if quiet else "precise tactile response"
        benefit = "meeting-friendly typing with less desk noise" if quiet else "fast, confident input for focused work"
        tags += ["keyboard", "input"] + (["quiet"] if quiet else ["mechanical"])
    elif "mouse" in s or "trackball" in s:
        attrs.update({"handedness": rng.choice(["Right", "Ambidextrous"]), "dpi": rng.choice([1600, 2400, 4000, 8000, 16000, 26000]),
                      "wireless": rng.random() < 0.82, "buttons": rng.randint(3, 12),
                      "vertical_angle_deg": rng.choice([0, 15, 35, 57]) if "vertical" in s else 0,
                      "weight_g": rng.randint(55, 145)})
        feature, benefit = "responsive precision tracking", "comfortable control across long work sessions"
        tags += ["mouse", "input", "wireless"]
    elif "laptop" in s or "tablet" in s or "mini pc" in s:
        attrs.update({"memory_gb": rng.choice([8, 16, 24, 32, 64]), "storage_gb": rng.choice([256, 512, 1024, 2048]),
                      "processor_tier": rng.choice(["Efficient", "Mainstream", "Performance", "Creator"]),
                      "battery_hours": rng.randint(7, 24), "weight_kg": round(rng.uniform(0.55, 2.5), 2),
                      "display_in": rng.choice([8.3, 10.9, 11, 13.3, 14, 15.6, 16]),
                      "usb_c": True, "wifi_generation": rng.choice([6, "6E", 7])})
        feature, benefit = "portable multitasking performance", "smooth work across documents, meetings, and creative apps"
        tags += ["computer", "portable", "usb-c"]
    elif s in CHARGING_SUBCATEGORIES:
        attrs.update({"max_power_w": rng.choice([20, 30, 45, 65, 67, 100, 140, 240]),
                      "ports": rng.randint(1, 6), "gan": rng.random() < 0.65,
                      "usb_c_pd": rng.random() < 0.9, "capacity_mah": rng.choice([0, 5000, 10000, 20000, 24000, 27000]) if "power bank" in s else 0,
                      "travel_ready": rng.random() < 0.7})
        feature, benefit = "compact high-output charging", "fewer adapters across travel and desk setups"
        tags += ["power", "usb-c", "charging"]
    elif "router" in s or "wi-fi" in s or "mesh" in s or "network" in s:
        attrs.update({"wifi_generation": rng.choice([6, "6E", 7]), "max_speed_mbps": rng.choice([1800, 3000, 5400, 6600, 11000, 19000]),
                      "coverage_sqft": rng.randint(1200, 8000), "ethernet_ports": rng.randint(2, 12),
                      "mesh_ready": "mesh" in s or rng.random() < 0.6, "security_updates_years": rng.randint(2, 7)})
        feature, benefit = "adaptive whole-home networking", "stable coverage across busy connected homes"
        tags += ["networking", "wifi", "home"]
    elif any(k in s for k in ["camera", "lens", "gimbal", "binocular"]):
        attrs.update({"resolution_mp": rng.choice([12, 20, 24, 33, 45, 61]), "video": rng.choice(["4K30", "4K60", "6K30", "8K30"]),
                      "stabilization": rng.random() < 0.72, "weather_sealed": rng.random() < 0.55,
                      "weight_g": rng.randint(120, 1200), "mount": rng.choice(["Universal", "A-Mount", "R-Mount", "L-Mount", "Micro Four Thirds"])})
        feature, benefit = "detail-rich stabilized capture", "sharper content in motion and changing light"
        tags += ["imaging", "creator", "video"]
    elif any(k in s for k in ["smartwatch", "fitness tracker", "smart ring", "sleep tracker", "gps running watch", "heart rate", "running pod", "recovery sensor", "smart scale"]):
        attrs.update({"battery_days": rng.randint(2, 30), "gps": rng.random() < 0.72, "heart_rate": True,
                      "sleep_tracking": rng.random() < 0.9, "water_rating_atm": rng.choice([3, 5, 10]),
                      "training_readiness": rng.random() < 0.55, "platforms": rng.sample(["iOS", "Android", "Web"], k=rng.randint(2, 3))})
        feature, benefit = "continuous training and recovery insights", "a clearer view of effort, sleep, and readiness"
        tags += ["wearable", "fitness", "health"]
    elif "shoe" in s:
        carbon = "carbon" in s or rng.random() < 0.22
        support = "stability" if "stability" in s else rng.choice(["neutral", "neutral", "mild stability"])
        terrain = "trail" if "trail" in s else "road"
        attrs.update({"terrain": terrain, "support": support, "carbon_plate": carbon,
                      "drop_mm": rng.choice([0, 4, 5, 6, 8, 10, 12]), "weight_g": rng.randint(175, 340),
                      "cushioning": rng.choice(["low", "moderate", "high", "maximum"]),
                      "distance": rng.choice(["5K", "10K", "Half Marathon", "Marathon", "Daily Training", "Ultra"]),
                      "widths": rng.sample(["Narrow", "Standard", "Wide", "Extra Wide"], k=rng.randint(1, 3)),
                      "waterproof": rng.random() < (0.45 if terrain == "trail" else 0.08)})
        feature = "propulsive composite plate" if carbon else rng.choice(["responsive foam geometry", "stable guidance platform", "grippy trail chassis"])
        benefit = rng.choice(["efficient turnover during long efforts", "comfortable daily mileage", "secure footing over mixed terrain", "support through tired late-run form"])
        tags += ["running shoes", terrain, support] + (["carbon plate"] if carbon else [])
    elif s in APPAREL_SUBCATEGORIES:
        attrs.update({"material": rng.choice(["Recycled Polyester", "Merino Blend", "Nylon Elastane", "Polyester Mesh"]),
                      "moisture_wicking": True, "reflective": rng.random() < 0.45,
                      "weather_protection": rng.choice(["None", "Wind", "Light Rain", "Waterproof"]) if "jacket" in s else "None",
                      "fit": rng.choice(["Compression", "Slim", "Regular", "Relaxed"]),
                      "sizes": ["XS", "S", "M", "L", "XL", "XXL"]})
        feature, benefit = "fast-drying stretch fabric", "less distraction through changing effort and weather"
        tags += ["apparel", "training", "moisture wicking"]
    elif any(k in s for k in ["dumbbell", "kettlebell", "barbell", "plate", "bench", "pull-up", "resistance band"]):
        attrs.update({"weight_range_lb": rng.choice(["5-25", "10-50", "10-90", "20-120"]),
                      "adjustable": "adjustable" in s or rng.random() < 0.4,
                      "max_user_weight_lb": rng.choice([250, 300, 400, 600, 1000]),
                      "foldable": rng.random() < 0.45, "commercial_grade": rng.random() < 0.3})
        feature, benefit = "space-efficient strength progression", "more training variety without a crowded room"
        tags += ["strength", "home gym", "training"]
    elif any(k in s for k in ["yoga", "roller", "mobility", "balance", "pilates", "massage", "recovery", "cold therapy", "compression sleeve"]):
        attrs.update({"firmness": rng.choice(["Soft", "Medium", "Firm", "Variable"]), "portable": rng.random() < 0.8,
                      "material": rng.choice(["EVA", "Natural Rubber", "Cork", "High-Density Foam", "Nylon"]),
                      "length_cm": rng.randint(15, 185), "washable": rng.random() < 0.65})
        feature, benefit = "targeted mobility and recovery support", "easier warmups and calmer post-session recovery"
        tags += ["recovery", "mobility", "fitness"]
    elif any(k in s for k in ["treadmill", "exercise bike", "rowing", "elliptical", "jump rope"]):
        attrs.update({"max_user_weight_lb": rng.choice([250, 300, 350, 400]), "resistance_levels": rng.randint(8, 32),
                      "foldable": rng.random() < 0.58, "connected_training": rng.random() < 0.55,
                      "footprint_sqft": round(rng.uniform(3.0, 18.0), 1), "noise_level_db": rng.randint(38, 72)})
        feature, benefit = "quiet connected cardio", "consistent training without leaving home"
        tags += ["cardio", "home gym", "connected"]
    elif any(k in s for k in ["bottle", "hydration vest", "soft flask", "electrolyte"]):
        attrs.update({"capacity_ml": rng.choice([250, 350, 500, 650, 750, 1000, 1500, 2000]),
                      "insulated": "insulated" in s or rng.random() < 0.35, "bpa_free": True,
                      "dishwasher_safe": rng.random() < 0.75, "leakproof": rng.random() < 0.88})
        feature, benefit = "bounce-free hydration access", "easier fueling through long training days"
        tags += ["hydration", "running", "portable"]
    elif "chair" in s or "stool" in s:
        attrs.update({"material": rng.choice(["Mesh", "Fabric", "Vegan Leather", "Woven Polymer"]),
                      "lumbar_support": rng.choice(["Fixed", "Adjustable", "Dynamic"]),
                      "seat_depth_adjustable": rng.random() < 0.55, "armrests": rng.choice(["Fixed", "2D", "3D", "4D"]),
                      "max_user_weight_lb": rng.choice([250, 275, 300, 350, 400]),
                      "recommended_hours": rng.choice([4, 6, 8, 10, 12]), "recline_deg": rng.choice([110, 120, 135, 145])})
        feature, benefit = "body-aligned adjustable support", "less fatigue through long desk sessions"
        tags += ["office chair", "ergonomic", "seating"]
    elif (
        "desk" in s or "drafting table" in s
    ) and s not in ORGANIZATION_SUBCATEGORIES:
        standing = "standing" in s or rng.random() < 0.28
        attrs.update({"width_in": rng.choice([36, 42, 48, 55, 60, 72]), "depth_in": rng.choice([20, 24, 27, 30, 32]),
                      "height_adjustable": standing, "height_range_in": "24-50" if standing else "29-30",
                      "load_capacity_lb": rng.choice([110, 154, 220, 300, 355]),
                      "memory_presets": rng.choice([0, 2, 3, 4]) if standing else 0,
                      "cable_management": rng.random() < 0.65})
        feature = "quiet electric lift" if standing else "stable compact work surface"
        benefit = "smooth transitions between sitting and standing" if standing else "a focused workspace without wasted room"
        tags += ["desk", "workspace"] + (["standing desk"] if standing else [])
    elif any(k in s for k in ["lamp", "light bar", "conference light", "circadian"]):
        attrs.update({"lumens": rng.randint(300, 1800), "color_temperature_k": rng.choice([2700, 3000, 4000, 5000, 6500]),
                      "dimmable": True, "cri": rng.randint(85, 98), "auto_dimming": rng.random() < 0.42,
                      "usb_power": rng.random() < 0.55})
        feature, benefit = "glare-controlled adjustable light", "clearer work surfaces and more flattering video calls"
        tags += ["lighting", "desk", "focus"]
    elif any(k in s for k in ["webcam", "speakerphone", "usb microphone", "conference headset", "acoustic headphone"]):
        attrs.update({"video_resolution": rng.choice(["1080p", "1440p", "4K"]) if "webcam" in s else None,
                      "microphone_array": rng.randint(1, 6), "noise_reduction": rng.random() < 0.78,
                      "field_of_view_deg": rng.choice([65, 78, 90, 110]) if "webcam" in s else None,
                      "usb_c": rng.random() < 0.75, "certified_platforms": rng.sample(["Zoom", "Teams", "Meet", "Webex"], k=rng.randint(1, 4))})
        feature, benefit = "clear meeting capture", "more natural conversations across remote teams"
        tags += ["video meetings", "collaboration", "usb"]
    elif s in ORGANIZATION_SUBCATEGORIES:
        attrs.update({"material": rng.choice(["Steel", "Bamboo", "Recycled Plastic", "Felt", "Wood Composite"]),
                      "width_in": rng.randint(8, 48), "modular": rng.random() < 0.6,
                      "mounting": rng.choice(["Desktop", "Under Desk", "Wall", "Freestanding"]),
                      "tool_free": rng.random() < 0.52})
        feature, benefit = "modular clutter control", "a clearer desk with essentials within reach"
        tags += ["organization", "workspace", "storage"]
    elif any(k in s for k in ["footrest", "laptop stand", "keyboard tray", "anti-fatigue", "wrist rest", "lumbar"]):
        attrs.update({"adjustable": rng.random() < 0.72, "material": rng.choice(["Memory Foam", "Mesh", "Aluminum", "Rubber", "Wood"]),
                      "height_range_in": rng.choice(["2-5", "4-8", "6-12", "10-18"]),
                      "weight_capacity_lb": rng.choice([20, 50, 100, 250])})
        feature, benefit = "posture-supportive adjustment", "a more neutral setup across long workdays"
        tags += ["ergonomic", "desk accessory", "comfort"]
    elif any(k in s for k in ["dock", "usb hub", "surge", "ups", "wireless charger", "kvm"]):
        attrs.update({"ports": rng.randint(4, 18), "host_connection": rng.choice(["USB-C", "Thunderbolt", "USB-A", "HDMI"]),
                      "power_delivery_w": rng.choice([0, 45, 65, 90, 100, 140]), "display_count": rng.randint(1, 4),
                      "ethernet": rng.random() < 0.72, "compatibility": rng.sample(["Windows", "macOS", "Linux", "ChromeOS"], k=rng.randint(2, 4))})
        feature, benefit = "single-cable workspace connectivity", "faster transitions between mobile and desk work"
        tags += ["connectivity", "usb-c", "workspace"]
    elif any(k in s for k in ["acoustic panel", "desk divider", "door seal", "sound masking"]):
        attrs.update({"nrc_rating": round(rng.uniform(0.45, 0.95), 2), "coverage_sqft": rng.randint(8, 120),
                      "mounting": rng.choice(["Adhesive", "Clip", "Wall", "Freestanding"]),
                      "recycled_material_pct": rng.randint(0, 100)})
        feature, benefit = "focused acoustic control", "fewer speech distractions in shared spaces"
        tags += ["acoustics", "quiet office", "focus"]
    elif any(k in s for k in ["air purifier", "air quality", "humidifier", "desk fan"]):
        attrs.update({"coverage_sqft": rng.randint(80, 650), "noise_level_db": rng.randint(18, 52),
                      "filter_type": rng.choice(["HEPA", "Carbon", "Washable", "Sensor Only"]),
                      "auto_mode": rng.random() < 0.62, "app_control": rng.random() < 0.45})
        feature, benefit = "quiet desktop climate support", "cleaner, more comfortable air near the workspace"
        tags += ["air quality", "workspace", "quiet"]
    else:
        attrs.update({"portable": rng.random() < 0.65, "material": rng.choice(["Aluminum", "Polymer", "Fabric", "Steel", "Composite"]),
                      "compatibility": rng.choice(["Universal", "USB-C", "Desktop", "Mobile"]),
                      "weight_g": rng.randint(20, 2000)})
        tags += [ctx.category.lower(), ctx.subcategory.lower()]

    # Create useful contradictions for reranking and hard-negative teaching.
    if "hard_negative" in cohorts:
        if "carbon_plate" in attrs:
            attrs["carbon_plate"] = False
            feature = "reinforced polymer support shank"
            benefit = "stable everyday training"
            tags = [t for t in tags if t != "carbon plate"] + ["non-plated"]
        elif "active_noise_cancellation" in attrs:
            attrs["active_noise_cancellation"] = False
            feature = "passive noise isolation"
            benefit = "a secure seal without electronic noise cancellation"
            tags = [t for t in tags if t != "noise cancelling"] + ["passive isolation"]
        elif "height_adjustable" in attrs:
            attrs["height_adjustable"] = False
            feature = "fixed-height standing-style workspace"
            tags = [t for t in tags if t != "standing desk"] + ["fixed height"]

    return attrs, sorted(set(tags)), feature, benefit


def typo_variant(text: str, rng: random.Random) -> tuple[str, str]:
    clean = re.sub(r"\s+", " ", text.strip())
    if len(clean) < 4:
        return clean, "none"
    op = rng.choice(["transpose", "delete", "substitute", "duplicate", "remove_space", "phonetic"])
    if op == "remove_space" and " " in clean:
        idx = clean.index(" ")
        return clean[:idx] + clean[idx + 1:], op
    if op == "phonetic":
        replacements = [("ph", "f"), ("tion", "shun"), ("ck", "k"), ("qu", "kw"), ("c", "k")]
        for a, b in replacements:
            if a in clean.lower():
                i = clean.lower().index(a)
                return clean[:i] + b + clean[i + len(a):], op
        op = "substitute"
    positions = [i for i, ch in enumerate(clean) if ch.isalnum()]
    i = rng.choice(positions[1:-1] or positions)
    if op == "transpose" and i + 1 < len(clean) and clean[i + 1].isalnum():
        return clean[:i] + clean[i + 1] + clean[i] + clean[i + 2:], op
    if op == "delete":
        return clean[:i] + clean[i + 1:], op
    if op == "duplicate":
        return clean[:i] + clean[i] + clean[i:], op
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return clean[:i] + rng.choice(alphabet) + clean[i + 1:], "substitute"


def format_attributes(attrs: dict[str, Any], completeness: float, rng: random.Random) -> dict[str, Any]:
    if completeness >= 0.75:
        return attrs
    kept = {}
    for key, value in attrs.items():
        if rng.random() < completeness:
            kept[key] = value
    return kept


def make_product(ctx: ProductContext, seed: int) -> dict[str, Any]:
    rng = product_rng(seed, ctx.product_id)
    cohorts = challenge_cohorts(rng, ctx.product_id)
    # About 3.6% of rows form deterministic four-product variant groups.
    # Members share brand/model/core attributes but vary in color, price, and inventory.
    variant_group = (ctx.product_id - 1) // 4
    is_variant_group = (variant_group % 28 == 0)
    base_id = variant_group * 4 + 1 if is_variant_group else ctx.product_id
    base_rng = product_rng(seed, base_id)
    if is_variant_group and "near_duplicate" not in cohorts:
        cohorts.append("near_duplicate")
    base_ordinal = ctx.ordinal - ((ctx.ordinal - 1) % 4) if is_variant_group else ctx.ordinal
    brand = BRANDS[ctx.domain][base_ordinal % len(BRANDS[ctx.domain])]
    model = make_model(ctx.subcategory, base_ordinal, base_rng)
    tier = base_rng.choice(QUALITY_WORDS)
    color = rng.choice(COLORS)
    use_case = base_rng.choice(USE_CASES[ctx.domain])
    attrs, tags, feature, benefit = specialized_attributes(ctx, base_rng if is_variant_group else rng, cohorts)

    launch_days_ago = int(rng.triangular(0, 2600, 500))
    if "fresh_launch" in cohorts:
        launch_days_ago = rng.randint(0, 90)
    launch_date = TODAY - timedelta(days=launch_days_ago)
    metrics = common_metrics(rng, cohorts, launch_date)
    attrs = format_attributes(attrs, metrics["metadata_completeness"], rng)

    price = base_price(ctx.subcategory, rng)
    if "selective_filter" in cohorts:
        # Place products near useful workshop thresholds.
        thresholds = [49.99, 99.99, 149.99, 199.99, 249.99, 399.99, 799.99]
        price = rng.choice(thresholds) + rng.choice([-0.01, 0, 0.01])
    list_price = round(price / rng.uniform(0.72, 1.0), 2)

    inventory = max(0, int(rng.expovariate(1 / 48)))
    availability = "In Stock" if inventory > 5 else ("Low Stock" if inventory > 0 else "Out of Stock")
    if "stale_inventory" in cohorts:
        availability = rng.choice(["In Stock", "Low Stock"])
        inventory = 0
    is_refurbished = rng.random() < 0.045
    is_sponsored = "sponsored_low_relevance" in cohorts or rng.random() < 0.018

    # Semantic-only rows use a paraphrase in user-facing text; canonical attributes stay structured.
    display_feature = feature
    if "semantic_only" in cohorts:
        for canonical, variants in SYNONYMS.items():
            if canonical in " ".join(tags).lower() or canonical in feature.lower():
                display_feature = rng.choice(variants)
                break

    title = f"{brand} {model} {tier} {ctx.subcategory[:-1] if ctx.subcategory.endswith('s') else ctx.subcategory}"
    if is_variant_group:
        title += f" — {color}"
    if "lexical_only" in cohorts:
        short = f"{brand} {model}; {ctx.subcategory}; {color}; catalog specification record."
    else:
        short = f"{display_feature.capitalize()} for {use_case}, with {benefit}."

    long = (
        f"The {title} is designed for {use_case}. It combines {display_feature} with {benefit}. "
        f"Its structured specifications make it easy to compare compatibility, performance, price, availability, and intended use. "
        f"Finish: {color}. Warranty: {rng.choice([12, 18, 24, 36, 60])} months."
    )
    if "hard_negative" in cohorts:
        long += " This product intentionally resembles a nearby search intent but lacks one decisive requested capability."
    if is_refurbished:
        long += " Professionally inspected refurbished unit with cosmetic grading and renewed warranty coverage."

    aliases = [brand, model, f"{brand} {model}", ctx.subcategory]
    if ctx.subcategory == "Over-Ear Headphones": aliases += ["ANC headphones", "wireless cans", "travel headphones"]
    if "shoe" in ctx.subcategory.lower(): aliases += ["trainers", "running sneaker", "performance footwear"]
    if "chair" in ctx.subcategory.lower(): aliases += ["desk chair", "task seating", "work chair"]
    if "standing desk" in ctx.subcategory.lower(): aliases += ["sit stand desk", "height adjustable desk"]

    canonical_group_id = f"{slug(ctx.domain)[:3]}-{slug(ctx.subcategory)[:12]}-{ctx.product_id}"
    if is_variant_group:
        canonical_group_id = f"{slug(ctx.domain)[:3]}-{slug(ctx.subcategory)[:12]}-variant-{variant_group}"

    updated_days_ago = rng.randint(0, min(180, launch_days_ago))
    if "stale_inventory" in cohorts:
        oldest_possible = min(540, launch_days_ago)
        youngest_possible = min(120, oldest_possible)
        updated_days_ago = rng.randint(youngest_possible, oldest_possible)
    updated_at = datetime.combine(TODAY - timedelta(days=updated_days_ago), datetime.min.time(), tzinfo=timezone.utc)

    # Phrase intentionally duplicates important fields for FTS while embedding_text stays natural.
    attr_phrases = []
    for k, v in list(attrs.items())[:12]:
        if isinstance(v, list):
            v = " ".join(map(str, v))
        attr_phrases.append(f"{k.replace('_', ' ')} {v}")
    search_text = " | ".join([title, brand, model, ctx.category, ctx.subcategory, short, " ".join(tags), " ".join(attr_phrases)])
    embedding_text = " ".join([title, short, long, f"Use case: {use_case}.", f"Features: {', '.join(tags)}."])

    return {
        "product_id": ctx.product_id,
        "product_uid": str(uuid.uuid5(NAMESPACE, f"product:{ctx.product_id}")),
        "sku": f"{ctx.domain[:2].upper()}-{sku_segment(ctx.subcategory)}-{ctx.product_id:07d}",
        "domain": ctx.domain,
        "category": ctx.category,
        "subcategory": ctx.subcategory,
        "brand": brand,
        "model": model,
        "title": title,
        "short_description": short,
        "long_description": long,
        "price_usd": f"{price:.2f}",
        "list_price_usd": f"{max(price, list_price):.2f}",
        "currency": "USD",
        "rating": metrics["rating"],
        "review_count": metrics["review_count"],
        "availability": availability,
        "inventory_count": inventory,
        "seller_count": rng.randint(1, 12),
        "shipping_days": rng.choice([0, 1, 1, 2, 2, 3, 5, 7]),
        "warranty_months": rng.choice([12, 12, 18, 24, 24, 36, 60]),
        "return_rate": metrics["return_rate"],
        "popularity_score": metrics["popularity_score"],
        "quality_score": metrics["quality_score"],
        "freshness_score": metrics["freshness_score"],
        "metadata_completeness": metrics["metadata_completeness"],
        "launch_date": launch_date.isoformat(),
        "updated_at": updated_at.isoformat(),
        "source_system": rng.choice(SOURCE_SYSTEMS),
        "language": "en-US",
        "is_refurbished": str(is_refurbished).lower(),
        "is_sponsored": str(is_sponsored).lower(),
        "attributes_json": json.dumps(attrs, separators=(",", ":"), sort_keys=True),
        "tags_json": json.dumps(tags, separators=(",", ":")),
        "aliases_json": json.dumps(sorted(set(aliases)), separators=(",", ":")),
        "search_text": search_text,
        "embedding_text": embedding_text,
        "challenge_cohorts_json": json.dumps(cohorts, separators=(",", ":")),
        "canonical_group_id": canonical_group_id,
        "image_key": f"{ctx.domain}/{slug(ctx.subcategory)}/{ctx.product_id % 240:03d}.webp",
    }


def iter_contexts(scale: float = 1.0) -> Iterable[ProductContext]:
    product_id = 1
    for domain, categories in DISTRIBUTION.items():
        for category, subcategories in categories.items():
            for subcategory, count in subcategories.items():
                scaled = max(1, int(round(count * scale)))
                for ordinal in range(1, scaled + 1):
                    yield ProductContext(product_id, domain, category, subcategory, ordinal)
                    product_id += 1


def validate_distribution() -> None:
    for domain, expected in DOMAIN_COUNTS.items():
        actual = sum(v for cat in DISTRIBUTION[domain].values() for v in cat.values())
        if actual != expected:
            raise ValueError(f"Distribution for {domain}: expected {expected}, found {actual}")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def make_eval_assets(anchors: list[dict[str, Any]], pools: dict[str, list[dict[str, Any]]], seed: int, out_dir: Path) -> dict[str, int]:
    rng = random.Random(seed + 991)
    eval_path = out_dir / "queries.jsonl"
    demo_path = out_dir / "demo_queries.jsonl"
    judgments_path = out_dir / "judgments.csv.gz"
    typo_path = out_dir / "typo_cases.csv"
    category_keys = resolve_category_keys(
        [
            (domain, category, subcategory)
            for domain, categories in DISTRIBUTION.items()
            for category, subcategories in categories.items()
            for subcategory in subcategories
        ]
    )

    intents = []
    for anchor in anchors:
        attrs = json.loads(anchor["attributes_json"])
        interesting = []
        for key in ["active_noise_cancellation", "battery_hours", "carbon_plate", "terrain", "support", "height_adjustable", "quiet_typing", "usb_c_power_w", "lumbar_support", "noise_level_db", "weight_g"]:
            value = attrs.get(key)
            if value is not None:
                interesting.append((key, value))
        if len(interesting) > 3:
            interesting = rng.sample(interesting, 3)

        domain_label = anchor["domain"].replace("_", " ")
        semantic = anchor["short_description"].lower().rstrip(".")
        price_ceiling = math.ceil(float(anchor["price_usd"]) / 50) * 50
        base_filters: dict[str, Any] = {"domain": anchor["domain"]}
        if anchor["is_refurbished"] == "true":
            base_filters["include_refurbished"] = True
        if anchor["is_sponsored"] == "true":
            base_filters["include_sponsored"] = True
        filters: dict[str, Any] = {
            **base_filters,
            "category_key": category_keys[
                (anchor["domain"], anchor["category"], anchor["subcategory"])
            ],
            "max_price_cents": price_ceiling * 100,
        }
        if interesting:
            filters["attributes"] = dict(interesting)
        feature_suffix = (
            f" with {', '.join(key.replace('_', ' ') for key, _ in interesting[:2])}"
            if interesting
            else ""
        )
        queries = [
            (f"{anchor['brand']} {anchor['model']}", "exact_model", ["lexical"]),
            (f"Find {anchor['subcategory'].lower()} for {semantic}", "semantic_intent", ["semantic", "rerank"]),
            (f"Best {anchor['subcategory'].lower()} under ${price_ceiling}{feature_suffix}", "hybrid_filtered", ["lexical", "semantic", "filters", "rrf", "rerank"]),
        ]
        for q, intent, techniques in queries:
            intents.append({
                "query": q, "domain": anchor["domain"], "intent": intent,
                "filters": filters if intent == "hybrid_filtered" else base_filters,
                "expected_techniques": techniques, "target_product_id": int(anchor["product_id"]),
                "notes": f"Synthetic ground truth anchored to {anchor['sku']} in {domain_label}."
            })

    # Cap and balance for a practical workshop eval set.
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in intents:
        by_domain[row["domain"]].append(row)
    selected: list[dict[str, Any]] = []
    for domain in DOMAIN_COUNTS:
        rng.shuffle(by_domain[domain])
        selected.extend(by_domain[domain][:240])
    rng.shuffle(selected)

    with eval_path.open("w", encoding="utf-8") as f:
        for i, row in enumerate(selected, 1):
            row = {"query_id": f"Q-{i:04d}", **row}
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    # 45 polished instructor/demo queries that cover all techniques.
    demo_templates = [
        ("consumer_electronics", "Find wireless noise-cancelling over-ear headphones under $200 with at least 40 hours of battery life", ["fts", "vector", "filters", "rrf", "rerank"]),
        ("consumer_electronics", "noice canceling hedphones for long fligts under 200", ["pg_trgm", "vector", "filters", "rrf"]),
        ("consumer_electronics", "A compact USB-C dock that can drive two monitors and charge my laptop", ["semantic", "jsonb filters", "rerank"]),
        ("consumer_electronics", "Which Wi-Fi system is best for a three-floor home with many devices?", ["semantic", "metadata", "rerank"]),
        ("consumer_electronics", "quiet mechancial keybaord for zoom calls", ["pg_trgm", "fts", "semantic"]),
        ("running_fitness", "Carbon-plated marathon shoes under $220 that are light enough for race day", ["fts", "vector", "filters", "rrf", "rerank"]),
        ("running_fitness", "marthon shoe with propulsive plate for tired late-race legs", ["pg_trgm", "semantic", "rerank"]),
        ("running_fitness", "Trail shoes for wet technical terrain with a secure fit", ["semantic", "filters", "rerank"]),
        ("running_fitness", "A quiet folding treadmill for a small apartment", ["semantic", "metadata", "filters"]),
        ("running_fitness", "Recovery tools for sore calves after long runs that fit in a carry-on", ["semantic", "rerank"]),
        ("home_office", "Ergonomic mesh chair with adjustable lumbar support under $500", ["fts", "vector", "filters", "rrf"]),
        ("home_office", "ergonmic ofice chair for 10 hour days", ["pg_trgm", "semantic", "rerank"]),
        ("home_office", "A quiet keyboard and vertical mouse for shared-office work", ["semantic", "metadata", "fusion"]),
        ("home_office", "Electric standing desk for a narrow apartment with cable management", ["semantic", "filters", "rerank"]),
        ("home_office", "Reduce speech distraction in a shared room without wearing headphones", ["semantic", "hard negatives", "rerank"]),
    ]
    demo_rows = []
    for repeat in range(3):
        for domain, query, techniques in demo_templates:
            demo_rows.append({"query_id": f"D-{len(demo_rows)+1:03d}", "domain": domain, "query": query,
                              "expected_techniques": techniques, "variant": repeat + 1})
    with demo_path.open("w", encoding="utf-8") as f:
        for row in demo_rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    # Relevance judgments use the target plus same-subcategory products as graded alternatives.
    with gzip.open(judgments_path, "wt", encoding="utf-8", newline="") as gz:
        writer = csv.DictWriter(gz, fieldnames=["query_id", "product_id", "relevance_grade", "reason"])
        writer.writeheader()
        for i, row in enumerate(selected, 1):
            qid = f"Q-{i:04d}"
            target_id = int(row["target_product_id"])
            writer.writerow({"query_id": qid, "product_id": target_id, "relevance_grade": 3, "reason": "anchor product"})
            # Locate the anchor's subcategory from the pools.
            anchor = next((a for a in anchors if int(a["product_id"]) == target_id), None)
            if not anchor:
                continue
            candidates = [p for p in pools[anchor["subcategory"]] if int(p["product_id"]) != target_id]
            rng.shuffle(candidates)
            for candidate in candidates[:3]:
                writer.writerow({"query_id": qid, "product_id": candidate["product_id"], "relevance_grade": 2, "reason": "same subcategory alternative"})
            for candidate in candidates[3:5]:
                writer.writerow({"query_id": qid, "product_id": candidate["product_id"], "relevance_grade": 1, "reason": "partially relevant alternative"})

    typo_rows = []
    typo_candidates = [a for a in anchors if "typo_target" in json.loads(a["challenge_cohorts_json"])] or anchors
    while len(typo_rows) < 5_000:
        anchor = rng.choice(typo_candidates)
        base = rng.choice([anchor["brand"], anchor["model"], f"{anchor['brand']} {anchor['model']}", anchor["subcategory"]])
        typo, typo_type = typo_variant(base, rng)
        if typo == base:
            continue
        typo_rows.append({"case_id": f"T-{len(typo_rows)+1:05d}", "misspelled_query": typo,
                          "corrected_text": base, "target_product_id": anchor["product_id"],
                          "domain": anchor["domain"], "typo_type": typo_type})
    with typo_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(typo_rows[0]))
        writer.writeheader()
        writer.writerows(typo_rows)

    return {"eval_queries": len(selected), "demo_queries": len(demo_rows), "typo_cases": len(typo_rows)}


def generate(scale: float, seed: int, out_root: Path) -> dict[str, Any]:
    validate_distribution()
    data_full = out_root / "data" / "full"
    data_sample = out_root / "data" / "sample"
    data_eval = out_root / "data" / "evals"
    data_dict = out_root / "data" / "dictionaries"
    ui_data = out_root / "ui" / "data"
    for p in [data_full, data_sample, data_eval, data_dict, ui_data]:
        p.mkdir(parents=True, exist_ok=True)

    full_paths = {
        domain: data_full / filename
        for domain, filename in FULL_DATASET_FILES.items()
    }
    sample_path = data_sample / "products_5000.csv.gz"
    sample_json_path = data_sample / "products_120.json"
    ui_json_path = ui_data / "products.json"

    domain_sample_targets = {"consumer_electronics": 2_100, "running_fitness": 1_600, "home_office": 1_300}
    domain_sample_counts = defaultdict(int)
    domain_counts = defaultdict(int)
    category_counts = defaultdict(int)
    subcategory_counts = defaultdict(int)
    cohort_counts = defaultdict(int)
    availability_counts = defaultdict(int)
    anchors: list[dict[str, Any]] = []
    pools: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ui_products: list[dict[str, Any]] = []
    sample_products_json: list[dict[str, Any]] = []

    total_expected = int(round(sum(DOMAIN_COUNTS.values()) * scale))
    destinations = ", ".join(str(path) for path in full_paths.values())
    print(f"Generating {total_expected:,} products -> {destinations}", flush=True)
    with ExitStack() as stack:
        full_streams = {
            domain: stack.enter_context(
                gzip.open(path, "wt", encoding="utf-8", newline="", compresslevel=1)
            )
            for domain, path in full_paths.items()
        }
        sample_gz = stack.enter_context(
            gzip.open(sample_path, "wt", encoding="utf-8", newline="", compresslevel=1)
        )
        full_writers = {
            domain: csv.DictWriter(stream, fieldnames=FIELDS)
            for domain, stream in full_streams.items()
        }
        sample_writer = csv.DictWriter(sample_gz, fieldnames=FIELDS)
        for writer in full_writers.values():
            writer.writeheader()
        sample_writer.writeheader()

        for i, ctx in enumerate(iter_contexts(scale), 1):
            row = make_product(ctx, seed)
            full_writers[row["domain"]].writerow(row)
            domain_counts[row["domain"]] += 1
            category_counts[f"{row['domain']}::{row['category']}"] += 1
            subcategory_counts[f"{row['domain']}::{row['category']}::{row['subcategory']}"] += 1
            availability_counts[row["availability"]] += 1
            for c in json.loads(row["challenge_cohorts_json"]):
                cohort_counts[c] += 1

            if domain_sample_counts[row["domain"]] < max(1, int(domain_sample_targets[row["domain"]] * scale)):
                sample_writer.writerow(row)
                domain_sample_counts[row["domain"]] += 1
            if len(sample_products_json) < 120 and i % max(1, total_expected // 120) == 0:
                sample_products_json.append(row)
            if len(pools[row["subcategory"]]) < 30:
                pools[row["subcategory"]].append(row)
            # ~450 balanced anchors at full scale, with extra challenge rows.
            domain_target_mod = {"consumer_electronics": 467, "running_fitness": 356, "home_office": 289}[row["domain"]]
            if i % domain_target_mod == 0 or (len(anchors) < 900 and "typo_target" in json.loads(row["challenge_cohorts_json"]) and i % 97 == 0):
                anchors.append(row)
            if len(ui_products) < 36 and (
                (row["domain"] == "consumer_electronics" and row["subcategory"] in ["Over-Ear Headphones", "Mechanical Keyboards", "Portable Monitors"]) or
                (row["domain"] == "running_fitness" and row["subcategory"] in ["Carbon Racing Shoes", "Trail Running Shoes", "GPS Running Watches"]) or
                (row["domain"] == "home_office" and row["subcategory"] in ["Ergonomic Office Chairs", "Electric Standing Desks", "Quiet Keyboards"])
            ):
                if float(row["rating"]) >= 4.0 and row["availability"] != "Out of Stock":
                    ui_products.append(row)

            if i % 50_000 == 0:
                print(f"  {i:,}/{total_expected:,}", flush=True)

    # Convert compact JSON samples from CSV-form strings into typed objects.
    def compact(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "product_id": int(row["product_id"]), "sku": row["sku"], "domain": row["domain"],
            "category": row["category"], "subcategory": row["subcategory"], "brand": row["brand"],
            "model": row["model"], "title": row["title"], "short_description": row["short_description"],
            "price_usd": float(row["price_usd"]), "rating": float(row["rating"]),
            "review_count": int(row["review_count"]), "availability": row["availability"],
            "attributes": json.loads(row["attributes_json"]), "tags": json.loads(row["tags_json"]),
            "cohorts": json.loads(row["challenge_cohorts_json"]), "image_key": row["image_key"],
            "popularity_score": float(row["popularity_score"]), "quality_score": float(row["quality_score"]),
        }
    write_json(sample_json_path, [compact(r) for r in sample_products_json])
    write_json(ui_json_path, [compact(r) for r in ui_products[:30]])

    eval_counts = make_eval_assets(anchors, pools, seed, data_eval)

    synonyms = {k: v for k, v in SYNONYMS.items()}
    write_json(data_dict / "synonyms.json", synonyms)
    write_json(data_dict / "brands.json", BRANDS)
    write_json(data_dict / "taxonomy.json", DISTRIBUTION)

    manifest = {
        "dataset_name": "Mosaic Synthetic Product Catalog",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "scale": scale,
        "total_products": sum(domain_counts.values()),
        "domain_counts": dict(domain_counts),
        "category_counts": dict(sorted(category_counts.items())),
        "subcategory_counts": dict(sorted(subcategory_counts.items())),
        "challenge_cohort_counts": dict(sorted(cohort_counts.items())),
        "availability_counts": dict(availability_counts),
        "evaluation": eval_counts,
        "full_datasets": [
            str(full_paths[domain].relative_to(out_root))
            for domain in DOMAIN_COUNTS
        ],
        "sample_dataset": str(sample_path.relative_to(out_root)),
        "embeddings_included": False,
        "embedding_note": "Use scripts/embed_catalog.py; embeddings are provider- and dimension-dependent.",
        "license": "Synthetic data generated for demonstration and workshop use; no real products or reviews are represented.",
    }
    write_json(data_full / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=1.0, help="1.0 = 500,000 products")
    parser.add_argument("--seed", type=int, default=20260806)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    manifest = generate(args.scale, args.seed, args.output_root)
    print(json.dumps({"total_products": manifest["total_products"], "files": manifest["full_datasets"]}, indent=2))


if __name__ == "__main__":
    main()
