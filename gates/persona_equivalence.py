#!/usr/bin/env python3
"""G-31 - Persona equivalence after the A7 vocabulary collapse.

A7 retired the two-axis identity model: ``support-lead`` is gone, the
``workbench.role`` GUC is deleted, and one persona now drives everything. That
collapse is only safe if it changed **vocabulary**, not **semantics**. The
observable contract is: whatever the old ``role=workshop`` identity could retrieve
and cite, the new ``persona_analyst`` persona retrieves and cites - byte-identically.

The gate compares live analyst results against ``gates/baselines/analyst_equivalence.json``,
a baseline captured on the pre-collapse corpus and committed to the repo. A
committed baseline (rather than a live A/B against the old code) is what lets this
assertion survive the deletion of the old path: after ``support-lead`` no longer
exists anywhere, the file is the only remaining witness to what it used to return.

Two comparisons:

1. Eval goldens - the judged relevance set the Lab-2 checkpoints score against.
   Any drift here moves a golden, which moves a checkpoint number in the guide.
2. Claim coverage - how many current chunks the identity can reach per document.
   Not the citation list: ``proof.answer_citations`` holds that and needs a
   persisted run, which a read-only gate must not create. Drift here means the
   evidence available to support a claim changed, which is what moves the room's
   headline answer.

A mismatch is a FAIL, not a warning: A7 says "any diff means the collapse altered
semantics: STOP and report."

**The two sides are asymmetric on purpose, and that asymmetry is the assertion.**
The baseline side replays the OLD rule explicitly, because the old rule is what is
being deleted: ``retrieval.acl_visible(acl, '{"scopes":["workshop"],"principals":[]}')``
(sql/03_search_functions.sql:1-29) resolved to *visibility is in my scopes AND the
row names no principal I lack*. The live side applies NO visibility predicate at
all - it issues a bare SELECT under the persona and lets RLS do the filtering.

That is the only shape in which this gate asserts anything. An earlier draft
filtered BOTH sides on ``acl_visibility = 'workshop'``; that version is vacuous -
drop every RLS policy and it still PASSes, because the explicit WHERE performs the
filtering the policies were supposed to prove. The live side must be a bare SELECT
so that a missing, mis-scoped, or non-FORCEd policy shows up as a row-count diff.

The corollary is that the pre-collapse rule must be replayed EXACTLY, including the
principals leg. ``CASE-7421`` today carries ``{"visibility": "workshop",
"principals": ["support-lead"]}`` (seed/corpus.py:13-16), so the pre-collapse
identity - empty ``principals`` - could NOT read it. Capturing on visibility alone
would record it as visible, and after Task 13 reclassifies it to
``visibility='restricted'`` the analyst correctly cannot see it, so the gate would
FAIL and report "the collapse altered semantics" for a row whose semantics the
collapse faithfully PRESERVED (denied before, denied after).

Background filler is excluded from claim coverage. ``_background_rows`` generates
``background_documents`` synthetic rows (default 15,000 - seed/corpus.py:1148,
200 under the local Makefile target), every one of them ``WORKSHOP_ACL`` and
one-chunk, so including them buries the ~17 canonical rows this assertion cares
about under 15k rows of the constant 1, ties the committed baseline to a seeding
knob, and inflates the file to ~900 kB. ``*-BG-*`` is the documented filler marker
(gates/noun_lint.py:19,122).

Read-only. Baseline absent, or the persona not created yet -> BLOCKED.

Usage:
    gates/persona_equivalence.py             # compare live analyst vs baseline
    gates/persona_equivalence.py --capture   # write the baseline (pre-collapse only)
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
    repo_root,
)

GATE_ID = "G-31"
TITLE = "Persona equivalence after the A7 collapse"

BASELINE_PATH = Path("gates/baselines/analyst_equivalence.json")
ANALYST = "persona_analyst"

# The judged relevance set: (query_id, evidence_kind, external_key, relevance)
# tuples the Lab-2 checkpoints score against. The grade column is named `relevance`
# (sql/01_schema.sql:1512) -- there is no `grade` column, and naming one would
# raise UndefinedColumn 42703 at PLAN time, which main_guard turns into a
# traceback rather than a verdict.
#
# `evidence_kind` is in the key because external_key alone is NOT unique:
# casework.evidence_items is UNIQUE (evidence_kind, external_key) (:44). Keying on
# external_key alone would silently collapse two graded rows that share a key
# across kinds, and _diff_summary's dict build would keep only the last one.
#
# {vis} is substituted with a per-side visibility predicate: the OLD rule for the
# baseline, TRUE for the live side (RLS filters it). Never with anything derived
# from input -- these are two module constants, not a query builder.
EVAL_GOLDENS_SQL = """
SELECT j.query_id, e.evidence_kind, e.external_key, j.relevance
  FROM proof.relevance_judgments j
  JOIN casework.evidence_items e USING (evidence_id)
 WHERE NOT e.is_deleted
   AND {vis}
 ORDER BY j.query_id, e.evidence_kind, e.external_key
"""

# Claim coverage: current reachable chunks per current non-filler document.
# retrieval.chunks has no external_key (it is on documents), and
# documents.document_version_id is that table's PRIMARY KEY which chunks carries as
# a NOT NULL FK, so this join is many-to-one and cannot fan the count out.
CLAIM_COVERAGE_SQL = """
SELECT d.evidence_kind, d.external_key, count(*) AS reachable_chunks
  FROM retrieval.documents d
  JOIN retrieval.chunks c ON c.document_version_id = d.document_version_id
 WHERE d.is_current
   AND c.is_current
   AND d.external_key NOT LIKE '%-BG-%'
   AND {vis}
 GROUP BY d.evidence_kind, d.external_key
 ORDER BY d.evidence_kind, d.external_key
"""

# The pre-collapse rule, replayed verbatim so the baseline records what the OLD
# identity could actually read. retrieval.acl_visible(acl, principal) is still the
# two-jsonb signature at capture time (sql/03_search_functions.sql:1; Task 9 is what
# drops it for the (jsonb, name) form), and the workshop principal is the literal
# the API sent (backend/app/models.py:22). Calling the live function rather than
# restating its logic means the baseline cannot drift from the rule it claims to
# record. Both `acl` columns are jsonb, on evidence_items (:29) and documents (:900).
OLD_RULE_EVIDENCE = (
    """retrieval.acl_visible(e.acl, '{"scopes":["workshop"],"principals":[]}'::jsonb)"""
)
OLD_RULE_DOCUMENT = (
    """retrieval.acl_visible(d.acl, '{"scopes":["workshop"],"principals":[]}'::jsonb)"""
)

# The live side asserts nothing itself -- RLS is the subject under test. A
# visibility predicate here would make this gate vacuous: it would PASS with every
# policy dropped.
RLS_FILTERS = "true"


def _fetch(conn, sql: str, persona: str | None) -> list[list]:
    """Run ``sql`` (optionally under ``persona``) and return JSON-comparable rows."""
    with conn.cursor() as cur:
        cur.execute("BEGIN")
        try:
            if persona:
                cur.execute(f"SET LOCAL ROLE {persona}")
            cur.execute(sql)
            return [list(row) for row in cur.fetchall()]
        finally:
            cur.execute("ROLLBACK")


def _diff_summary(label: str, expected: list[list], actual: list[list]) -> list[str]:
    """Return human-readable diff lines for two ordered row lists."""
    lines: list[str] = []
    exp = {tuple(row[:-1]): row[-1] for row in expected}
    act = {tuple(row[:-1]): row[-1] for row in actual}
    for key in sorted(set(exp) - set(act)):
        lines.append(f"    {label}: MISSING {key} (baseline value {exp[key]})")
    for key in sorted(set(act) - set(exp)):
        lines.append(f"    {label}: UNEXPECTED {key} (live value {act[key]})")
    for key in sorted(set(exp) & set(act)):
        if exp[key] != act[key]:
            lines.append(
                f"    {label}: CHANGED {key} baseline={exp[key]} live={act[key]}"
            )
    return lines


def _capture(owner_dsn: str, path: Path) -> int:
    """Write the pre-collapse baseline. Refuses to overwrite an existing one.

    Overwriting is the one irreversible thing this gate could do. Once the
    collapse lands, a re-capture would record post-collapse semantics under a
    pre-collapse label, and the gate would compare the new world against itself
    and PASS - destroying the only witness A7 has. Delete the file deliberately
    if you really mean to re-baseline.
    """
    import psycopg

    if path.exists():
        print(f"  refusing to overwrite the existing baseline at {path}")
        return FAIL

    with psycopg.connect(owner_dsn, connect_timeout=15, autocommit=True) as conn:
        # The two-jsonb acl_visible must still exist, or this capture is recording
        # the wrong world. After Task 9 it is DROPped in favour of (jsonb, name),
        # and the call below would raise UndefinedFunction 42883 at plan time --
        # main_guard translates only AssertionError, so that is a traceback rather
        # than a verdict. Refuse instead: a baseline captured post-Task-9 is
        # worthless, because the rule it claims to witness is already gone.
        #
        # to_regprocedure, NOT pg_get_function_identity_arguments. Measured on
        # PG17: identity_arguments returns 'p_acl jsonb, p_principal jsonb' --
        # it includes PARAMETER NAMES, so comparing it to 'jsonb, jsonb' can never
        # match and this guard would refuse every capture on a healthy cluster.
        # (That is exactly why G-30's probe compares against 'payload jsonb' and
        # not 'jsonb'.) to_regprocedure resolves by type signature, ignores
        # parameter names, discriminates (jsonb,jsonb) from Task 9's (jsonb,name),
        # and returns NULL instead of raising when the function or schema is
        # absent -- so it cannot become the 42883 traceback it exists to prevent.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regprocedure('retrieval.acl_visible(jsonb, jsonb)')"
            )
            if cur.fetchone()[0] is None:
                print(
                    "  retrieval.acl_visible(jsonb, jsonb) is gone; the pre-collapse "
                    "rule can no longer be replayed, so this baseline would be a "
                    "forgery. Capture must happen before Task 9."
                )
                return FAIL
        payload = {
            "captured_under": (
                "pre-A7 role=workshop semantics, replayed via "
                "retrieval.acl_visible(acl, {\"scopes\":[\"workshop\"],\"principals\":[]})"
            ),
            "eval_goldens": _fetch(
                conn, EVAL_GOLDENS_SQL.format(vis=OLD_RULE_EVIDENCE), None
            ),
            "claim_coverage": _fetch(
                conn, CLAIM_COVERAGE_SQL.format(vis=OLD_RULE_DOCUMENT), None
            ),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"  captured baseline: {len(payload['eval_goldens'])} goldens, "
        f"{len(payload['claim_coverage'])} covered documents -> {path}"
    )
    return PASS


def run() -> int:
    print_header(GATE_ID, TITLE)
    root = repo_root()
    baseline_path = root / BASELINE_PATH

    owner_dsn = read_env_value("DATABASE_URL")
    if not owner_dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not set (env or .env)")

    try:
        import psycopg
    except ImportError:
        return finish(GATE_ID, BLOCKED, "psycopg is not importable")

    if "--capture" in sys.argv:
        print(f"  engine: {redact_dsn(owner_dsn)}")
        code = _capture(owner_dsn, baseline_path)
        summary = (
            f"baseline written to {BASELINE_PATH}"
            if code == PASS
            else f"{BASELINE_PATH} already exists; delete it to re-baseline"
        )
        return finish(GATE_ID, code, summary)

    if not baseline_path.exists():
        return finish(
            GATE_ID,
            BLOCKED,
            f"{BASELINE_PATH} not captured yet; run with --capture before the collapse",
        )

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    app_dsn = read_env_value("WORKSHOP_APP_DATABASE_URL")
    if not app_dsn:
        return finish(
            GATE_ID, BLOCKED, "WORKSHOP_APP_DATABASE_URL is not set; cannot SET ROLE"
        )

    print(f"  engine: {redact_dsn(app_dsn)}")
    print(f"  baseline captured under: {baseline['captured_under']}")

    try:
        with psycopg.connect(app_dsn, connect_timeout=15, autocommit=True) as conn:
            # Existence check BEFORE the SET LOCAL ROLE. Task 5 creates the
            # persona; until then SET ROLE raises UndefinedObject (42704), and
            # main_guard translates only AssertionError -- so an unguarded
            # SET ROLE reports this gate as a traceback instead of the honest
            # BLOCKED that an unbuilt dependency deserves.
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [ANALYST])
                if cur.fetchone() is None:
                    return finish(
                        GATE_ID, BLOCKED, f"{ANALYST} does not exist yet"
                    )
            # A persona the app login is not granted raises InsufficientPrivilege
            # (42501) on SET ROLE, and a missing SELECT grant raises it on the
            # read. Both are unbuilt Task 5 grants, not semantic drift: FAILing
            # here would claim the A7 collapse changed semantics when the truth
            # is that nothing is wired up yet.
            try:
                live_goldens = _fetch(
                    conn, EVAL_GOLDENS_SQL.format(vis=RLS_FILTERS), ANALYST
                )
                live_coverage = _fetch(
                    conn, CLAIM_COVERAGE_SQL.format(vis=RLS_FILTERS), ANALYST
                )
            except psycopg.errors.InsufficientPrivilege as exc:
                return finish(
                    GATE_ID,
                    BLOCKED,
                    f"{ANALYST} cannot be assumed or cannot read the corpus: {exc}",
                )
    except psycopg.OperationalError as exc:
        return finish(GATE_ID, BLOCKED, f"cannot reach the engine: {exc}")

    print(
        f"\n  eval goldens:   baseline={len(baseline['eval_goldens'])} "
        f"live={len(live_goldens)}"
    )
    print(
        f"  claim coverage: baseline={len(baseline['claim_coverage'])} "
        f"live={len(live_coverage)}"
    )

    diffs = _diff_summary("goldens", baseline["eval_goldens"], live_goldens)
    diffs += _diff_summary("coverage", baseline["claim_coverage"], live_coverage)

    if diffs:
        print("\n  DIFFS (A7 STOP condition):")
        for line in diffs:
            print(line)
        return finish(
            GATE_ID,
            FAIL,
            f"{len(diffs)} semantic difference(s) between the baseline and the analyst "
            f"persona; the A7 collapse altered semantics - STOP and report",
        )

    return finish(
        GATE_ID,
        PASS,
        f"analyst persona reproduces the baseline byte-identically "
        f"({len(live_goldens)} goldens, {len(live_coverage)} covered documents)",
    )


if __name__ == "__main__":
    main_guard(run)
