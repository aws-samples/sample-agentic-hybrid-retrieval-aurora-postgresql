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
- Preserved units in product specifications and the Ask Mosaic product drawer:
  screen size, refresh rate, weight, power, duration and gamut coverage use the
  same formatter as the summary facts. False attributes display as “No.”

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
The old upper spelling control, “enough,” now matches a catalog word directly.
Its former similarity interval is no longer claimed as current calibration.
The interval check uses “hedfones” from the existing required positive case and
the existing unknown-brand negative. Permanent tests reject thresholds on either
side of that observed interval; no production threshold was changed.

## Refreshed measurements

The HNSW run measured 30 anchors across three domains, six filter presets and
three vector representations on the existing Aurora PostgreSQL 18.3
`db.r8g.2xlarge` instance. The run records pgvector 0.8.1, all query samples,
index definitions and sizes, plans, source revision and dataset hash. At
`ef_search = 100`, mean exact-neighbor recall was 0.8533 and warmed server p50
was 1.914 ms. At 800, the measured values were 0.9867 and 7.824 ms. These are
sequential existing-instance measurements, not cold-cache or concurrent-load
claims. The optional scale projection was regenerated from this measurement;
larger scales remain estimates, not measured capacity.

The 20-query reviewed set was measured again through the production retrieval
and reranking path. Its required identity, negative-attribute and sibling-order
controls passed. The stage comparison retains per-query results and the limit
imposed by products absent from the retrieved set. Broad headphone requests
remain among the weakest reviewed cases. No judgments were changed to improve
these measurements, and no claim of complete catalog relevance is made.
The refreshed reranking comparison improved five searches, worsened five and
left ten unchanged. The old test claiming that more than half were unchanged
was replaced with these exact observed counts; the paired-comparison rule was
not changed.

The current committed files are the authoritative numbers:

- `data/evals/canonical_scorecard.json` and `canonical_ranked_results.csv`;
- `data/evals/canonical_stage_ablation.json`, including per-search differences;
- `data/benchmarks/hnsw_measured.json` and its complete samples file; and
- `data/benchmarks/scale_projection.json`, explicitly labeled as a projection.

The final quality measurement is captured from a clean committed source after
this report. Only generated scorecard, ranked-result and stage-comparison files
may follow it; the existing release check enforces that boundary.

## Acceptance matrix

This extends the previous release matrix; publication and fresh-environment
proof remain separate from these existing-cluster checks.

| Area | Status | Evidence and boundary |
|---|---|---|
| Complete catalog and restore cache | PASS | 500,000 source records and cached vectors agree with Aurora; zero projection mismatches |
| Generated and graded filter targets | PASS | 720 generated targets and 74 graded judgments use production SQL filters |
| Catalog diagnostics and packaging | PASS | Source and database packages validate; category repair, cache and identity checks pass |
| Offline source checks | PASS | Python suite and affected regression checks, Ruff, retrieval configuration/profile checks and package checks; live Aurora lanes are reported separately |
| Aurora integration | PASS | 51 contract tests and 109 model/integration tests; all three production lab validators pass |
| Deliberate failure and repair | PASS | Labs 1 and 2 tested in rolled-back production-function transactions; isolated Lab 3 defect rejected, healthy API passes |
| Search-index recovery | PASS | All three HNSW indexes valid and ready; 180 exact-search reference pairs refreshed |
| App interface | PASS | 653 UI tests, separate TypeScript checks and production build; laptop and narrow Alex brief inspected |
| Images | PASS | All 337 assets inspected; replacements, labels, bindings and checksums checked; shared images are explicitly illustrative |
| Deck and speaker narrative | PASS | Twelve-slide PowerPoint/PDF and notes synchronized; exported layout and media package checked |
| Native PowerPoint autoplay | BLOCKED | Native app was being used for another presentation; package timing is verified, native playback is not |
| Saved quality and performance measurements | PASS | Fresh clean-source Aurora runs, all required quality controls, complete HNSW samples and regenerated estimates; limited-query quality and warmed sequential performance only |
| Local Workshop Studio static checks | PASS | Four CloudFormation templates, shellcheck and 126 guide/bootstrap regression tests; source parity and final pin are checked again after source publication |
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

## Release handoff

Publish the source `main` branch with the configured Git identity, independently
compare its full SHA with `origin/main`, then use Studio's `scripts/repin.py` to
prepare the local package. Its source pin must be that published SHA; the tool
also updates the derived infrastructure revision and bootstrap checksum. The
final identity and local validation receipt are supplied with the delivery.

The exact manual commands and explicit staging list in
`docs/release-readiness-2026-09-19.md`, under “Maintainer-only release commands,”
still apply. The essential additional change is the new 51-object embedding
cache: upload the verified local cache with the four named runtime assets before
publishing the newly pinned Studio package. The new manifest checksum is shown
above. The old remote cache cannot bootstrap the corrected source catalog.
Do not add deletion flags or stage the large cache files in Git.

After the owner's upload and publication, repeat published asset checksums,
native Studio rendering and automated new-host bootstrap/lifecycle checks.
The combined delivery gate continues to reject the intentionally uncommitted
Studio checkout until the owner commits it. Native PowerPoint playback also
remains unverified; the deck's embedded media and automatic-start timing were
checked structurally. The video preserves its original Aurora app frames and
does not claim to be a fresh capture of this catalog revision.

The separate human rehearsal must still cover a timed fresh bootstrap, model
access, all three broken-to-repaired labs, saved completion, participant recovery,
presentation playback and teardown. It is excluded here, not waived.
