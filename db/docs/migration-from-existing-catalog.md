# Migration from the existing 500K Mosaic catalog

The existing workshop archive stores one flat product row with text taxonomy, commerce state, retrieval text, and an image key. This package normalizes that source and creates a search projection.

## Transform

```bash
python scripts/transform_legacy_catalog.py \
  /path/to/products_500k.csv.gz \
  build/normalized
```

Use `--limit 5000` for a quick local test.

## Load

Recommended bulk load pattern:

1. `COPY` `brands.csv.gz` into `mosaic.brand`.
2. `COPY` `categories.csv.gz` into `mosaic.category`.
3. `COPY` `products.csv.gz` into a staging table and upsert `mosaic.product`.
4. `COPY` `offers.csv.gz` into a staging table and upsert `mosaic.product_offer`.
5. Run `CALL mosaic_search.refresh_product_documents();`.
6. Generate embeddings from `mosaic_search.product_document.embedding_text`.
7. Build `sql/08_indexes_concurrent.sql`.
8. Load `data/premium_cohort_120.csv` with `sql/15_load_premium_cohort.sql`.

The transformer leaves embeddings empty; embedding generation remains model-specific and should run in the target environment.
