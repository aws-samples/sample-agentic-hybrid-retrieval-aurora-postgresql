# Synthetic catalog retirement — 3 October 2026

The development Aurora database now contains only the selected real catalog.
A single transaction removed 500,000 synthetic products, their offers,
merchandising assignments and evidence, the legacy search projection and
vocabulary, 309 synthetic brands and 161 unused categories. Before removing
old reference rows, it corrected 1,543 real-product brand links and 79,346
category links from the current source projection.

The transaction verified the catalog receipt and compared the current
projection's row count, identity bounds and aggregate identity before and after.
The production real-only bootstrap check passed before commit: 553,911 products,
553,911 saved embeddings, zero foreign products, synthetic brands, legacy search
documents or legacy vocabulary rows. No active catalog index was rebuilt.

Synthetic CSVs, generated reviews, dictionaries, old evaluation fixtures,
premium-cohort data, offline storefront, generators and loaders have been
retired from the repository. The reusable Bedrock embedding adapter is separate
from catalog generation. Package validation now checks the real archive,
vocabulary, Shop selection and judged-query contracts. Shared database schemas,
current category illustrations and dated measurement records remain in use.

The obsolete local 500,000-vector cache and normalized synthetic CSV exports
were removed (about 2 GB). The Workshop Studio asset prefix contained only the
real-catalog bundle and immutable release assets; no legacy embedding cache
remained there.
