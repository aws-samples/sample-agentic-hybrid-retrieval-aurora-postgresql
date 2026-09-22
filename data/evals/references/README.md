# Reviewed ESCI and WANDS comparisons

This is a small teaching integration, not a full benchmark import. The search
corpus remains 500,000 Amazon Reviews 2023 products with its existing vectors.

| Need | ESCI selection | Separate WANDS selection |
|---|---|---|
| Headphones | Query 107238: earbuds (Exact), audio adapter (Complement) | None; do not invent furniture-dataset coverage |
| Chairs | Query 75180: guest chair (Exact), rolling chair (Irrelevant) | Query 422: adjustable-arm chair (Exact), fixed-arm chair (Partial) |
| Monitors | Query 106506: ultrawide USB-C listing (Exact), ultrawide listing (Substitute) | Query 163: one-screen mount (Partial), two-screen mount (Exact) |

`reviewed_sources.json` preserves 10 original product records and the original
judgment rows across five queries. Six ESCI products join to the current Amazon
catalog by ASIN and US locale; four WANDS products retain their separate IDs.
ESCI snapshot titles can differ from today's imported snapshot. A released
label describes its original query; it does not establish today's compatibility
or a workshop-specific requirement. No labels enter search, fusion, reranking,
or embedding input. WANDS products have no invented Amazon links or photos.

The companion `../reviewed_product_examples.json` holds the current product
review: source revision, exact field quotes, requirements and explicit unknowns.
The UI hides reviewed claims if a current product's source revision differs.
Open `/labs/examples` from Playground to inspect all three categories.

## Reproduce

Install the optional `pyarrow` dependency in the preparation environment, then
run against copies of the upstream files. File hashes and upstream URLs are
saved inside the generated bundle.

```bash
uv run --no-project --with pyarrow python scripts/prepare_reference_examples.py \
  --esci-products /path/to/shopping_queries_dataset_products.parquet \
  --esci-judgments /path/to/shopping_queries_dataset_examples.parquet \
  --wands-dir /path/to/WANDS/dataset

uv run python scripts/verify_reviewed_examples.py --report .local/reviewed-products.json
uv run python scripts/probe_reference_examples.py \
  --base-url http://127.0.0.1:8000 --report .local/reference-searches.json
```

The source verifier reads the configured Aurora cluster. It checks product
identity, exact quotes, source hashes and unchanged embedding inputs. The probe
runs all three selected ESCI queries through the actual search API, reopens the
saved product lists and reports selected-product positions. Other returned
products are **ungraded**, not automatically irrelevant. It calculates no
whole-catalog accuracy or ranking metric. WANDS remains a separate evidence
comparison; its records are not embedded or injected into the Amazon corpus.

Tests retain deliberate faults: changed IDs, altered labels, conflicting
judgments, wrong locale, invented features, incorrect displayed values,
cross-dataset joins, empty comparisons and missing category coverage. An
irrelevant change to reading notes leaves verification unchanged.

## Source notices

- [Amazon ESCI: Shopping Queries Dataset](https://github.com/amazon-science/esci-data), Apache-2.0. Original license and notice are retained in `licenses/`.
- [Wayfair WANDS: Dataset for Product Search Relevance Assessment](https://github.com/wayfair/WANDS), MIT. Original license is retained in `licenses/`.

The extracted records and labels are unchanged. The selection, links to the
current catalog and reading notes are workshop additions. This selected subset
has been inspected and must not later be presented as an untouched evaluation
set. Contradictory label pairs are rejected rather than resolved by choosing the
more convenient label. No Home Depot data is included.
