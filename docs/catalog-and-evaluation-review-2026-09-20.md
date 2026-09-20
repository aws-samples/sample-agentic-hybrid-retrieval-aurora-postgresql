# Catalog and evaluation review

This review extends `docs/release-readiness-2026-09-19.md`. Its earlier release
measurements do not establish the result of this catalog change. The current
source changes and new measurements must travel together.

## Why keep the evaluation queries?

Use them as repair checks within the existing Retrieve → Rank → Reason story:

1. Did a known suitable product enter the results after the retrieval repair?
2. Did fusion use each search method's actual position, even if reranking hides
   the defect in the final order?
3. Do the recommendation's claims have supporting product or review records?

Keep the request and filters unchanged during each before/after comparison.
The broader 720 generated cases belong in maintainer validation. They check
product existence and exact filter eligibility, not natural-language quality.
The 20 graded searches cover selected regressions; they do not represent
customer traffic or judge all 500,000 products. The agent case remains a
separate Lab 3 check. Production work needs independent requests and held-out
judgments before making broader quality claims.

## Confirmed defects and corrections

The audit scanned every product for identity, required fields, category-specific
specifications, description/offer agreement, source projections and embedding
coverage. It separately inspected image bindings and the available photograph
set. It did not manually certify 500,000 fictional products or real retail
performance.

- Replaced specifications drawn from the wrong product category. Examples include
  mesh chairs with networking fields, monitor arms with screen resolutions,
  desk lamps with desk load capacities and camera lenses with camera-body fields.
- Corrected oversized portable-display descriptions, mechanical-keyboard switch
  contradictions, headphone form factors, fixed-height desk categories and
  non-plated shoe categories. Product identities, prices and stock stay intact.
- Removed authoring instructions from product descriptions, repaired malformed
  singular names and aligned warranty fields with their existing descriptions.
- Removed a webcam certification attribute contradicted by its own description.
  The corresponding check now asks for observable listed features.
- Corrected review-source drift: the source contains 504 replacement review
  excerpts that the running database had not received. Retired rows retain
  their evidence IDs and original text for saved citations; current search and
  product reviews exclude them.
- Replaced the portable-monitor photograph with a folding-cover portable screen.
  Removed unrelated-category image fallbacks and labeled representative category
  photography. A category photograph is not evidence of a SKU's exact appearance.
- Corrected relevance judgments: several ANC headphones suit the broad typo
  request; a scissor-switch keyboard is a partial match for a mechanical request;
  a ten-hour chair recommendation falls short of an explicit twelve-hour request.
  Unrequested armrest features and price no longer justify those chair grades.
- Made all 720 generated query descriptions express their actual filter values,
  including false booleans and exact numeric equality. Corrected 15 impossible or
  mismatched targets. Watch battery language now specifies smartwatch mode.

## Data-change boundary

The reviewed bundle contains 412,211 changed source records. Of these, 70,665
change production search text and require new Cohere Embed v4 vectors; 341,546
change only the warranty offer. Warranty changes total 361,268 because some also
have text corrections. These counts overlap only where explicitly stated.

The replacement vectors use the exact text produced by the production Aurora
projection, the pinned `us.cohere.embed-v4:0` model, `search_document` input type
and 1,024 dimensions. Image-only edits do not require new vectors in this
text-only pipeline. Completed batches are reused after transient throttling.

The promotion script validates the old source and vector hashes, completes a
recovery backup, then installs product text, offers, search projections, vectors
and supporting evidence in one transaction. It refuses drift or incomplete
vectors. The source bundle and cached restore assets are updated only after
that transaction commits.

Scores from before and after this revision are not a controlled comparison of
the retrieval algorithm: the catalog, some queries and relevance judgments all
changed. Inspect per-query orderings and the committed measurement identity.

## Delivery boundaries

Source commit/push and local Workshop Studio preparation are authorized.
Workshop Studio S3 uploads, staging, commits, pushes and publication remain
PENDING USER ACTION. The human fresh-environment rehearsal is EXCLUDED from
this pass and is still required. Native Studio rendering and new-host lifecycle
proof retain the separate blockers documented in the release-readiness report.

## Image coverage

The initial resolver audit covered all 500,000 products: 200 have product-bound
photographs and the remainder use shared category photography or a missing-photo
backdrop. All 337 referenced image files existed. The 200 bound images, 134
category plates and three fallback images were visually inspected. A replacement
portable-monitor photo and an empty fallback backdrop were generated and their
runtime checksums recorded. Three fallback filenames share the empty backdrop.

This is not a catalog of 500,000 distinct product photographs. Shared photography
is labeled “Category image”; missing photographs are labeled “Photo unavailable.”
The displayed image stays stable between search, comparison and recommendations.

## Completed catalog proof

The Aurora promotion committed all 70,665 text/vector pairs, 361,268 warranty
changes and 70,665 specification records. There are 15,000 current review
excerpts; 504 superseded excerpts remain accessible by their original IDs.

- All 500,000 source identities, content hashes, short descriptions, categories,
  prices, stock and warranties agree with Aurora after applying the production
  availability-name mapping.
- Every cached vector agrees byte for byte with Aurora, and every cached content
  hash agrees with its product. There are no missing, zero or wrong-model vectors.
- All six projection comparisons pass: title, summary, attributes, body, offer
  and exact embedding input text.
- The 720 generated filter checks and 74 graded product judgments pass the
  production `matches_filters` function. This proves eligibility, not ranking
  quality.
- Labs 1 and 2 detect their deliberately broken production functions and pass
  after repair. Their probe transactions were rolled back; source stayed intact.

The cache manifest is
`115da5ed3b932ffe84c7e1355a0c541e09bafa7ef56b096501a30308d59d0657`.
The matching cache is prepared locally in Workshop Studio. Its published copy
remains unchanged until the owner uploads the new assets.

The first large update was cancelled and rolled back because timestamp-only
changes incurred repeated maintenance of three HNSW indexes. The retry preserved
their exact definitions, removed the indexes concurrently, committed the catalog
transaction and rebuilt them concurrently. One half-vector index build reached
its reader-lock timeout and required recovery; its invalid state was not treated
as ready. Recovery verified all three indexes as valid and ready before the
new retrieval measurements. The updated exact-search reference covers all 180
anchor/filter pairs.

The 12 vocabulary controls were remeasured against the corrected corpus. Their
queries, expected decisions and similarity threshold remain unchanged; obsolete
term counts and nearest-spelling observations were replaced with live results.
The new measurement command refuses changed expectations or an empty case set.

## Acceptance matrix

This extends the previous release matrix; publication and fresh-environment
proof remain separate from these existing-cluster checks.

| Area | Status | Evidence and boundary |
|---|---|---|
| Complete catalog and restore cache | PASS | 500,000 source records and cached vectors agree with Aurora; zero projection mismatches |
| Generated and graded filter targets | PASS | 720 generated targets and 74 graded judgments use production SQL filters |
| Catalog diagnostics and packaging | PASS | Source and database packages validate; category repair, cache and identity checks pass |
| Aurora integration | PASS | 51 contract tests and 109 model/integration tests; all three production lab validators pass |
| Deliberate failure and repair | PASS | Labs 1 and 2 tested in rolled-back production-function transactions; isolated Lab 3 defect rejected, healthy API passes |
| Search-index recovery | PASS | All three HNSW indexes valid and ready; 180 exact-search reference pairs refreshed |
| App interface | PASS | 653 UI tests, separate TypeScript checks and production build; laptop and narrow Alex brief inspected |
| Images | PASS | All 337 assets inspected; replacements, labels, bindings and checksums checked; shared images are explicitly illustrative |
| Deck and speaker narrative | PASS | Twelve-slide PowerPoint/PDF and notes synchronized; exported layout and media package checked |
| Native PowerPoint autoplay | BLOCKED | Native app was being used for another presentation; package timing is verified, native playback is not |
| Saved quality and performance measurements | BLOCKED | Require fresh measurements from the clean source commit after this catalog repair; earlier numbers do not certify this revision |
| Published Studio rendering and new-host lifecycle | BLOCKED | Existing release report's publication/access boundary remains; no fresh deployment is claimed |
| Human fresh-event rehearsal | EXCLUDED | Explicitly outside this pass and still required before event delivery |

Workshop Studio uploads, git staging/commit/push and publication remain
**PENDING USER ACTION**, including the changed embedding cache. No Studio upload
or publication was performed by this review.

## Alex's brief

Discover, the profile card, the presentation bio and the deck use the same
headphones → chair → monitor sequence. His desk and laptop are already in place.
The quote is: “I've got the desk and the laptop. Now I need a setup I can actually
work in, every day.” The monitor need explicitly explains code and documentation
side by side without constant tab-switching. This changes the introduction, not
the separate required Lab 3 exercise.
