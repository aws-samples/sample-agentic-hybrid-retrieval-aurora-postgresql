"""Fingerprint the files that can move the canonical scorecard's numbers.

`service/scorecard.py` used to gate on `artifact_revision == current_revision`.
That equality can never hold: `scripts/score_evals.py` records
`service.config._source_identity()`'s revision *before* the artifact it writes
is committed, so committing the artifact always advances HEAD one commit past
what was measured (proven in git history: the artifact recorded `0869073`, and
the commit that adds it, `8d7fad4`, has `0869073` as its parent). The scorecard
would read "pending" forever.

Comparing ancestry or diffing two revisions at serve time is not available
either: `deploy/mosaic-bootstrap.sh` fetches with `--depth 1`, so the workshop
host is a shallow clone with no history to walk.

What *is* available on a shallow clone is the files themselves, present even
without history. This module hashes a frozen manifest of exactly the files
that can change what `scripts/score_evals.py` measures, computed once at
measurement time and again at serve time; a mismatch means "the served
retrieval path or the scoring definition changed since this artifact was
measured," which is the only claim the fingerprint needs to make.

Manifest, and why each entry earns its place
----------------------------------------------
- ``db/sql/*.sql`` (every file, recursive): the fusion, indexing, and
  eligibility SQL the retrieval arms call --
  ``mosaic_search.search_hybrid_rrf`` and ``configure_hnsw`` live here.
- ``db/config/retrieval.yaml``: the single source for candidate limits,
  fusion k, weights, and HNSW tuning (``scripts.retrieval_profile``).
- ``service/retrieval.py``, ``service/rerank.py``, ``service/embeddings.py``,
  ``service/bedrock.py``: the served retrieval, reranking, and
  model-invocation path ``scripts/score_evals.py`` measures through
  ``service.retrieval.get_retrieval_service``.
- ``scripts/retrieval_profile.py``: resolves the yaml above into the profile
  the service actually applies.
- ``scripts/evaluate.py``: computes Recall, MRR, and nDCG. Editing the
  formula moves every number with no retrieval change at all.
- ``scripts/eval_contract.py``: resolves mission-backed query text and
  filters into the scored query population (see the added file below).
- ``data/evals/canonical_queries.jsonl``: carries the relevance judgments
  inline (a ``judgments`` key per row), covering both the query population
  and the grades.

Added to the manifest specified by the request, and why
---------------------------------------------------------
- ``data/evals/mosaic_labs_missions.json``: ``scripts/eval_contract.py``'s
  ``load_evaluation_queries`` substitutes *this* file's ``query`` and
  ``filters`` into every mission-backed canonical query before scoring --
  measured at 8 of the 19 currently-scored ``product_retrieval`` queries
  (``G-001``, ``G-003``, ``G-004``, ``G-007``, ``G-008``, ``G-009``,
  ``G-012``, ``G-019``). Editing a mission's ``filters`` changes candidate
  eligibility for those queries without changing a single byte of
  ``canonical_queries.jsonl``. Leaving this file out of the manifest would
  have reopened exactly the blind spot this module exists to close, so it is
  added here rather than left to the frozen list as specified.

Deliberately excluded, and why
---------------------------------
- ``service/catalog.py``: not in the retrieval closure; cannot affect scored
  metrics.
- ``service/config.py``, ``service/db.py``: noise. They change for reasons
  unrelated to retrieval quality, and model identity is carried as its own
  separate provenance field rather than folded into this hash.
- ``service/models.py``: excluded from *this* hash for the same reason, but
  **not uncovered** -- it defines the served shape, so it is in both
  methodology manifests below.
- ``data/evals/canonical_scorecard.json``: emphatically excluded. Including
  it would recreate the exact off-by-one this module exists to kill -- the
  artifact would be hashing itself.
- ``scripts/score_evals.py``: the measurement harness itself. Including it here
  would move the fingerprint on harness refactors that touch no retrieval
  behavior, and worse, invalidate a paid measurement over a console-output
  change. It is **not uncovered** either: it is in both methodology manifests
  below, which is where an audit correctly said it belonged.

Methodology hashes: the same problem, one layer up
---------------------------------------------------
Excluding the harness from the retrieval fingerprint left a real gap an audit
found: ``scripts/score_evals.py`` assembles the artifact and selects the scored
population, ``service/models.py`` defines the shape it is served in, and this
module decides what counts as provenance at all. Editing any of them can change
a published number while ``retrieval_fingerprint`` sits perfectly still.

Folding them into ``retrieval_fingerprint`` would be the wrong fix. That hash
gates a *paid* measurement, so coupling it to the harness means a console-output
tweak invalidates a billed run. Instead there are two narrower hashes, and
retrieval quality never depends on ablation code:

- ``scorecard_methodology_sha256`` covers ``service/models.py``,
  ``scripts/score_evals.py``, and this file.
- ``ablation_methodology_sha256`` covers those three plus
  ``scripts/ablation_evals.py``.

So an ablation-only edit marks the ablation section pending and leaves canonical
retrieval metrics attributed, while a change to the shared three marks both.

This module is inside both manifests deliberately. The code that decides what
provenance means must be covered by the provenance it computes, or editing the
definition would be the one change no hash can see.

A methodology mismatch marks the section pending, and pending is resolved only
by re-measuring. An earlier design offered offline "recertification" from the
persisted served results; an audit disproved its premise. Reproducing historical
output proves nothing about a behaviour change, because the output predates the
change: altering filter serialization in ``service/models.py`` or making the
semantic arm return no rows leaves the old CSV intact and therefore perfectly
reproducible, so recertification restored attribution to a build it had not
verified. No subset of these files is safely recertifiable -- each one can change
what the system does -- so the mechanism was removed rather than narrowed.

The ablation's re-measure spends no reranker calls, so only the canonical
scorecard's costs anything, and only when one of three rarely-edited files
changes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Exactly the file count each manifest category must produce. A category
# collapsing to a shorter list -- an empty `db/sql/` glob, a moved file --
# must fail loudly rather than silently hash fewer files under a name that
# still reads as complete. Checked against these literals, never against
# another count derived from the same glob (house standards rule 7's
# independent-witness requirement).
_EXPECTED_CATEGORY_COUNTS: dict[str, int] = {
    # 27 since db/sql/20_query_coverage.sql. Adding it moves the retrieval
    # fingerprint, so the committed scorecard reads unattributed until the next
    # measured baseline. That is the correct reading: the served path now
    # carries a query-coverage step.
    "sql": 27,
    "config": 1,
    "service": 4,
    "scripts": 3,
    "eval_data": 2,
}


class RetrievalFingerprintError(RuntimeError):
    """The retrieval fingerprint cannot be computed as specified.

    Same class of failure as `service.config.ConfigurationError` and
    `scripts.retrieval_profile.ProfileError`: refusing to produce a
    fingerprint is the difference between a loud, legible failure and a
    fingerprint that silently omits a whole category of retrieval-defining
    files while still looking like a valid hash.
    """


def explain(found: str, fix: str) -> str:
    """Render a failure in the house style: offending value, then nearest fix."""
    return f"found {found}; fix: {fix}"


def _category_files(repo_root: Path) -> dict[str, tuple[Path, ...]]:
    """Every file in each manifest category. Order within a group is not
    significant; `manifest_files` re-sorts everything by path."""
    return {
        "sql": tuple(sorted((repo_root / "db" / "sql").rglob("*.sql"))),
        "config": (repo_root / "db" / "config" / "retrieval.yaml",),
        "service": (
            repo_root / "service" / "retrieval.py",
            repo_root / "service" / "rerank.py",
            repo_root / "service" / "embeddings.py",
            repo_root / "service" / "bedrock.py",
        ),
        "scripts": (
            repo_root / "scripts" / "retrieval_profile.py",
            repo_root / "scripts" / "evaluate.py",
            repo_root / "scripts" / "eval_contract.py",
        ),
        "eval_data": (
            repo_root / "data" / "evals" / "canonical_queries.jsonl",
            repo_root / "data" / "evals" / "mosaic_labs_missions.json",
        ),
    }


def _assert_category_witness(categories: dict[str, tuple[Path, ...]]) -> None:
    """Refuse to hash a manifest that silently lost a whole category.

    Runs on every computation, not only in tests: a moved directory or a
    typo'd path constant must not produce a fingerprint that looks valid
    while having hashed zero files from `db/sql/`.
    """
    for name, expected in _EXPECTED_CATEGORY_COUNTS.items():
        files = categories.get(name, ())
        if len(files) != expected:
            raise RetrievalFingerprintError(
                explain(
                    f"manifest category {name!r} has {len(files)} file(s)",
                    f"expected exactly {expected}; if a file was deliberately "
                    "added to or removed from this category, update both the "
                    "file list and _EXPECTED_CATEGORY_COUNTS in "
                    "service/retrieval_fingerprint.py together",
                )
            )
        for path in files:
            if not path.is_file():
                raise RetrievalFingerprintError(
                    explain(
                        f"manifest entry {path} in category {name!r} does not exist",
                        "restore the file, or remove it from the manifest "
                        "deliberately with the category count updated to match",
                    )
                )


def category_counts(repo_root: Path | None = None) -> dict[str, int]:
    """Per-category file counts, for tests and diagnostics."""
    root = repo_root or REPO
    categories = _category_files(root)
    _assert_category_witness(categories)
    return {name: len(files) for name, files in categories.items()}


def manifest_files(repo_root: Path | None = None) -> list[Path]:
    """Every file the fingerprint covers, sorted by repo-relative path.

    Sorting is over the path string so the result is independent of how the
    categories above happen to be assembled or ordered.
    """
    root = repo_root or REPO
    categories = _category_files(root)
    _assert_category_witness(categories)
    files = [path for group in categories.values() for path in group]
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


#: Files that define how the canonical scorecard is measured and served, as
#: opposed to what retrieval does. Repo-relative POSIX paths so the hash is
#: independent of where the tree was cloned.
SCORECARD_METHODOLOGY_FILES: tuple[str, ...] = (
    "scripts/score_evals.py",
    "service/models.py",
    "service/retrieval_fingerprint.py",
)

#: The ablation reuses every scorecard methodology input and adds its own
#: harness. Ordering is irrelevant -- `_methodology_digest` sorts -- but the
#: superset relationship is asserted below so the two hashes cannot drift apart.
ABLATION_METHODOLOGY_FILES: tuple[str, ...] = (
    *SCORECARD_METHODOLOGY_FILES,
    "scripts/ablation_evals.py",
)

#: Independent witnesses, per house standards rule 7: literals, never
#: `len(SCORECARD_METHODOLOGY_FILES)`, which would agree with any edit.
_EXPECTED_METHODOLOGY_COUNTS: dict[str, int] = {
    "scorecard": 3,
    "ablation": 4,
}


def _methodology_digest(
    label: str,
    relpaths: tuple[str, ...],
    repo_root: Path | None = None,
) -> str:
    """Sha256 over a named methodology manifest, same line format as above.

    Reuses `relative/posix/path:sha256\\n` so a methodology hash and a
    retrieval fingerprint are computed identically and can be reasoned about
    together.
    """
    root = repo_root or REPO
    expected = _EXPECTED_METHODOLOGY_COUNTS[label]
    if len(relpaths) != expected:
        raise RetrievalFingerprintError(
            explain(
                f"{label} methodology manifest has {len(relpaths)} file(s)",
                f"expected exactly {expected}; update both the file tuple and "
                "_EXPECTED_METHODOLOGY_COUNTS in "
                "service/retrieval_fingerprint.py together",
            )
        )
    lines = []
    for relpath in sorted(relpaths):
        path = root / relpath
        if not path.is_file():
            raise RetrievalFingerprintError(
                explain(
                    f"{label} methodology entry {relpath} does not exist",
                    "restore the file, or remove it from the manifest "
                    "deliberately with the expected count updated to match",
                )
            )
        lines.append(f"{relpath}:{hashlib.sha256(path.read_bytes()).hexdigest()}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def compute_scorecard_methodology_sha256(repo_root: Path | None = None) -> str:
    """How the canonical scorecard is measured and served, not what it measured."""
    return _methodology_digest("scorecard", SCORECARD_METHODOLOGY_FILES, repo_root)


def compute_ablation_methodology_sha256(repo_root: Path | None = None) -> str:
    """The scorecard methodology plus the ablation harness itself."""
    return _methodology_digest("ablation", ABLATION_METHODOLOGY_FILES, repo_root)


def compute_retrieval_fingerprint(repo_root: Path | None = None) -> str:
    """Sha256 over the frozen manifest of retrieval-defining files.

    Each file contributes one ``relative/posix/path:sha256\\n`` line; the
    fingerprint is the sha256 of the concatenation of those lines, in
    path-sorted order. Deterministic across machines and checkouts: paths are
    always POSIX-normalized and relative to `repo_root`, never absolute, so
    the fingerprint does not change just because the repository was cloned to
    a different directory.
    """
    root = repo_root or REPO
    lines = [
        f"{path.relative_to(root).as_posix()}:"
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in manifest_files(root)
    ]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
