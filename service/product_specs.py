"""Typed specifications read from a listing's own text, each carrying the verbatim span it came from.

The source record is hash-pinned, so a spec is derived on read rather than
stored: re-running these rules over the same record always gives the same
values. Every value names its field (`details.<key>`, `title`, `features[i]`,
`description[i]`) and quotes the exact text, so a reader or a test can check it
against the listing. A value the listing does not state stays unknown; the rules
favour a missing value over a guessed one, because Lab 3 decisions such as
"at least 100 W over USB-C" must not rest on a misread number.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

from service.models import ProductSpec

# A period between digits (23.8 inches, 3.5 mm) is a decimal point, not a sentence end.
_SENTENCE = re.compile(r"(?:[^.;!?\n]|(?<=\d)\.(?=\d))+[.;!?]?")
_USB_C = re.compile(
    r"\b(?:usb[\s-]?c|type[\s-]?c|thunderbolt\s?[345])\b", re.IGNORECASE
)
_CHARGING = re.compile(
    r"\b(?:charg\w*|power delivery|pd|powers? (?:your|the|a) (?:laptop|notebook|macbook|device))\b",
    re.IGNORECASE,
)
_WATTS = re.compile(r"(?<![\d.])(\d{2,3})\s?(?:w|watts?)\b", re.IGNORECASE)
_RESOLUTION = re.compile(
    r"(?<![\d.])(\d{3,4})\s?[x×]\s?(\d{3,4})(?![\d.])", re.IGNORECASE
)
_INCHES_TEXT = re.compile(
    r"(?<![\d.])(\d{2}(?:\.\d{1,2})?)\s?(?:\"|”|''|-?\s?inch(?:es)?\b|-in\b)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![\d.])(\d{2}(?:\.\d{1,2})?)(?![\d.])")
# "65W laptop charger", "2 x 3W speakers": a wattage that names another device.
_DEVICE_WATTS = re.compile(
    r"\s+(?:\w+\s+){0,2}?(?:adapters?|chargers?|power supply|bricks?|speakers?|amplifiers?)\b",
    re.IGNORECASE,
)
_HERTZ = re.compile(r"(?<![\d.])(\d{2,3})\s?hz\b", re.IGNORECASE)
_POUNDS = re.compile(r"(?<![\d.])(\d{3})\s?(?:lbs?|pounds)\b", re.IGNORECASE)
_ACTIVE_NC = re.compile(
    r"\b(?:(?:active|hybrid|adaptive)\s+noise[\s-]?cancel\w*|anc)\b", re.IGNORECASE
)
_ANY_NC = re.compile(r"\bnoise[\s_-]?cancel\w*\b", re.IGNORECASE)
# Headsets advertise noise-cancelling microphones; that is not listening ANC.
_VOICE = re.compile(
    r"\b(?:mic\w*|call\w*|voice|enc|cvc|boom|talk\w*|speech)\b", re.IGNORECASE
)
_MICROPHONE = re.compile(r"\b(?:microphones?|mics?)\b", re.IGNORECASE)
# A feature a buyer must add is not a feature of the listed product.
_NOT_INCLUDED = re.compile(
    r"\b(?:sold|purchased?|bought)\s+separately|not included|optional\b", re.IGNORECASE
)
_NO_MICROPHONE = re.compile(
    r"\b(?:no|without|not include\w*)\s+(?:a\s+|built[\s-]in\s+)?(?:microphones?|mics?)\b",
    re.IGNORECASE,
)


def _text_fields(original: dict[str, Any]) -> Iterator[tuple[str, str]]:
    yield "title", original.get("title") or ""
    for name in ("features", "description"):
        for index, value in enumerate(original.get(name) or []):
            if isinstance(value, str):
                yield f"{name}[{index}]", value


def _sentences(original: dict[str, Any]) -> Iterator[tuple[str, str]]:
    for field, text in _text_fields(original):
        for sentence in _SENTENCE.findall(text):
            if sentence.strip():
                yield field, sentence.strip()


def _details(original: dict[str, Any]) -> dict[str, str]:
    return {
        key: value
        for key, value in (original.get("details") or {}).items()
        if isinstance(value, str)
    }


def _spec(value: Any, source: str, quote: str) -> ProductSpec:
    return ProductSpec(value=value, source=source, quote=quote)


def _from_details(
    original: dict[str, Any], keys: tuple[str, ...], parse: Callable[[str], Any]
) -> ProductSpec | None:
    details = _details(original)
    for key in keys:
        if key in details:
            value = parse(details[key])
            if value is not None:
                return _spec(value, f"details.{key}", details[key])
    return None


def _from_sentences(
    original: dict[str, Any], parse: Callable[[str], Any]
) -> ProductSpec | None:
    for field, sentence in _sentences(original):
        value = parse(sentence)
        if value is not None:
            return _spec(value, field, sentence)
    return None


def _resolution(text: str) -> str | None:
    match = _RESOLUTION.search(text)
    if match is None:
        return None
    width, height = sorted((int(match.group(1)), int(match.group(2))), reverse=True)
    return (
        f"{width}x{height}" if 640 <= width <= 7680 and 360 <= height <= 4320 else None
    )


_OTHER_LENGTH_UNIT = re.compile(
    r"\b(?:cm|centimet\w*|mm|millimet\w*|feet|foot|ft)\b", re.IGNORECASE
)
# Nominal and viewable diagonals of one screen differ by up to about an inch
# (21" beside 21.3"); a wider gap means the record contradicts itself.
_SIZE_TOLERANCE_IN = 1.0


def _size(pattern: re.Pattern[str]) -> Callable[[str], float | None]:
    def parse(text: str) -> float | None:
        match = pattern.search(text)
        return (
            float(match.group(1))
            if match and 10 <= float(match.group(1)) <= 65
            else None
        )

    return parse


def _detail_size(text: str) -> float | None:
    """A details value in inches; a value in another length unit is not read as inches."""
    return None if _OTHER_LENGTH_UNIT.search(text) else _size(_NUMBER)(text)


def _refresh(text: str) -> int | None:
    match = _HERTZ.search(text)
    return int(match.group(1)) if match and 24 <= int(match.group(1)) <= 540 else None


def _charging_watts(text: str) -> list[int]:
    """Wattages in a plausible USB-C range that do not name a separate device (adapter, speaker)."""
    return [
        int(match.group(1))
        for match in _WATTS.finditer(text)
        if 15 <= int(match.group(1)) <= 240
        and not _DEVICE_WATTS.match(text, match.end())
    ]


def _usb_c_power(sentence: str) -> int | None:
    """Wattage stated with USB-C (or Thunderbolt) and charging, clause first, then one per sentence."""
    for clause in re.split(r",|\band\b", sentence):
        if _USB_C.search(clause) and _CHARGING.search(clause):
            watts = _charging_watts(clause)
            if watts:
                return max(watts)
    if _USB_C.search(sentence) and _CHARGING.search(sentence):
        watts = _charging_watts(sentence)
        return watts[0] if len(set(watts)) == 1 else None
    return None


def _screen_size(original: dict[str, Any]) -> ProductSpec | None:
    """The diagonal in inches, unless the details field and the title disagree.

    Details carry centimetres labelled as inches ("55.8 Inches" on a 22" AOC)
    and plain errors ("14 Inches" on a 27" Dell). Neither statement can be
    preferred without guessing, so a contradiction leaves the size unknown.
    """
    detail = _from_details(
        original,
        ("Screen Size", "Standing screen display size", "Display Size"),
        _detail_size,
    )
    if detail is None:
        return _from_sentences(original, _size(_INCHES_TEXT))
    parse = _size(_INCHES_TEXT)
    title_sizes = [
        size
        for sentence in _SENTENCE.findall(original.get("title") or "")
        if (size := parse(sentence)) is not None
    ]
    if title_sizes and all(
        abs(size - detail.value) > _SIZE_TOLERANCE_IN for size in title_sizes
    ):
        return None
    return detail


def monitor_specs(original: dict[str, Any]) -> dict[str, ProductSpec]:
    found = {
        "size_in": _screen_size(original),
        "resolution": _from_details(
            original,
            (
                "Display Resolution Maximum",
                "Screen Resolution",
                "Max Screen Resolution",
                "Resolution",
            ),
            _resolution,
        )
        or _from_sentences(original, _resolution),
        "refresh_hz": _from_details(original, ("Refresh Rate",), _refresh)
        or _from_sentences(
            original,
            lambda s: _refresh(s) if re.search(r"refresh", s, re.IGNORECASE) else None,
        ),
        "usb_c_power_w": _from_sentences(original, _usb_c_power),
    }
    return {key: spec for key, spec in found.items() if spec is not None}


def _listening_anc(clause: str, tag: bool) -> bool | None:
    """Listening noise cancellation; passive isolation and headset-microphone claims do not count.

    A bare "noise-canceling" feature tag is used for microphones as often as for
    listening, so a tag must say active (or hybrid/adaptive); a listing sentence
    may say plain "noise cancelling" when no voice or microphone word shares it.
    """
    if re.search(r"\bpassive\b", clause, re.IGNORECASE):
        return None
    if _ACTIVE_NC.search(clause):
        return True
    if not tag and _ANY_NC.search(clause) and not _VOICE.search(clause):
        return True
    return None


def _noise_control(value: str) -> bool | None:
    if re.search(r"active|hybrid|adaptive", value, re.IGNORECASE):
        return True
    if re.fullmatch(
        r"\s*(?:none|sound isolation|passive noise cancell?ation)\s*",
        value,
        re.IGNORECASE,
    ):
        return False
    return None


def _clauses(original: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    """(field, clause, quote): comma clauses of sentences and of special-feature lists."""
    details = _details(original)
    for key in ("Special Feature", "Special features", "Special Features"):
        if key in details:
            for clause in details[key].split(","):
                yield f"details.{key}", clause, details[key]
    for field, sentence in _sentences(original):
        for clause in sentence.split(","):
            yield field, clause, sentence


def headphone_specs(original: dict[str, Any]) -> dict[str, ProductSpec]:
    found: dict[str, ProductSpec | None] = {
        "anc": _from_details(original, ("Noise Control",), _noise_control),
        "microphone": None,
        "wireless": _from_details(
            original,
            ("Connectivity Technology", "Connectivity technologies"),
            lambda v: (
                True
                if re.search(r"wireless|bluetooth", v, re.IGNORECASE)
                else False
                if re.search(r"wired|3\.5|usb|lightning|aux", v, re.IGNORECASE)
                else None
            ),
        ),
        "form_factor": _from_details(
            original,
            ("Form Factor",),
            lambda v: (
                f"{m.group(1).lower()}-ear"
                if (m := re.search(r"\b(over|on|in)[\s-]?ear", v, re.IGNORECASE))
                else None
            ),
        ),
    }
    for field, clause, quote in _clauses(original):
        if found["anc"] is None and _listening_anc(
            clause, field.startswith("details.")
        ):
            found["anc"] = _spec(True, field, quote)
        if (
            found["microphone"] is None
            and _MICROPHONE.search(clause)
            and not _NO_MICROPHONE.search(quote)
        ):
            found["microphone"] = _spec(True, field, quote)
    return {key: spec for key, spec in found.items() if spec is not None}


def _armrests(text: str) -> str | None:
    if _NOT_INCLUDED.search(text):
        return None
    if match := re.search(r"\b([2-8])D\s*(?:adjustable\s*)?arm", text, re.IGNORECASE):
        return f"{match.group(1)}D adjustable"
    if re.search(
        r"adjustable\s+arm|arm(?:rest)?s?\s+(?:are\s+)?(?:height[\s-])?adjustable",
        text,
        re.IGNORECASE,
    ):
        return "adjustable"
    if re.search(r"flip[\s-]?(?:up|back)\s+arm", text, re.IGNORECASE):
        return "flip-up"
    return None


def _max_weight(original: dict[str, Any]) -> ProductSpec | None:
    for key, value in _details(original).items():
        if key.startswith("Maximum Weight Recommendation"):
            match = _POUNDS.search(value) or _POUNDS.search(key)
            if match and 150 <= int(match.group(1)) <= 700:
                return _spec(int(match.group(1)), f"details.{key}", value)
    return _from_sentences(
        original,
        lambda s: (
            int(m.group(1))
            if (
                m := re.search(
                    r"(?:capacity|support\w*|holds?|up to|max\w*)\D{0,25}?(\d{3})\s?(?:lbs?|pounds)\b",
                    s,
                    re.IGNORECASE,
                )
            )
            and 150 <= int(m.group(1)) <= 700
            else None
        ),
    )


def chair_specs(original: dict[str, Any]) -> dict[str, ProductSpec]:
    arm_style = _from_details(
        original,
        ("Arm Style",),
        lambda v: (
            "none"
            if re.search(r"armless", v, re.IGNORECASE)
            else "fixed"
            if re.search(r"^\s*fixed\s*$", v, re.IGNORECASE)
            else "adjustable"
            if re.search(r"adjustable", v, re.IGNORECASE)
            else None
        ),
    )
    found = {
        "lumbar_support": _from_sentences(
            original,
            lambda s: (
                "adjustable"
                if re.search(
                    r"adjustable lumbar|lumbar[^.,]{0,30}\badjust", s, re.IGNORECASE
                )
                and not _NOT_INCLUDED.search(s)
                else None
            ),
        )
        or _from_details(
            original,
            ("Special Feature",),
            lambda v: (
                "adjustable"
                if re.search(r"adjustable lumbar", v, re.IGNORECASE)
                else None
            ),
        )
        or _from_sentences(
            original,
            lambda s: (
                "yes" if re.search(r"\blumbar support\b", s, re.IGNORECASE) else None
            ),
        ),
        "armrests": _from_sentences(original, _armrests) or arm_style,
        "headrest": _from_sentences(
            original,
            lambda s: (
                True
                if re.search(r"\bhead\s?rest\b", s, re.IGNORECASE)
                and not re.search(r"\b(?:no|without)\s+head\s?rest", s, re.IGNORECASE)
                and not _NOT_INCLUDED.search(s)
                else None
            ),
        ),
        "max_weight_lb": _max_weight(original),
    }
    return {key: spec for key, spec in found.items() if spec is not None}


_EXTRACTORS: dict[str, Callable[[dict[str, Any]], dict[str, ProductSpec]]] = {
    "monitor": monitor_specs,
    "headphones": headphone_specs,
    "chair": chair_specs,
}


def listing_specs(
    category_key: str, original: dict[str, Any]
) -> dict[str, ProductSpec]:
    """Typed specs the listing states for a lab category; empty for other categories."""
    extractor = _EXTRACTORS.get(category_key)
    return extractor(original) if extractor else {}


def quote_is_verbatim(original: dict[str, Any], spec: ProductSpec) -> bool:
    """True when the spec's quote is exactly present in the field it names."""
    if spec.source.startswith("details."):
        return (
            _details(original).get(spec.source.removeprefix("details.")) == spec.quote
        )
    fields = dict(_text_fields(original))
    return spec.source in fields and spec.quote in fields[spec.source]
