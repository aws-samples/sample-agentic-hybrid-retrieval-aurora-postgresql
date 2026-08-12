# Data generation and extension

## Regenerate the canonical catalog

```bash
uv run python scripts/generate_catalog.py --scale 1.0 --seed 20260806
```

The generator streams directly to gzip and uses only the Python standard library. The same seed produces stable IDs and deterministic product attributes.

## Smaller development catalog

```bash
uv run python scripts/generate_catalog.py \
  --scale 0.02 \
  --output-root /tmp/catalog-10k
```

Generation always writes one shard per domain and records the ordered paths in
`data/full/manifest.json`.

## Reviews

The shipped review evidence covers the 5K sample:

```bash
uv run python scripts/generate_reviews.py
```

To create a larger evidence corpus, point the generator at the full catalog and choose a review density. A million-plus review rows can be generated without changing product IDs.

## Embeddings

The product file contains `embedding_text`, not model-specific vectors. This keeps the canonical dataset independent of provider, dimension, and model version.

```bash
# Workshop path: Cohere Embed v4 through Amazon Bedrock
uv run python scripts/embed_catalog.py \
  --provider bedrock \
  --bedrock-model-id us.cohere.embed-v4:0 \
  --dimensions 1024
```

The command records the exact model ID and content hash with each vector. It
re-embeds a product only when the model or `embedding_text` changes.

For local pipeline and HNSW mechanics only:

```bash
uv run python scripts/embed_catalog.py \
  --provider hash \
  --dimensions 1024 \
  --allow-development-embeddings
```

Hash vectors are never valid workshop relevance results.

## Scale multiplication

For physical 1M/5M/10M datasets, prefer a scale generator that preserves semantic clusters while creating unique IDs, inventory states, and controlled perturbations. Do not simply duplicate identical vectors; that creates unrealistic graph neighborhoods and misleading recall behavior.

For 100M, use a dedicated prebuilt environment or a calibrated projection. The package does not pretend a 100M dataset is physically included.
