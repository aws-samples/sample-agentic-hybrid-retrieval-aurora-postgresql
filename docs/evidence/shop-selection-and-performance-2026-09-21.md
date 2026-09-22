# Shop selection and browsing performance

## Scope and result

The local storefront uses `reviews-2023-500k-v1` in Aurora. The Workspace edit
previously contained **70** records: 23 headphones, 23 chairs and 24 monitors.
Some were exercise examples; the rest came from the earlier visual sample.
Those sample choices were ordered by an identity hash, not by teaching value.

It now contains **120 distinct source products: 40 headphones, 40 chairs and
40 monitors**. The existing 12-product page size gives exactly **10 pages**,
with four of each category per unfiltered Featured page. The order alternates
headphone, chair, monitor. The opening examples appear first within each category;
the remaining positions prioritize source coverage and variety. Highest rated
and filtered views use their requested order instead.

All products and search still use the full 500,000-record catalog. This edit
changes browsing order, not retrieval scores or exercise assertions. Original
records, photos, rating aggregates, listing links and saved embeddings were not
modified. No embedding regeneration was required. Accessories and other useful
negative controls remain available in the full catalog.

## Selection review

The review used 5,829 records from the three relevant source categories, read
from the prepared Aurora catalog. Every input record was checked against its
original-record hash and embedding-input hash before selection.

The selection requires an identifiable brand, a matching original primary photo,
at least two feature bullets, at least three specification fields and at least
two relevant topics to inspect. General additions have at least 25 historical
ratings and an average of at least 3.8. The explicitly reviewed opening examples
may have fewer ratings or a lower average: the Dell U2720Q variant has six ratings,
and the BenQ PD2710QC has a 3.4 average. They are useful specification comparisons,
not endorsements based on rating strength.

The review removes accessories, sleep headphones, children's models, novelty
chairs, portable displays, obvious taxonomy errors, repeated colour variants,
renewed listings and products explicitly marked discontinued from the featured
edit. Monitor records dated before 2014 are also excluded from this edit.
Repeated brands, model identifiers and primary photos are limited. All selected
titles were inspected; the complete original descriptions remain accessible.

The former Steelcase Gesture opening record has no feature bullets and only one
historical rating. It remains searchable but is not used as a featured example.
Nouhaus Ergo3D provides more text to inspect. Its listing uses both “3D” and “4D”
wording: use its explicit adjustment descriptions, without resolving that
inconsistency into a stronger claim. Source text is evidence to inspect, not a
guarantee that every manufacturer claim is correct.

### Opening comparisons

| Category | First four source products | What builders can inspect |
| --- | --- | --- |
| Headphones | Bose QC35 II; Soundcore Life Q30; Sony WH-1000XM5; Sennheiser HD 599 | Listening noise control, microphone/call descriptions, wireless versus wired/open-back designs, and what the listing leaves unspecified. |
| Chairs | Nouhaus Ergo3D; Amazon Basics ergonomic mesh chair; FelixKing office chair; Mimoglad office chair | Which adjustments are actually described: seat height, arm movement, back support and recline. A flip-up arm is not automatically a height-adjustable arm. |
| Monitors | Dell U2720Q; Dell SE2717H; BenQ PD2710QC; LG 27UN850-W | 4K versus 1080p versus 1440p, screen size, and whether USB-C video and power delivery are explicitly supported. |

Topic keywords in the selection manifest identify reading material; they are not
new product attributes or proof that a feature is present. Historical rating
aggregates are available for every selected record. Imported review **text** is
still a separately sampled subset; this pass did not imply full review coverage
or claim that 120 new exercise cases passed a retrieval evaluation.

The selection is reproducible with `scripts/curate_shop_collection.py`. Its
`--check` mode compares the generated result with `data/real-shop-collection.json`.
The manifest records each selected source hash, embedding-input hash and reading
topics. Final manifest SHA-256:

`63c386ed7115e4a23715d04f148a2f8fdd5563aa70996f1791fe26a14e1ab4aa`

## Performance changes

The category filter was evaluated across all 500,000 rows because PostgreSQL did
not inline the composite filter function into an index condition. A redundant
category equality now exposes the existing category index while retaining
`matches_filters` as the final eligibility check. The measured monitor count
dropped from approximately 6.2 seconds to 39 milliseconds at the SQL level.

Counts and the three filter menus now share one narrow materialized result,
rather than repeating the same filter scan four times. A bounded cache reuses
these statistics across pages for at most five minutes, keyed by catalog,
preparation receipt, complete filter JSON and selection. Every page still checks
the live preparation receipt before using it.

Featured ordering in All products now combines two disjoint, bounded lists:
featured identities in their declared order, followed by the remaining products
in ID order. This preserves the original ordering while avoiding a full-corpus
sort for every page. Source hydration explicitly selects the original record and
verification fields; it no longer retrieves vectors that browsing does not use.

The browser reuses up to 32 recently visited browse pages for 60 seconds and
prefetches the next page's data, except when the browser requests reduced data
usage. Dataset, all filters, offset, size, sort and collection are separate cache
keys. Failed reads are retried. Search and lab-check requests are not cached by
this mechanism. The UI waits for catalog identity before making its initial
browse request, and page changes no longer blur the product grid. The original
photo host also receives an early connection hint.

An intermediate, non-shipped grouping query regressed to approximately 96 seconds
because the planner constructed the wide source row repeatedly. The final narrow
`MATERIALIZED` step prevents that expansion. The final timings below are from the
corrected query, not that rejected version.

### Local API measurements

These are wall-clock HTTP measurements from this laptop to the local API backed
by Aurora, not browser paint timings or a service-level guarantee. Photos load
separately from their original host.

| Request | Before | After |
| --- | ---: | ---: |
| Monitors, first page with uncached statistics | 30.472 s | 0.455 s |
| Monitors, next page | Not measured | 0.398 s |
| All 500,000 products, first page with uncached statistics | 32.011 s | 7.344 s |
| All products, next page | Not measured | 0.380 s |
| All products, after the 120 featured records | Not measured | 0.343 s |
| Workspace edit, warm pages | 0.554–1.953 s in the initial sample | 0.327–0.477 s |

The final ten-page Workspace sweep had a median of 0.350 seconds. Its first two
requests took 1.405 and 2.626 seconds; they are retained in the measurement record,
not discarded as outliers. The first uncached All products request remains slower
because it computes exact filtered counts and menus over the entire catalog.

## Verification

- All ten pages returned exactly 12 source products, in manifest order, with no
  duplicate identity across pages and four records of each category per page.
- All 120 primary photo URLs returned HTTP 200 with an image content type.
- Source hashes and embedding-input hashes were verified during selection.
- Fourteen live comparisons covered Featured and Highest rated ordering with
  empty filters, category, case-insensitive brand, rating, exact attributes,
  combined filters and an empty result. API identities and counts matched the
  production predicate and original sort expressions.
- All products reported 500,000 records. Its first page matched the featured
  opening; the first page after the featured group contained no featured IDs.
- 33 focused Python tests passed. 70 catalog/cache UI tests and 59 related
  product, Discover, walkthrough, shell and routing tests passed. The production
  UI build and configuration tripwire passed.
- The curation check was falsified by omitting a selected product in a temporary
  manifest. It rejected the omission and passed after a byte-identical restore.
  Permanent tests cover source tampering, bad category fits, missing opening
  records, balanced identities, cache separation, expiry, errors and reuse.
- Browser inspection confirmed the first-page order, 120-record count, ten-page
  navigation, original listing links, image presentation and Next/Previous
  behavior.

Raw local receipts are in `.local/real-products/catalog-500k/`:
`shop-browse-performance.json`, `shop-photo-check.json` and the verified
`shop-candidates.jsonl.gz` input. They are local diagnostic inputs and outputs,
not redistributed product data.

This change is active in the local app at port 5186 with its API at port 8010.
It has not been committed, pushed or published to Workshop Studio. This check
does not replace the separate live exercise/scorecard work or the excluded
fresh-account workshop rehearsal.
