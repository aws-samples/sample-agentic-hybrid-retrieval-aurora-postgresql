#!/usr/bin/env python3
"""Fail the build if a Mosaic Labs rule sets a font or size outside the shared scale.

Before this gate the three Labs views carried 161 `font-size` declarations across
38 distinct values — 27 px literals from 8px to 42px, one `0.94em`, and 10
separate `clamp()` expressions. 78 of the 161 were 11px or smaller, which is below
a usable projector floor, and each view had invented its own steps, so `.hnsw-*`
rendered smaller than `.labs-*` for the same class of label.

Routing every declaration through `--labs-*` makes the scale shared structurally: a
fourth Labs view cannot drift because there is nothing left to drift from. The
selector families are enumerated here rather than in prose so the check and its
documentation cannot disagree.

It scans both stylesheets. Reading only `surfaces.css` left 42 Labs declarations
unchecked in `styles.css` — 10px, 10.5px, 11px, 16px, 19px and 27px steps on the
outcome banner, the query bar and the diagnostics strip, which render directly
below a masthead on the shared scale. Two type systems in one viewport is exactly
what this gate exists to prevent, and the half that was drifting was the half
nobody was looking at. `retrieval-` is in the family list for the same reason: the
Retrieval Observatory's panels are named for what they show, not for the surface
they sit on.

Font families go through tokens too. `--display` and `--sans` were tokens while the
monospace stack was 45 copies of a literal, so there was no single place to change
it and nothing for a gate to require.

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

STYLESHEETS = (
    REPO / "ui" / "src" / "styles.css",
    REPO / "ui" / "src" / "surfaces.css",
)

# A rule belongs to Mosaic Labs when its selector names one of these families.
LABS_SELECTOR = re.compile(
    r"\.(?:labs-|lab-|hnsw-|mosaic-studio-|mosaic-labs-|retrieval-)"
)

# The only admitted values. Any other value — px, em, rem, a clamp() expression or
# a custom property from outside the Labs scale — is a second scale.
ADMITTED = re.compile(r"^var\(\s*--labs-[a-z0-9-]+\s*\)$")

RULE = re.compile(r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}")
FONT_SIZE = re.compile(r"font-size:\s*(?P<value>[^;]+);")
FONT_FAMILY = re.compile(r"font-family:\s*(?P<value>[^;]+);")

# `inherit` is not a second family, it is a refusal to name one.
ADMITTED_FAMILY = re.compile(r"^(?:var\(\s*--(?:display|sans|mono)\s*\)|inherit)$")

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
    """One Labs declaration that bypasses the shared type system."""

    sheet: str
    selector: str
    property_name: str
    value: str
    line: int

    @property
    def remedy(self) -> str:
        if self.property_name == "font-size":
            return f"use one of {', '.join(f'var({token})' for token in TOKENS)}"
        return "use var(--display), var(--sans) or var(--mono)"


def scan_labs_type(css: str, sheet: str) -> list[Violation]:
    """Return every Labs font declaration not routed through a shared token.

    Args:
        css: Full stylesheet text.
        sheet: File name, carried into the violation so a report over two sheets
            can say which one to open.

    Returns:
        Violations in source order, each carrying the selector, the property, the
        offending value, and the 1-indexed line the value appears on.
    """
    violations: list[Violation] = []
    for rule in RULE.finditer(css):
        selector = rule.group("selector").strip()
        if not LABS_SELECTOR.search(selector):
            continue
        for pattern, name, admitted in (
            (FONT_SIZE, "font-size", ADMITTED),
            (FONT_FAMILY, "font-family", ADMITTED_FAMILY),
        ):
            for declaration in pattern.finditer(rule.group("body")):
                value = declaration.group("value").strip()
                if admitted.match(value):
                    continue
                offset = rule.start("body") + declaration.start("value")
                violations.append(
                    Violation(
                        sheet, selector, name, value, css.count("\n", 0, offset) + 1
                    )
                )
    return violations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--explain", action="store_true")
    arguments = parser.parse_args()

    violations: list[Violation] = []
    for stylesheet in STYLESHEETS:
        violations.extend(
            scan_labs_type(stylesheet.read_text(encoding="utf-8"), stylesheet.name)
        )

    if arguments.explain:
        for stylesheet in STYLESHEETS:
            print(f"scanned {stylesheet.relative_to(REPO)}")
        print(f"families {LABS_SELECTOR.pattern}")
        print(f"tokens {', '.join(TOKENS)}")
        print("families admitted --display, --sans, --mono")

    for violation in violations:
        print(
            f"FAIL labs-type-scale {violation.sheet}:{violation.line} "
            f"{violation.selector}: "
            + explain(f"{violation.property_name} {violation.value}", violation.remedy)
        )
    if violations:
        raise SystemExit(f"{len(violations)} Labs type declarations off-scale")
    print("labs-type-scale: every Labs font size and family uses a shared token")


if __name__ == "__main__":
    main()
