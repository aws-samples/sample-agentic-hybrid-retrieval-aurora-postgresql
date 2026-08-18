"""The Labs type scale must be shared, and the gate must prove it.

House bar: a green check is not evidence on its own. The synthetic fixtures below
are the permanent falsifiers — each one is a violation the gate must catch, kept
as a test so the gate is re-proven on every run rather than once at birth.
"""

from __future__ import annotations

from scripts.labs_type_scale import (
    SURFACES_CSS,
    scan_labs_font_sizes,
)


def test_gate_catches_a_px_literal_in_a_labs_rule():
    css = ".hnsw-live > footer small {\n  font-size: 9.5px;\n}\n"

    violations = scan_labs_font_sizes(css)

    assert [violation.value for violation in violations] == ["9.5px"]
    assert violations[0].selector == ".hnsw-live > footer small"
    assert violations[0].line == 2


def test_gate_catches_em_and_clamp_literals_too():
    css = (
        ".labs-intro-copy h1 {\n  font-size: clamp(48px, 4.6vw, 66px);\n}\n"
        ".lab-card p {\n  font-size: 0.94em;\n}\n"
    )

    values = [violation.value for violation in scan_labs_font_sizes(css)]

    assert values == ["clamp(48px, 4.6vw, 66px)", "0.94em"]


def test_gate_admits_a_labs_token():
    css = ".mosaic-studio-briefs .eyebrow {\n  font-size: var(--labs-micro);\n}\n"

    assert scan_labs_font_sizes(css) == []


def test_gate_ignores_rules_outside_the_labs_families():
    css = ".product-card strong {\n  font-size: 13px;\n}\n"

    assert scan_labs_font_sizes(css) == []


def test_gate_rejects_a_non_labs_variable_inside_a_labs_rule():
    css = ".hnsw-graph header {\n  font-size: var(--detail);\n}\n"

    assert [v.value for v in scan_labs_font_sizes(css)] == ["var(--detail)"]


def test_gate_reports_the_line_of_a_later_declaration():
    css = (
        ".product-card {\n  color: red;\n}\n\n"
        ".labs-intro-deck {\n  margin: 0;\n  font-size: 17px;\n}\n"
    )

    violations = scan_labs_font_sizes(css)

    assert [(v.value, v.line) for v in violations] == [("17px", 7)]


def test_every_labs_font_size_uses_the_shared_scale():
    violations = scan_labs_font_sizes(SURFACES_CSS.read_text(encoding="utf-8"))

    assert violations == [], (
        f"{len(violations)} Labs font-size declarations bypass the shared scale, "
        f"first: {violations[0] if violations else None}"
    )
