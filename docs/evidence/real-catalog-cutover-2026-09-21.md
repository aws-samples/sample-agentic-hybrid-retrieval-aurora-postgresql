# Real catalog: local storefront cutover — September 21, 2026

The local storefront on port 5186 and its API on port 8010 now serve the
500,000 selected Amazon Reviews 2023 products from Aurora. This supersedes
the **local Shop wiring status** in the September 20 report; it does not
supersede that report's source-integrity measurements or establish a workshop
release. The work is on `codex/real-product-labs`, based on `c630066`, with
uncommitted changes.

## Data and identity

- Dataset: `reviews-2023-500k-v1`; 400,000 Electronics and 100,000 Office Products.
- Catalog SHA-256: `149563d3bc6b3b090bd49bb6c3eda583636d03aec5c9126add0df1a57447c9c6`.
- Aurora readiness reports 500,000 products and 500,000 embeddings, 1,024
  dimensions, Cohere Embed v4, PostgreSQL 18.3 and pgvector 0.8.1. Required
  retrieval functions and indexes are available. Exact-neighbor reference
  results are explicitly missing for this corpus.
- `prepare_live_catalog.py` registered 500,000 real product identities in
  230.26 seconds, generated **zero** new embeddings, and preserved the historical
  catalog. Public IDs are the physical search IDs plus 1,000,000, so an old
  receipt cannot silently refer to a different product.
- `mosaic_live_search` uses the prepared real search table and the existing
  FTS, trigram, vector, rank-fusion and evidence functions. The real catalog is
  selected explicitly with `MOSAIC_CATALOG_DATASET`.
- Original titles, features, descriptions, specifications, photo identities,
  parent listing links and historical rating counts are preserved. Current
  prices, availability and inventory remain unknown. Review text is a sampled
  subset, not every review behind an aggregate rating.

## Storefront changes and rendered checks

Shop uses bounded, contain-fit photo frames (200–280 pixels high), compact
titles and original listing links. At the checked desktop and narrow widths,
products remain fully visible and the page has no horizontal overflow.

Product 1224428, the supplied Geekria case example, now has a compact gallery
with all eight original photos, a shorter first view and expandable sections
for the full description, features, specifications and reviews. Long original
titles can be expanded. The first view no longer repeats a long description
or presents unknown price and stock as purchase controls. Gallery selection,
full-text expansion and the original listing link were checked. Desktop and
narrow layouts were inspected in the browser.

Ask Mosaic starters and saved category links translate the old workshop
category names to the real catalog's category keys. Selecting a starter resets
pagination. The observed failure was an old `over-ear-headphones` filter on
page four returning zero products; the corrected request uses `headphones`
and resets to page one. Recommendation cards preserve the original titles
behind a compact preview and link to the original listing.

## Live retrieval and agent checks

| Check | Observed result |
| --- | --- |
| Exact listing search, `B0939N79Y8` | Correct Dell product 1408222 and original listing identity. |
| Production SQL plan for that search | HTTP 200; plan includes `real_search_vector_idx`. Event `0f6bf71b-23dc-4738-8d23-2aa640f9a6c9`. This is a functional check, not a latency benchmark. |
| Bose specifications and reviews | Grounded response for product 1277987 with specification 531166 and customer review 531169. Run `d2141178-f86f-45fa-9e1b-918f8e4e49c8`. |
| Follow-up asking about call quality | HTTP 200, 28.12 seconds, same product and fresh evidence. It distinguishes the specification's microphone claim from a review that discusses listening quality and does not establish call performance. Run `0bcb42e3-108c-4ffa-bb8b-9fd66af2c9cb`. |
| Clearer calls starter in the browser | Completed with a boom-microphone headset and a listening-noise-cancellation alternative. The answer explains which listing addresses what the other caller hears and cites both specification records. |

Multi-topic evidence questions can otherwise miss a review when full-text
search requires every term in the same passage. For a real product with no
review hit and room in the evidence limit, the same production evidence
function now searches individual query terms within that product's customer
reviews. It preserves the original review and variant identity and does not
treat a partial topic match as proof of every requested claim.

Old product scopes fail closed after a catalog change. Original titles longer
than 300 characters and records without model names can be carried into a
follow-up; the server still compares those identities with its saved answer.
Plan capture also rejects a receipt from a different catalog hash.

## Validation and remaining work

- Full UI run: 681 tests passed across 64 files. The production build passed;
  the existing large HNSW visualization chunk warning remains. After the final
  recommendation-card polish, the affected 69 tests and the build passed again.
- Full offline Python run: 1,383 passed, 59 skipped, **two failed**. Both failures
  are the committed scorecard's attribution checks, because its measured
  baseline predates these retrieval changes. The old scores were not relabeled
  or edited to claim a result for the new catalog.
- Configuration tripwire and retrieval-profile checks passed. Targeted lint
  passed. Regression coverage includes source-byte/photo changes, scope
  substitution, stale catalog receipts, source titles without a model name,
  review fallback and both fusion orders using the same selected corpus.

Still required for release: measure and judge replacement lab/evaluation
queries on this corpus; prove the intentional failures and repairs; refresh
the scorecard and exact-neighbor references; validate the Scale & HNSW paths;
update the dependent deck/video and workshop pin after the source revision is
reviewed. Historical measurements remain historical. Workshop Studio was not
published in this pass. Fresh-account rehearsal remains excluded from this
work and required before the event.

Detailed local receipts are under `.local/real-products/catalog-500k/`:
`live-preparation-report.json`, `live-readiness-after-ui-fixes.json`,
`live-plan-cutover-proof.json`, `agent-review-cutover-proof.json`,
`agent-followup-cutover-proof.json`, `python-validation.log` and
`ui-validation.log`. They are local verification artifacts, not published
release evidence.
