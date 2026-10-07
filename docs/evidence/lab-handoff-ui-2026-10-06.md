# Lab observation, handoff and ranking UI validation

## Change

- Lab 1 Shop card shows the missing product and the typed/listing identifiers,
  with an inspection action. Diagnosis and repair instructions remain in the
  guide's investigation and hints. The mission's Electronics and Headphones
  filters remain required; repaired results still receive feedback.
- `uv run python scripts/lab_state.py advance --lab 1` checks Lab 1 source/applied
  state and production retrieval/filter controls, persists completion, then calls
  the existing resumable Lab 2 start. A handoff record binds the validation to
  the selected connection, Lab 1 entry and seam. Failure before validation cannot
  install Lab 2. Retry does not replay Lab 1 under Lab 2's ranking fault.
- Lab 2 Shop feedback checks entry completion, source/applied state and the saved
  search's occurrence time. A supplied reference result, an old search or an
  unavailable state cannot earn repair credit.
- Shop's comparison sorts the same displayed products, retaining both positions.
  It explicitly distinguishes this from comparing separate top-12 sets.
- Cards use neutral surfaces and small semantic status accents. The redundant
  ranking mini-table and Lab 1's repair instructions were removed from the cards.

## Verification

- Complete offline Python suite: 2,272 passed, 39 live-dependent tests skipped.
- Complete UI suite: 935 passed. Includes lifecycle, saved pre-start results,
  unavailable evidence, stale SQL, and stale state during a new request.
- Follow-up affected Python checks after timestamp precision and command tests:
  75 passed (including interrupted handoff, failure before entry and retry
  preservation). UI production build passed.
- Browser against the local API connected to Aurora: the transposed Logitech
  identifier returned through close spelling at #1; the corrected Lab 1 card
  retained Electronics and Headphones. Event:
  `2881fd2a-2496-4562-aead-8b1466fd0aca`.
- Browser against Aurora: the monitor search showed a neutral Lab 2 Not started
  card despite a plausible first result. Switching between RRF and final order
  preserved all 12 displayed products. At 390px viewport width the card and page
  had no horizontal overflow. The temporary viewport override was reset.
- Updated three screenshots in the workshop repository's `static/lab-guides/`,
  captured from the real local app and API. They show repaired Lab 1, pre-start
  Lab 2 and sorting, not a fresh participant-account rehearsal.
- Workshop participant-query validation: three required payloads match, five
  source controls retained, four rendered controls match. Workshop preflight
  reaches the publication guard and refuses the uncommitted source worktree.

## Remaining release boundary

The live fault-installation handoff rehearsal was refused before mutation:
`DATABASE_URL` selects `mosaic_v2`, while the existing reset guard expects
`mosaic_catalog`. The safeguard was not overridden. The handoff's failure and
resumption tests use real file/record operations with Aurora and HTTP boundaries
substituted. A full live handoff still needs the intended workshop database.

No catalog rows, embeddings, search indexes or exercise faults were changed in
Aurora during that UI-validation pass. Source/guide changes and screenshots
were local at that point; those checks did not establish publication or a
pristine Workshop Studio rehearsal.

## Publication candidate validation

Before publishing the Shop and matching guide changes on 6 October:

- The complete offline Python suite passed: 2,273 passed, 39 live-dependent
  tests skipped. The UI suite passed all 935 tests and its production build.
- Lint, package/schema/configuration contracts, the release-workflow tests,
  the MCP tests and isolated wheel smoke test passed. The UI dependency audit
  reported no vulnerabilities.
- Against the configured development Aurora database, all 125 mission checks,
  canonical and independent evaluation contracts, the function census and
  real-only bootstrap checks passed. The catalog contained 553,911 embedded
  products with no foreign products, synthetic brands or legacy documents.
- The Workshop Studio introduction gate rejected its retired callout, accepted
  unrelated prose, and demonstrably read the introduction through the production
  validator. The original file remained byte-identical.

These checks do not replace the live handoff rehearsal described above or
fresh-account deployment acceptance.
