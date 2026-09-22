# DAT409 examples: what to reuse for DAT410

Keep DAT410's three required repairs and the home-office story. Reuse DAT409's
way of showing a request, visibly different products and the search pipeline.
The reviewed DAT409 materials do not establish a stronger replacement exercise
than the production before/after runs already captured for DAT410.

## Materials inspected and limits

- **DAT409-R1 repaired presentation:** slide text, speaker notes and embedded
  product images; especially slides 2–6, 8–11 and 13–14.
- **Local source notebook:** `02-dat409-hybrid-search-SOLUTIONS.ipynb`, 33 cells,
  with no saved execution outputs. Cell numbers below are zero-based.
- **Workshop Studio guides:** business challenge, hybrid-search lab, optional
  demo and quick reference in the local DAT409 delivery repository. Its README
  still describes an incident-search story, so the product lab and notebook are
  the relevant evidence for this review.
- **Current DAT410:** the mission manifest, participant guides, reviewed product
  comparisons and [September 22 production receipts](evidence/reviewed-exercises-2026-09-22.json).

The DAT409 Aurora environment was not rerun. An older WorkDocs notebook could
not be read because its file handle was stale; the accessible source notebook
was inspected instead. Expected outcomes and slide scores are not treated as
measured results without matching execution evidence.

## Reuse decisions

| DAT409 element | Decision for DAT410 |
|---|---|
| One request compared across search methods | Reuse the teaching format. Keep the same request and filters, then inspect which search found the product and whether it reached the combined list. DAT410 already exposes these signals. |
| Product photos before mechanism diagrams | Reuse. Introduce the reviewed headphones/adapter distinction before explaining why a related item can be the wrong product type. Keep this an evidence comparison, not a claimed broken search or fourth repair. |
| Small score-versus-position table, slide 11 | Reuse the structure with the saved DAT410 values. Walk one product through its source positions, RRF contributions, combined position and final position. Do not compare a fusion score numerically with a rerank score. |
| Purpose-first requests such as keeping coffee hot | Reuse the phrasing approach in Alex's introduction: calls, adjustable support and code beside documents. Coffee and cooking examples add a new shopping story without improving the three core repairs. |
| Optional rerank toggle and visible SQL | Reuse as inspection, with actual timings and results. Explain that reranking only sees the products passed to it; it cannot recover an omitted product. |
| Persona/RLS/MCP demonstration | Keep outside the required hour. It changes the problem from retrieval quality to access and agent infrastructure, and the current workshop explicitly retires that extension. |

## Why not bring back the backpack example?

Slide 2's notes say a rain cover may be the better answer to a request for a
waterproof hiking backpack. Slide 6 then says the backpack is the primary answer
and the rain cover is secondary. That changes the success criterion while the
request stays the same.

Slide 3 rejects a daypack and waist bag using capacity and weather-protection
claims that the pictures alone cannot establish. The silhouettes are easy to
distinguish, but the evidence behind the decision needs more work. DAT410's
reviewed product-versus-accessory comparison retains that visual clarity while
showing the original text and listing links.

## Code and claims to leave behind

The old notebook is useful teaching material, not code to transplant:

- Cell 19 accepts `k` but hard-codes 60 in SQL, substitutes rank 1000 for missing
  matches, and combines only semantic and keyword lists. Copying it would also
  omit the spelling channel used by DAT410's first repair.
- Budget examples such as a chair under a stated dollar amount do not translate
  that requirement into a price predicate in the reviewed search functions.
  Current historical/missing price data does not justify making these the main
  workshop examples.
- Search functions truncate descriptions to 200 characters before cell 22 sends
  them to reranking. A decisive specification could be outside that excerpt.
- The keyword function builds `to_tsquery` input by joining raw words with `&`.
  PostgreSQL provides parsers for unformatted user input; retain the current
  application path rather than copying this shortcut.
- Claims such as universal HNSW speedups, fixed reranking accuracy gains and
  tuning-free RRF need qualification and measurements. A high model score does
  not certify that every requested feature is present.

Technical references: [PostgreSQL query parsing and ranking](https://www.postgresql.org/docs/current/textsearch-controls.html),
[pg_trgm](https://www.postgresql.org/docs/current/pgtrgm.html) and
[pgvector search and recall guidance](https://github.com/pgvector/pgvector).

## The connected story to present

1. **Headphones — find the intended product.** Alex saved a specific Bose
   listing. Related headphones cannot replace an exact-product lookup. Keep
   the transposed identifier as the short, measurable diagnostic input; show
   the product name and photo prominently so participants do not have to read
   an identifier as the story.
2. **Monitor — preserve the option that meets the stated need.** Explain the
   one-cable screen-and-charging requirement before showing the numeric query.
   The reviewed Dell record states the requested power delivery. A competing
   record's missing wattage is an unknown, not proof that it cannot charge.
3. **Chair and monitor — make a supported decision.** Check the wheeled chair's
   stated adjustments and the monitor's specifications, attach their sources,
   and say what remains unknown about comfort and laptop compatibility. Return
   to Alex's room to close the story.

The current receipts show the missing Bose listing recovered, the Dell admitted
to reranking and placed first, and the unsupported-answer failure repaired into
an answer with resolvable sources. The broader ESCI chair and monitor misses
remain disclosed; they do not become successful repair demonstrations merely
because the source comparisons are clear.

The remaining improvement is presentation: lead with the visible distinction,
then show the code and measured change. Keep the existing lab timing and three
deliberate faults. This review does not change the deck, catalog, embeddings,
mission contract or publication status.
