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

Both sides apply the SAME visibility rule, and the rule lives in the query rather
than in the reader. The baseline is captured as the bootstrap owner, an
``rds_superuser`` member that RLS does not apply to; the live side runs under a
persona that RLS filters. Comparing an unfiltered baseline against an
RLS-filtered persona would FAIL by construction the moment Task 13 reclassifies a
row - reporting "the collapse altered semantics" for the row filter that is the
whole point of the exercise.

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

# The judged relevance set: (query_id, external_key, relevance) triples the Lab-2
# checkpoints score against. The grade column is named `relevance`
# (sql/01_schema.sql:1512) -- there is no `grade` column, and naming one would
# raise UndefinedColumn 42703 at PLAN time, which main_guard turns into a
# traceback rather than a verdict.
#
# `evidence_kind` is in the key because external_key alone is NOT unique:
# casework.evidence_items is UNIQUE (evidence_kind, external_key) (:44). Keying on
# external_key alone would silently collapse two graded rows that share a key
# across kinds, and _diff_summary's dict build would keep only the last one.
#
# The visibility rule is applied HERE, in the query, so the owner-captured
# baseline and the RLS-filtered persona are compared over the same population.
# `acl ->> 'visibility'` with the fail-closed 'restricted' default is byte-equal
# to the RLS policy's first disjunct on this table (Task 5 policy
# rls_evidence_visibility), and evidence_items has no acl_visibility column --
# only the jsonb (:29). Task 13 flips the constant this reads.
EVAL_GOLDENS_SQL = """
SELECT j.query_id, e.evidence_kind, e.external_key, j.relevance
  FROM proof.relevance_judgments j
  JOIN casework.evidence_items e USING (evidence_id)
 WHERE NOT e.is_deleted
   AND coalesce(e.acl ->> 'visibility', 'restricted') = 'workshop'
 ORDER BY j.query_id, e.evidence_kind, e.external_key
"""

# Claim coverage: current reachable chunks per current document. Both sides filter
# on acl_visibility, the denormalized scalar the RLS policies on documents and
# chunks read (sql/01_schema.sql:901,968; policies rls_documents_visibility and
# rls_chunks_visibility). Filtering both tables mirrors the two policies: a
# document and its chunks carry the same scalar (:1047), so this cannot drop a
# chunk whose document survives.
CLAIM_COVERAGE_SQL = """
SELECT d.evidence_kind, d.external_key, count(*) AS reachable_chunks
  FROM retrieval.documents d
  JOIN retrieval.chunks c ON c.document_version_id = d.document_version_id
 WHERE d.is_current
   AND c.is_current
   AND d.acl_visibility = 'workshop'
   AND c.acl_visibility = 'workshop'
 GROUP BY d.evidence_kind, d.external_key
 ORDER BY d.evidence_kind, d.external_key
"""


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
        payload = {
            "captured_under": "pre-A7 owner identity (role=workshop semantics)",
            "eval_goldens": _fetch(conn, EVAL_GOLDENS_SQL, None),
            "claim_coverage": _fetch(conn, CLAIM_COVERAGE_SQL, None),
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
                live_goldens = _fetch(conn, EVAL_GOLDENS_SQL, ANALYST)
                live_coverage = _fetch(conn, CLAIM_COVERAGE_SQL, ANALYST)
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
