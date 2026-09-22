# Real-product catalog assessment

Status, September 22, 2026: the local app and required labs serve the selected
500,000 Amazon Reviews 2023 products through `reviews-2023-500k-v1`. Source text
and saved Cohere Embed v4 input hashes agree; the vectors were reused. The old
synthetic catalog remains separately for historical checks and optional benchmarks.
The earlier staging-only status below has been superseded by this activation.

The local delivery bundle pins all selected records, 9,496 saved embedding
batches and 32 verified review excerpts. It is excluded from Git. Public
redistribution clearance remains unresolved; preparing a bundle is not clearance
to publish it. Source, local lab validation, public asset delivery and fresh-account
rehearsal are separate claims. See `docs/evidence/` for dated, model-specific lab
results; the old synthetic scorecard does not certify this catalog.

## What is available

| Source | Evidence examined | Fit for this workshop |
| --- | --- | --- |
| [Kaggle Amazon Products 2023](https://www.kaggle.com/datasets/asaniczka/amazon-products-dataset-2023-1-4m-products) | Complete version 17 archive: 1,426,337 rows and distinct ASINs, 248 categories. Includes 9,242 entries classified as Headphones & Earbuds and 3,584 as Computer Monitors. Titles, image links, rating/review counts and historical pricing; no description, detailed specification, review-text or relevance-label columns. Listed license: ODC-By. | Useful storefront enrichment and a possible source of scale. Exact ASIN matching finds 127,700 products in ESCI US; 126,802 have a description or listing highlights there. This join does not supply 500,000 products with richer text. ODC-By [separates database rights from rights to individual content](https://opendatacommons.org/licenses/by/1-0/), so it does not independently settle photo redistribution. |
| [Amazon Shopping Queries / ESCI](https://github.com/amazon-science/esci-data) | Complete official product file: 1,814,924 distinct product-and-locale identities, including 1,215,854 US identities. Of the US records, 646,059 have descriptions and 1,037,077 have listing highlights. Apache-2.0 repository license. | A plausible base for 500,000 distinct US products with query relevance judgments. It supplies no photos, current prices or review text. Verify individual feature claims separately from relevance labels. |
| [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/) | Complete pinned metadata files, checked against their published SHA-256 hashes: 1,610,012 Electronics records and 710,503 Office Products records. Selected 400,000 and 100,000 distinct parent ASINs respectively. Every selected record has an original photo URL, substantive source text, an average rating and a rating count. | The selected bulk catalog uses this one source for text, specifications, rating aggregates and photo links. Metadata coverage does not certify every product claim or photo. The publisher [does not assign a dataset license](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1); public workshop redistribution remains unresolved. Aurora staging now also holds 32 source-verified reviews covering seven of the ten selected preview products. |
| [Amazon Berkeley Objects](https://amazon-berkeley-objects.s3.us-east-1.amazonaws.com/index.html) | Complete listings archive: 147,702 product-and-marketplace identities, 19,616 on amazon.com. The US title screen found 104 possible office-chair records; screened monitor titles were accessories, not display panels. | Useful furniture metadata and imagery; insufficient as the sole headphones/chairs/monitors catalog. The downloaded archive and current project site specify CC BY 4.0, while the [AWS registry](https://registry.opendata.aws/amazon-berkeley-objects/) still lists CC BY-NC 4.0. Retain the exact archive license when resolving distribution. |
| [Wayfair WANDS](https://github.com/wayfair/WANDS) | Official published counts: 42,994 products, 480 queries and 233,448 relevance labels. Structured feature strings and descriptions; no product images. Official repository license: MIT. Files not locally audited in this pass. | A stronger furniture relevance reference than anonymous Wayfair or Overstock scrapes. Useful for chair search; not the full electronics catalog. |
| [Shopping Queries Image Dataset](https://github.com/Crossing-Minds/shopping-queries-image-dataset) | Two official CSV maps downloaded. Six preview products matched directly to ESCI US product IDs. All six linked original photos loaded in the browser. | Useful visual companion to part of ESCI. An image URL and the map publisher's MIT label do not by themselves establish redistribution rights to every underlying photograph. Keep this preview local. Its product/query selections must be excluded from any later untouched evaluation set. |
| [Best Buy API](https://developer.bestbuy.com/legal) | Official terms reviewed; not downloaded. Current terms impose a 72-hour content-cache limit and branding conditions. | A poor default dependency for a frozen workshop bundle without an appropriate agreement. |
| [Home Depot relevance](https://www.kaggle.com/c/home-depot-product-search-relevance/data) | Competition description reviewed; files and accepted competition terms not obtained. | Different product domain; useful relevance research, not a source for this electronics story or its photos. |
| Other Walmart, Wayfair and Overstock scrapes | No specific release with both verified rights and stronger coverage established in this pass. | Do not infer source rights, quality or product truth from an uploader's license label. |

Counts from title screens identify listings to inspect; they are not confirmed
category counts. A relevance label is also not proof of a specific capability.
For example, the ESCI judgments include a 2560 × 1080 monitor marked relevant
to “4k monitor.” Preserve the original judgment and record a separate feature
check; do not rewrite the source label to improve the demonstration.

The Kaggle file is a different dataset from Amazon Reviews 2023. Its 11 product
columns are `asin`, `title`, `imgUrl`, `productURL`, `stars`, `reviews`,
`price`, `listPrice`, `category_id`, `isBestSeller` and `boughtInLastMonth`.
`reviews` is a count, not review text. Four of the six local preview products
also appear in this file; the preview itself still uses ESCI text and SQID photo
links. Historical prices or rating counts must not be presented as current.

## Scale and teaching value

The selected corpus contains **500,000 distinct parent ASINs** from one dataset,
Amazon Reviews 2023: 400,000 Electronics and 100,000 Office Products. ESCI,
Kaggle and ABO records are not mixed into that selection. Count products, not
reviews, images or duplicate marketplace listings. The six-product visual
prototype remains separate: it uses ESCI text and SQID photo links.

For context, [BEIR](https://github.com/beir-cellar/beir) includes TREC-COVID with
171,000 documents and MS MARCO with 8.84 million passages. Those are scale
references, not directly comparable product benchmarks. Half a million
1,024-dimensional float32 vectors contain 2.048 GB of raw vector values before
PostgreSQL row storage, indexes and metadata. This arithmetic is not a measured
Aurora capacity or latency claim.

The three exercises still need a small, reviewed set of examples inside that corpus:
headphones with confirmed cancellation and a microphone; chairs with the
adjustments requested; and monitors with the required display and connection
capabilities. Each example must fail through the actual broken production path
and pass after the intended repair. These six preview products demonstrate
visible feature differences only. No retrieval failure or recovery is claimed.

## Bulk import and verification

[`data/real-catalog-plan.json`](../data/real-catalog-plan.json) fixes the source
allocation, sampling seed and text bounds. Selection uses stable product-ID
hashes rather than source order. Records without a usable primary photo URL,
at least 160 characters of description or listing features, or valid field
types are excluded. Each original metadata object is retained unchanged; the
embedding text is a separate, hashed projection of its title, categories,
descriptions, features and specifications.

The selected file has SHA-256
`149563d3bc6b3b090bd49bb6c3eda583636d03aec5c9126add0df1a57447c9c6`.
Its 936,909,727 embedding-text characters are source text, not generated
descriptions. There are 399,163 primary high-resolution image URLs and 100,837
primary large-image URLs. These are source field classifications, not a claim
that all photographs have been downloaded or visually inspected.

The operator sequence uses the existing Python environment and Aurora
`DATABASE_URL`; it never starts a local database:

```sh
python scripts/fetch_catalog_metadata.py Electronics --destination .local/real-products/reviews-2023/full
python scripts/fetch_catalog_metadata.py Office_Products --destination .local/real-products/reviews-2023/full
python scripts/prepare_real_catalog.py --source-root .local/real-products/reviews-2023/full --output .local/real-products/catalog-500k
python scripts/embed_real_catalog.py --selection .local/real-products/catalog-500k --workers 4
python scripts/stage_real_catalog.py --selection .local/real-products/catalog-500k --dataset-id reviews-2023-500k-v1 --phase records
python scripts/stage_real_catalog.py --selection .local/real-products/catalog-500k --dataset-id reviews-2023-500k-v1 --phase embeddings
python scripts/stage_real_catalog.py --selection .local/real-products/catalog-500k --dataset-id reviews-2023-500k-v1 --phase verify --require-complete
```

### Generating embeddings efficiently

Embedding uses the production Cohere Embed v4 request format, `search_document`
inputs and the configured 1,024 dimensions. Each batch binds model settings,
product IDs and input-text hashes to verified vector bytes. Restarts reuse saved
batches; interrupted or retried remote calls may still incur charges. The job
paces requests below each source Region's applied quota and checks for applied
quota changes every five minutes. Requesting a higher quota does not activate it.

The generator groups inputs by both product count and text size, within the
[Cohere Embed v4 request limits](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-embed-v4.html).
Bounded concurrency overlaps remote requests without enqueueing the full
catalog in memory. Verified cache reuse avoids repeating successful requests;
atomic checkpoints preserve completed batches through restarts. These are
batched `InvokeModel` requests, not Amazon Bedrock Batch Inference jobs.

For more throughput, the operator can use the existing US inference profile
from three source Regions, subject to the account's permissions and applied
quotas in each Region:

```sh
python scripts/embed_real_catalog.py --selection .local/real-products/catalog-500k --workers 12 --regions us-east-1 us-east-2 us-west-2
```

[Bedrock's geographic inference quotas are per model, per source Region](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html).
Each Region gets its own paced client and 85 percent of its applied token
budget. `--tokens-per-minute`, when supplied, sets a fixed budget **per Region**.
Increasing workers alone does not increase that budget. Startup verifies that
every endpoint uses the same active model and US destinations. One writer owns
the cache, and existing batches retain their identities and vector bytes when
resumed from another Region. New batches record their request Region separately.
The progress report lists regional quotas individually; their sum is not a
quota-increase approval. Actual throughput still depends on available capacity.

Add `--adaptive-pacing` to learn token estimates from verified batches and new
responses. After eight usable observations, each Region uses a rolling sample
of 64 batches, a five-percent estimation margin, and the highest ratio among
the four most recent batches. Missing token counts do not train the estimate.
The applied-quota allocation remains unchanged at 85 percent. Admission also
checks a rolling token budget: unfinished requests retain their reservations,
completed responses replace estimates with actual usage, and reported retries
reserve additional capacity. Completed usage remains in the budget for 60
seconds after the response. Historic cache entries train the estimate without
counting as new model requests. Estimates can still differ from actual usage;
Bedrock enforces the quota and the SDK retains its retry behavior.

New checkpoints record request times and retry counts, and progress reports
show the pacing strategy and estimate per Region. Omit `--adaptive-pacing` to
return to the original conservative character estimate. Either mode preserves
the same batch identities, model, dimensions, source text, and saved vectors.

#### Observed preparation throughput

The September 21, 2026 build provides the following observations. Rates count
only newly saved embeddings; elapsed time includes startup cache checks. Both
runs resumed earlier work, and the three-Region run was still incomplete at
this snapshot.

| Build configuration | New embeddings saved | Elapsed seconds | New embeddings/hour |
| --- | ---: | ---: | ---: |
| One source Region, conservative pacing | 69,251 | 10,644 | 23,422 |
| Three source Regions, adaptive pacing, 12 workers | 127,081 | 5,739 | 79,716 |

The observations come from the last single-Region checkpoint in
`.local/real-products/catalog-500k/embedding-resume.log` and the adaptive
checkpoint with 436,190 total saved products in `embedding-adaptive.log`.
Rate is `newly_embedded / elapsed_seconds * 3600`, rounded to the nearest
whole embedding. The adaptive run reused 309,109 verified embeddings; those
are excluded from its generation rate.

This is about 3.4 times the earlier observed rate, not a controlled benchmark
of adaptive pacing alone. Regional capacity, concurrency and pacing changed
together, and the runs embedded different product texts. Each of the three
source Regions had an applied quota of 300,000 tokens/minute and a job budget
of 255,000; the summed job budget is not a single regional quota. Text length,
available capacity, retries and other account traffic affect achievable rates.

When tuning another build, watch newly saved embeddings per hour alongside
per-Region token usage, retry counts and request latency. Check request and
daily quotas as well as token-per-minute quotas, and allow for other workloads
sharing the same model quota. Saved-response token counts do not include every
potentially billable failed or interrupted call. Preserve input hashes and
embedding settings when comparing runs so performance tuning does not silently
change retrieval behavior.

### Loading into Aurora

[`scripts/stage_real_catalog.py`](../scripts/stage_real_catalog.py) is the
public-catalog loader used by the operator commands above. It streams product
records with `COPY`. For vectors, it verifies each saved cache batch and uses
binary `COPY` into an Aurora temporary table, followed by a set-based
`UPDATE ... FROM` that joins product IDs and input-text hashes. This avoids
issuing one update round trip per vector.

The vector loader accumulates several cache batches per bounded transaction,
analyzes the temporary table before the update, and commits the update and its
batch checkpoints together. It reads the existing checkpoint map once and
skips committed batches after validating their cache identities. An update
count mismatch rolls back the entire transaction, including its checkpoints.
These choices reduce round trips and commit overhead while preserving resume
integrity; they do not establish a particular rows-per-second rate.

Records and vectors have separate transactional checkpoints in
`mosaic_catalog_stage`. The loader requires an Aurora endpoint and an encrypted
connection, checks `aurora_version()` and the actual TLS connection, and never
writes the live `mosaic` or `mosaic_search` schemas. A partial vector import
remains explicitly incomplete. The completeness check requires every selected
product, the expected embedding model and dimensions, and matching input hashes.
This proves import integrity, not retrieval quality.

The final staging report at 15:58:50 UTC on September 21, 2026 records 500,000
products and 500,000 embeddings, complete record and embedding phases, no
incompatible embeddings, and no text-hash mismatches. Its
`ready_for_search_validation` value is true and `live_catalog_promoted` is
false. This report is `.local/real-products/catalog-500k/aurora-staging-report.json`;
its file modification time supplies the observation timestamp, not an import
duration. No end-to-end ingestion speedup is claimed from that timestamp.

For a fresh Workshop Studio Aurora cluster,
[`scripts/embedding_cache.py`](../scripts/embedding_cache.py) imports the pinned
workshop cache through the same binary-`COPY` and bulk-update pattern, with one
transaction per shard. That manifest-based cache and the refresh's batch cache
are different formats and require their corresponding loaders. The
[`db-bootstrap-cached` target](../Makefile) verifies the pinned cache before
database mutation, imports embeddings, then creates search indexes and runs
acceptance. Its timings separate `embedding_import` from `index_creation`;
report both when comparing complete restore times. Participants receive this
prepared database and do not run a second import during the labs.

Aggregate evidence is in
[`reviews-2023-selection.json`](evidence/catalog-source-audit/reviews-2023-selection.json).
That file retains the earlier selection snapshot; the completed import and
full-source identity audit are in
[`import-2026-09-21.json`](evidence/catalog-source-audit/import-2026-09-21.json).
Local progress and cache files remain under the ignored `.local/real-products/`
directory. No raw product objects, photographs, review text or credentials are
included in the source commit.

### Search preparation and first comparisons

[`prepare_staged_catalog_search.py`](../scripts/prepare_staged_catalog_search.py)
builds a separate `mosaic_catalog_search` projection from the verified import.
All 500,000 rows retain their original parent IDs, text hashes and vectors.
The full comparison found zero source or vector mismatches, and every index is
valid. The full-text, trigram and full-precision HNSW indexes occupy approximately
321 MiB, 190 MiB and 3.81 GiB respectively in this build. These are measured
sizes of the replacement indexes, not a comparison with `halfvec` or binary
representations. Those comparisons remain outstanding.

[`probe_staged_catalog_search.py`](../scripts/probe_staged_catalog_search.py)
runs the shipped SQL, fixed query embeddings and the configured reranker in the
isolated schema. Each broken lab state runs in a transaction that is rolled
back; the served search functions are not changed. Seven requests produced 21
observations across repaired search, disabled spelling search and incorrect RRF
arithmetic. All 350 repaired rows passed an independent RRF calculation; the
intentional ranking defect failed that calculation on 348 of 350 rows.

The existing `noice cancelng hedfones` request and a `Bose QuietComfrt 35` request
each retained the same leading three products when spelling search was disabled.
Neither is an accepted replacement Lab 1 demonstration. The monitor requirements
request changed its leading results with the ranking defect, but its product
features and participant-visible contrast still need independent review.

The first probe omitted the parent product ID from the text sent to the
reranker. For an exact `B0939N79Y8` request, the correct product moved from first
in repaired SQL retrieval to eighth after reranking. Including the preserved
parent ID before the unchanged source text kept that product first in all three
retested states. This correction changes the reranker input only; it does not
rewrite source records or regenerate embeddings. The original failed results
remain recorded. The other six requests have not been rerun with this correction.

The source audit also found one lowercase parent ID. The inspection API now
accepts it while retaining the source spelling; both unit checks and the running
local API confirm the exact source record can be read.

The aggregate search evidence is
[`search-validation-2026-09-21.json`](evidence/catalog-source-audit/search-validation-2026-09-21.json).
Single-run query times are observations, not latency benchmarks. The probe does
not exercise the Shop API, agent tools, exact-identity handling, source-feature
requirements or workshop assertions. A successful import and valid indexes do
not satisfy those remaining gates.

In Playground's **Scale & HNSW** view, **How this catalog was built** opens a
compact Generate, Verify, Load, Index explanation. It links to the scripts from
the current app build and the project repository. This is optional preparation
context; participants do not regenerate or reload the catalog during the labs.

## Ratings and review evidence

All 500,000 selected records contain numeric `average_rating` and `rating_number`
fields. The observed averages are within 1–5 stars and every count is positive.
These are the source's historical product-page aggregates. They can be displayed
without importing review text, and must not be presented as current live values.
`rating_number` is a count of ratings, not a count of locally available written
reviews.

Aurora staging now holds a bounded sample of 32 original reviews for seven of
the ten selected preview products. The importer preserves text, rating, date,
helpful-vote count, verified-purchase flag and both parent and variant ASINs.
It joins by exact parent ASIN and retains nine distinct reviewed variants.
Eight reviews are explicitly not verified purchases in the source. Review text
can describe comfort, calls, glare or everyday use; one variant's experience
does not establish another variant's specifications.

Keep reviews as separately retrievable evidence with their own input hashes and
citations. Do not append them to every product embedding or regenerate the
existing product vectors. Do not recalculate the overall star rating from the
selected reviews, represent their selection as an unbiased customer survey, or
let an anecdote override a documented hardware specification. Attribute claims
to the review and expose contradictory or missing evidence.

The two pinned review files total 28,393,026,486 bytes before local compression.
The sampler streams and discards bulk bytes, keeping only selected records and
range receipts. The current prefixes cover 1,375,695,946 Electronics bytes and
838,844,529 Office Products bytes. Selection retains helpful positive, mixed and
critical reviews where found; it is not a representative survey or a complete
source scan. Each retained JSONL record was independently fetched again from
its pinned URL and byte offset before import. No full-file hash verification
is claimed for these partial scans.

Steelcase Gesture, the renewed LG monitor and Dell U2720Q-Black have no imported
reviews in this sample. That is a coverage gap, not evidence that no reviews
exist. Review retrieval by a source citation is wired; semantic review search
and agent use of the replacement catalog remain pending.

## Product and evidence wiring

`service/source_catalog.py` projects the preserved source into explicit fields.
The production projection passed across all 500,000 selected products: 211,711
have an exact historical price, 78 have a qualified starting price, and 288,211
have no reported price. Current price and availability remain unknown. A source
rating aggregate is never recomputed from the review sample. Product photos
must match the primary photo URL preserved in that product's source record.

Set `MOSAIC_STAGED_CATALOG_DATASET=reviews-2023-500k-v1` on the development API to
enable `/api/catalog-staging`. Its examples, product and evidence endpoints read
Aurora staging. Evidence citations must name the exact parent product and a
record in the current selected review sample; another product's citation returns
404. Specification evidence reuses the hashed product text without duplicating
the catalog or regenerating its vectors. The UI preserves the raw evidence at
the source link and renders review line breaks as plain text.

The preview's **Product details and source** section reads these endpoints for
selected catalog products. Shop, comparison tools and the agent still use the
existing live catalog. They have not been switched to staged products. The
next migration must preserve one identity across all three and validate new
lab targets against Aurora before promotion. See the aggregate
[source-wiring proof](evidence/catalog-source-audit/staged-source-2026-09-20.json).

## Optional index comparison after embedding

The [AWS binary quantization walkthrough](https://aws.amazon.com/blogs/database/scale-pgvector-with-binary-quantization-on-amazon-aurora-postgresql/)
provides a useful measurement method: compare full, half and binary indexes
against exact nearest neighbors on the same vectors, then measure recall and
latency including any full-precision rescore. Mosaic already has these index
forms in `db/sql/19_indexes_quantized.sql`. Deriving them does not require a
new embedding run.

Full-precision vector rescoring is different from the model-based reranking in
the workshop. Keep those stages distinct. The article's text and image benchmark
corpora are not substitutes for this product catalog. Its published performance
and this repository's older measurements do not establish results for the new
selection. Use identical filters and request limits, record index sizes, and
run the actual new corpus before making a claim.

## Preserve the source, improve the presentation

- Retain source-native IDs, source revision, original title, description, listing
  highlights, specifications, image URL and content hashes. Parent ASINs from
  Reviews 2023 are not interchangeable with ESCI variant ASINs.
- Store display names, summaries and normalized specifications separately.
  Keep evidence for each normalized fact. Unreported features remain unknown;
  they must not silently become false.
- Prefer a higher-resolution original image of the exact product and variant.
  Keep the complete product visible. Preserve originals if a display derivative
  is made; do not generate ports, controls, materials, accessories or other
  features that the original does not establish.
- The local preview contains 16 examples: the original six ESCI examples with
  SQID image links, plus ten products verified in the selected Reviews 2023
  corpus. The original six photographs were checked at 1,200 to 2,560 pixels
  on their longest side. This resolution check does not cover every new photo.
  No product photo is AI-generated or replaced with a different product.
  Original title, description and highlights remain separate from display copy.
- The original six retain their exact variant identities and specification
  links. Five still need verified mappings to Reviews 2023 parent products;
  one exact parent was found in the full metadata but was not selected in the
  initial sample. Their inclusion in the preview does not mean all six are
  already part of the 500,000 selected records. The ten selected examples
  show historical ratings from their own source records. See
  `data/real-catalog-examples.json` for identities and evidence status.
- The selected Dell U2720Q-Black parent `B0939N79Y8` supplies the positive
  monitor comparison: the record documents a 27-inch 4K display, USB-C video
  and power delivery up to 90 W. Its source and embedding-text hashes were
  verified against the unchanged selection; its original image loaded at
  1500 × 1140. This addition changes the preview, not the selection or vectors.
  The original Dell preview identity remains a separate, unselected record.
- Product photos use a clean background with no added warm-light effect.
  No replacement product features or image files are generated.
- The current embedding path sends text to Cohere. A photo-only display change
  does not change those inputs. Re-embed when the actual embedding text changes,
  keeping its input hash and model identity; introducing real product text is
  such a change. Do not regenerate 500,000 embeddings merely to sharpen photos.

## Inspect locally

The development route is `/catalog-preview`. Set
`MOSAIC_CATALOG_PREVIEW_FILE` to a local JSON file before starting Vite.
The file is served with no-store caching by a development-only endpoint.
The preview route, endpoint and source data are not included in a production
build. No raw third-party product data or photographs are committed.

Each group contains `id`, `label`, `heading`, `request`, `requirements`
(specification labels) and `products`. Each product contains `id`, `brand`,
`model`, `title`, `originalDescription`, `originalBulletPoints`, `image`,
`description` (display summary), `facts`, `sourceUrl` and `sourceLabel`.
Original description/highlights may be null. A fact has `label`, `value`
and optional boolean `meetsNeed`. The checkbox requires every listed
requirement to be explicitly true; missing evidence does not pass.
It filters the visible specifications, not Aurora search results.

Aggregate source reports and input hashes are in
[`docs/evidence/catalog-source-audit/`](evidence/catalog-source-audit/).
`scripts/catalog_source_audit.py` reproduces the ESCI, ABO and Reviews 2023
coverage checks without a database or model call. Its optional Parquet reader
uses PyArrow. The additional Kaggle report records the complete archive hash,
all product columns, identity counts and exact ESCI US overlap. Full ESCI revision:
`7916cdf6ab75a462e77f20ab40428a10923998d5`; Reviews metadata revision:
`2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e`; SQID image-map revision:
`2514ba83e413ee8979798c1ef82d13f737535b04`.

Lab guides, deck, speaker notes and recordings stay on their current measured
story until a replacement exercise has passed Aurora validation.
