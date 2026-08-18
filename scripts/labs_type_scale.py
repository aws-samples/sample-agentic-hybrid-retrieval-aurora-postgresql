#!/usr/bin/env python3
"""Fail the build if a Mosaic Labs rule sets a font size outside the shared scale.

Before this gate the three Labs views carried 161 `font-size` declarations across
38 distinct values — 27 px literals from 8px to 42px, one `0.94em`, and 10
separate `clamp()` expressions. 78 of the 161 were 11px or smaller, which is below
a usable projector floor, and each view had invented its own steps, so `.hnsw-*`
rendered smaller than `.labs-*` for the same class of label.

Routing every declaration through `--labs-*` makes the scale shared structurally: a
fourth Labs view cannot drift because there is nothing left to drift from. The
selector families are enumerated here rather than in prose so the check and its
documentation cannot disagree.

Usage
-----
    uv run python scripts/labs_type_scale.py
    uv run python scripts/labs_type_scale.py --explain   # list what was scanned
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import explain

SURFACES_CSS = REPO / "ui" / "src" / "surfaces.css"

# A rule belongs to Mosaic Labs when its selector names one of these families.
LABS_SELECTOR = re.compile(r"\.(?:labs-|lab-|hnsw-|mosaic-studio-|mosaic-labs-)")

# The only admitted values. Any other value — px, em, rem, a clamp() expression or
# a custom property from outside the Labs scale — is a second scale.
ADMITTED = re.compile(r"^var\(\s*--labs-[a-z0-9-]+\s*\)$")

RULE = re.compile(r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}")
FONT_SIZE = re.compile(r"font-size:\s*(?P<value>[^;]+);")

TOKENS = (
    "--labs-display",
    "--labs-h2",
    "--labs-h3",
    "--labs-lead",
    "--labs-body",
    "--labs-detail",
    "--labs-micro",
    "--labs-mono",
)


@dataclass(frozen=True)
class Violation:
    """One Labs font-size declaration that bypasses the shared scale."""

    selector: str
    value: str
    line: int


def scan_labs_font_sizes(css: str) -> list[Violation]:
    """Return every Labs font-size declaration not using a `--labs-*` token.

    Args:
        css: Full stylesheet text.

    Returns:
        Violations in source order, each carrying the selector, the offending
        value, and the 1-indexed line the value appears on.
    """
    violations: list[Violation] = []
    for rule in RULE.finditer(css):
        selector = rule.group("selector").strip()
        if not LABS_SELECTOR.search(selector):
            continue
        for declaration in FONT_SIZE.finditer(rule.group("body")):
            value = declaration.group("value").strip()
            if ADMITTED.match(value):
                continue
            offset = rule.start("body") + declaration.start("value")
            violations.append(
                Violation(selector, value, css.count("\n", 0, offset) + 1)
            )
    return violations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--explain", action="store_true")
    arguments = parser.parse_args()

    css = SURFACES_CSS.read_text(encoding="utf-8")
    violations = scan_labs_font_sizes(css)

    if arguments.explain:
        print(f"scanned {SURFACES_CSS.relative_to(REPO)}")
        print(f"families {LABS_SELECTOR.pattern}")
        print(f"tokens {', '.join(TOKENS)}")

    for violation in violations:
        print(
            f"FAIL labs-type-scale {SURFACES_CSS.name}:{violation.line} "
            f"{violation.selector}: "
            + explain(
                f"font-size {violation.value}",
                f"use one of {', '.join(f'var({token})' for token in TOKENS)}",
            )
        )
    if violations:
        raise SystemExit(f"{len(violations)} Labs font-size declarations off-scale")
    print("labs-type-scale: every Labs font-size uses the shared scale")


if __name__ == "__main__":
    main()
