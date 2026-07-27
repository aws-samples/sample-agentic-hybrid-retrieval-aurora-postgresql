#!/usr/bin/env python3
"""G-14 - Empty-database UI test (built-bundle numeral denylist).

SPEC-session Section 10, G-14: workbench against a schema-only DB renders only
empty states; the built frontend bundle contains no fixture numerals (denylist:
``0.0650``, ``94.8``, ``12,011``, ``48,226``, rerank scores, ...).

Law 2 (psql parity): nothing renders in the workbench that cannot be reproduced
from psql with a ``run_id``. A fixture numeral compiled into the shipped bundle
is a value that renders without the engine having produced it - the exact
violation this gate exists to catch.

This gate is the static half of G-14: it scans the built bundle
(``frontend/dist``) for a denylist. It does not stand up a schema-only database
(that is the runtime half, run during the dry run). If the bundle has not been
built yet, the gate reports BLOCKED rather than FAIL, because there is nothing to
scan.

The denylist targets *values the engine must produce*, not Law 1 nouns:

1. The exact fixture numerals named in the spec, plus the canonical-thread scores
   and sizes from the UI design system Section 7 (corpus counts, timings, RRF
   sums), and the pre-rendered run receipts. A precomputed similarity or a baked
   ``rr_*`` receipt is a number that renders without a run - the spec's literal
   target.
2. Round-number identifiers (``CHG-1000``, ``INC-2000``, ...). After Step 1 the
   corpus is canonical; a round ID reappearing in the bundle is the tell-tale of
   a regenerated-but-not-live fixture and fails the gate.

Canonical identifiers (``CHG-1842``, ``INC-2047``, ...) are NOT denylisted: they
are Law 1 nouns and legitimately seed query-input affordances (the default query,
the presets, the D14 ``CGH-1842`` fuzzy probe) and guide narrative, which are
participant input and teaching copy, not faked engine output. What the gate must
still catch - a hardcoded *rendered evidence structure* that pairs canonical IDs
with pre-decided present/missing verdicts - is a structural fixture, addressed by
removing such blocks from the source (e.g. the answer-source expected-state
fallback), not by denylisting the IDs themselves.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    repo_root,
)
from noun_lint import SYNONYM_TO_CANONICAL  # noqa: E402

GATE_ID = "G-14"
TITLE = "Empty-database UI test (built-bundle numeral denylist)"

BUNDLE_DIR = Path("frontend/dist")
SCAN_SUFFIXES = {".js", ".css", ".html", ".json", ".map"}

# Fixture numerals named in the spec (G-14) and the UI design system Section 7.
# A hit is an exact substring match, so decimal points and separators matter.
NUMERAL_DENYLIST = [
    "0.0650",   # naive-RRF worked example
    "0.06505",  # expanded RRF sum
    "0.0491",   # the documented drift artifact
    "94.8",     # illustrative percentage
    "12,011",   # corpus document count
    "48,226",   # ready-chunk count
    "1,356",    # agent total ms
    "1,240",    # synthesis ms
    "0.5000",   # cgh-1842 trigram similarity
    "0.3846",   # banned chg-1482 tie
]

# Canonical run receipts (UI design system Section 7) - never precompiled.
RECEIPT_DENYLIST = [
    "rr_9b41d7",
    "rr_9b41d4",
    "rr_9b41d5",
    "rr_9b41d6",
    "rr_9b41d2",
]

# Round-number placeholder identifiers are forbidden in the bundle: after Step 1
# the corpus is canonical, so a round CHG-1000 reappearing in the compiled UI is
# the tell-tale of a regenerated-but-not-live fixture. Sourced from the noun-lint
# synonym map so the two gates never disagree about what a round ID is. Canonical
# identifiers (CHG-1842, ...) are intentionally NOT here: they are Law 1 nouns
# that legitimately seed query-input affordances and guide narrative.
IDENTIFIER_DENYLIST = sorted(SYNONYM_TO_CANONICAL)

TERM_RE = re.compile(
    "|".join(
        re.escape(t)
        for t in NUMERAL_DENYLIST + RECEIPT_DENYLIST + IDENTIFIER_DENYLIST
    )
)


def _iter_bundle_files(bundle: Path):
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES:
            yield path


def run() -> int:
    print_header(GATE_ID, TITLE)
    root = repo_root()
    bundle = root / BUNDLE_DIR
    if not bundle.is_dir():
        return finish(
            GATE_ID,
            BLOCKED,
            f"{BUNDLE_DIR} not built; run the frontend build before this gate",
        )

    files = list(_iter_bundle_files(bundle))
    if not files:
        return finish(
            GATE_ID, BLOCKED, f"{BUNDLE_DIR} has no scannable assets"
        )

    hits: list[tuple[str, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        for match in TERM_RE.finditer(text):
            hits.append((rel, match.group(0)))

    if not hits:
        return finish(
            GATE_ID,
            PASS,
            f"scanned {len(files)} bundle assets; no fixture numerals or "
            f"canonical IDs baked in",
        )

    by_term: dict[str, int] = {}
    by_file: dict[str, int] = {}
    for rel, term in hits:
        by_term[term] = by_term.get(term, 0) + 1
        by_file[rel] = by_file.get(rel, 0) + 1

    print("  denylisted terms found in the built bundle:")
    for term, count in sorted(by_term.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {term}: {count}")
    print("  files:")
    for rel, count in sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {rel}: {count}")

    return finish(
        GATE_ID,
        FAIL,
        f"{len(hits)} denylisted terms in the built bundle across "
        f"{len(by_file)} files ({len(by_term)} distinct terms)",
    )


if __name__ == "__main__":
    main_guard(run)
