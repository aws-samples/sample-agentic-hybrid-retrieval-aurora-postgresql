# Staged catalog wiring — September 20, 2026

The new public catalog is inspectable at `/catalog-preview`, with source evidence
loaded from Aurora. Shop, its comparisons, the agent and the required lab targets
still use the existing live catalog. This is source-wiring evidence, not a
replacement retrieval or release acceptance result.

## Observed results

- The production product projection processed all 500,000 selected records with
  no integrity or shape failures. Original titles, taxonomy, text hashes and
  source photo identities were retained.
- Historical prices: 211,711 exact amounts, 78 starting amounts and 288,211
  unreported values. The 419 initial failures exposed the source's `—` and
  `from …` forms; the adapter now preserves their meaning. Current prices,
  availability and inventory are unknown.
- The sample importer re-fetched and matched every retained review's raw bytes
  against its pinned source URL and offset. Aurora holds 32 selected reviews
  for seven sample products and nine variants; eight purchase flags are false.
- Live HTTP resolved all ten specification records and all 32 review records
  to their original parent products. A review requested under another parent
  returned 404. Placeholder and starting prices were also checked through HTTP.
- Desktop 1440px and mobile 390px evidence views loaded actual Aurora records
  without horizontal overflow. Review line breaks are plain text; source markup
  is never executed. The original text remains available at the source link.

The scans cover only prefixes of the two review files. They are deliberately
selected examples, not complete coverage or an unbiased survey. Steelcase
Gesture, renewed LG 27UL850 and Dell U2720Q-Black have no imported review text.
The aggregate receipts contain no raw review text or reviewer identifiers:
[`staged-source-2026-09-20.json`](catalog-source-audit/staged-source-2026-09-20.json).

## Validation and remaining release work

The source projection, sampler, importer and API have permanent tests for
identity changes, altered source bytes, unselected parents, cross-product
citations and preserving an unfinished download range on resume. The importer
tests assert that the remote fetch executes and a missing parent blocks writes;
an irrelevant sample note does not invalidate source identity.

The focused frontend run passed 28 tests. The full frontend run passed 673 of
674 tests; the remaining asset gate found the two new hero photos not yet in
the Git index. After adding those exact files, both asset tests passed. The
production build passed, with the existing large HNSW chunk warning.

The full Python run passed 1,381 tests and found five failures. Three were fixed:
the adapter check now exercises actual HTTP routes, the bootstrap proxy check
only follows proxy-target environment variables, and the DB checksums include
the corrected lab instruction text. The affected rerun passed 47 tests, with
two Aurora-only tests skipped in that DSN-free rerun. Two scorecard attribution
checks remain red because the measured baseline predates the changed source
contract; do not relabel the old result as current. A clean reviewed revision
and fresh measurement are still required.

The live mission gate passed 124 checks. Both evaluation contracts passed against
Aurora: 720 canonical judged targets and 74 additional targets. Configuration
tripwire and retrieval-profile checks passed. Workshop Studio passed 126 tests
using this worktree as `MOSAIC_SOURCE_REPO`, plus participant-query, timing, page
structure and source-line checks. Its immutable publishing gate still rejects
the uncommitted source revision, as intended.

The revised session is 10 minutes of introduction, then 10 / 10 / 20 minutes
for Retrieve / Rank / Reason. Required completion is minute 50; flex is 50–60.
Each lab bookmarks its relevant extension without interrupting the core path.
Memory remains optional Lab 4 after the hour.

Before Shop switches, resolve its integer product identities to stable source
parents, preserve nullable offers, and use the same identities in search,
comparison and citations. Existing in-stock controls cannot be applied as if
this historical dataset supplied present availability. Measure replacement
queries and their deliberate failures on Aurora, then update the canonical
mission contract and dependent materials together. Complete embeddings and
search indexes before claiming full-catalog vector coverage.

The audited ESCI products download (1,108,857,465 bytes) and generated UI build
output were removed to recover disk space. The ESCI source pointer, matching
SHA-256 audit and selected preview records remain for reproducibility.
