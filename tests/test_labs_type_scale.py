"""The Labs type scale must be shared, and the gate must prove it.

House bar: a green check is not evidence on its own. The synthetic fixtures below
are the permanent falsifiers — each one is a violation the gate must catch, kept
as a test so the gate is re-proven on every run rather than once at birth.

The last test reads both stylesheets. It used to read only `surfaces.css`, which is
how 42 off-scale declarations sat in `styles.css` on the same surfaces this gate
governs while the gate reported green.
"""

from __future__ import annotations

from scripts.labs_type_scale import (
    STYLESHEETS,
    scan_labs_type,
)


def scan(css: str):
    return scan_labs_type(css, "fixture.css")


def test_gate_catches_a_px_literal_in_a_labs_rule():
    css = ".hnsw-live > footer small {\n  font-size: 9.5px;\n}\n"

    violations = scan(css)

    assert [violation.value for violation in violations] == ["9.5px"]
    assert violations[0].selector == ".hnsw-live > footer small"
    assert violations[0].line == 2
    assert violations[0].property_name == "font-size"
    assert violations[0].sheet == "fixture.css"


def test_gate_catches_em_and_clamp_literals_too():
    css = (
        ".labs-intro-copy h1 {\n  font-size: clamp(48px, 4.6vw, 66px);\n}\n"
        ".lab-card p {\n  font-size: 0.94em;\n}\n"
    )

    values = [violation.value for violation in scan(css)]

    assert values == ["clamp(48px, 4.6vw, 66px)", "0.94em"]


def test_gate_admits_a_labs_token():
    css = ".mosaic-studio-briefs .eyebrow {\n  font-size: var(--labs-micro);\n}\n"

    assert scan(css) == []


def test_gate_ignores_rules_outside_the_labs_families():
    css = ".product-card strong {\n  font-size: 13px;\n}\n"

    assert scan(css) == []


def test_gate_covers_the_retrieval_panels_on_the_labs_surface():
    """`.retrieval-*` panels render on a Labs surface but were outside the families.

    The Retrieval Observatory's own panels are named for what they show, so they
    escaped a family list built from surface names. That let a 9.5px `dt` and a
    23px `h2` sit directly under a masthead on the shared scale.
    """
    css = ".retrieval-run-comparison dt {\n  font-size: 9.5px;\n}\n"

    assert [violation.value for violation in scan(css)] == ["9.5px"]


def test_gate_rejects_a_non_labs_variable_inside_a_labs_rule():
    css = ".hnsw-graph header {\n  font-size: var(--detail);\n}\n"

    assert [v.value for v in scan(css)] == ["var(--detail)"]


def test_gate_reports_the_line_of_a_later_declaration():
    css = (
        ".product-card {\n  color: red;\n}\n\n"
        ".labs-intro-deck {\n  margin: 0;\n  font-size: 17px;\n}\n"
    )

    violations = scan(css)

    assert [(v.value, v.line) for v in violations] == [("17px", 7)]


def test_gate_catches_a_font_family_literal():
    """45 copies of one monospace stack meant no single place to change it."""
    css = (
        ".labs-matrix-query code {\n"
        '  font-family: "SFMono-Regular", Consolas, monospace;\n'
        "}\n"
    )

    violations = scan(css)

    assert [violation.property_name for violation in violations] == ["font-family"]
    assert (
        "use var(--display), var(--masthead), var(--sans) or var(--mono)"
        == violations[0].remedy
    )


def test_gate_admits_the_four_family_tokens_and_inherit():
    # `--masthead` is the seam the five commerce and Labs mastheads swap
    # through together; it is a first family here, not a second one.
    css = (
        ".labs-matrix-heading h2 {\n  font-family: var(--display);\n}\n"
        ".labs-intro-copy h1 {\n  font-family: var(--masthead);\n}\n"
        ".labs-matrix-controls select {\n  font-family: var(--sans);\n}\n"
        ".labs-matrix-identity > small {\n  font-family: var(--mono);\n}\n"
        ".hnsw-ab button {\n  font-family: inherit;\n}\n"
    )

    assert scan(css) == []


def test_gate_rejects_a_family_variable_from_outside_the_type_system():
    css = ".labs-matrix-query {\n  font-family: var(--script);\n}\n"

    assert [v.value for v in scan(css)] == ["var(--script)"]


def test_every_labs_declaration_uses_the_shared_type_system():
    violations = [
        violation
        for stylesheet in STYLESHEETS
        for violation in scan_labs_type(
            stylesheet.read_text(encoding="utf-8"), stylesheet.name
        )
    ]

    assert violations == [], (
        f"{len(violations)} Labs declarations bypass the shared type system, "
        f"first: {violations[0] if violations else None}"
    )
