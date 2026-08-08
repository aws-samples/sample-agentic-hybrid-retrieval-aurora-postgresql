# Catalog specification

## Design objective

The catalog is not random filler. It is a deliberately adversarial retrieval corpus designed to make each workshop technique earn its place. Products vary across wording, metadata completeness, popularity, availability, near-duplicate variants, exact model identifiers, semantic intent, and decisive negative attributes.

## Canonical size and distribution

| Domain | Count | Share |
|---|---:|---:|
| Consumer electronics | 210,000 | 42% |
| Running & fitness | 160,000 | 32% |
| Home office & workspace | 130,000 | 26% |

The detailed taxonomy is stored in `data/dictionaries/taxonomy.json` and summarized in `data/full/manifest.json`.

### Consumer electronics

Nine category families: Audio, Computing, Mobile & Power, Wearables, Networking, Smart Home, Imaging, Gaming, and Accessories. High-value subcategories include over-ear headphones, true-wireless earbuds, monitors, mechanical keyboards, chargers, smartwatches, mesh Wi-Fi, cameras, and gaming displays.

### Running & fitness

Nine category families: Footwear, Apparel, Wearables, Strength, Yoga & Mobility, Cardio Equipment, Hydration, Recovery, and Accessories. High-value subcategories include road/trail/carbon/stability shoes, GPS watches, heart-rate sensors, strength equipment, compact cardio, and recovery tools.

### Home office & workspace

Eleven category families: Seating, Desks, Displays, Input Devices, Lighting, Video & Audio, Organization, Ergonomics, Power & Connectivity, Acoustics, and Air & Environment. This domain is especially useful for dimension, compatibility, selectivity, and ergonomic-intent filters.

## Product fields

Each product includes:

- stable integer ID, UUID, SKU, brand, model, title, taxonomy, and canonical variant group
- short and long natural-language descriptions
- price/list price, ratings, review counts, inventory, availability, shipping, warranty, seller count, and return rate
- popularity, quality, freshness, and metadata-completeness signals
- source-system and update timestamps
- subcategory-specific JSON attributes
- tags and aliases
- FTS-oriented `search_text` and natural-language `embedding_text`
- challenge-cohort labels and an image key

The database schema adds:

- weighted `tsvector` search document
- `trigram_text` for fuzzy lookup
- configurable pgvector embedding column

## Attribute families

Attributes are specialized by product type rather than copied across every row. Examples:

- Headphones: ANC, battery hours, form factor, weight, codec, multipoint, microphone, water rating
- Running shoes: terrain, support, carbon plate, drop, weight, cushioning, intended distance, widths, waterproofing
- Office chairs: lumbar type, armrests, seat-depth adjustment, recline, user-weight rating, recommended daily duration
- Standing desks: width/depth, height range, lift type, load capacity, memory presets, cable management
- Monitors: size, resolution, refresh rate, panel, color gamut, USB-C power, VESA
- Keyboards: layout, switch type, wireless, hot-swap, quiet typing, OS compatibility

## Deliberate challenge cohorts

The shipped manifest records the exact generated count of each cohort. Cohorts can overlap.

| Cohort | Retrieval lesson |
|---|---|
| `typo_target` | Misspelled brand, model, category, and phrase recovery with `pg_trgm` |
| `semantic_only` | Paraphrased benefit/use-case language with limited exact keyword overlap |
| `lexical_only` | Exact model/SKU precision and terse catalog records |
| `hard_negative` | Strong keyword overlap but one decisive capability is absent |
| `hybrid_conflict` | Lexical and semantic candidate lists disagree |
| `near_duplicate` | Variant deduplication and canonical-group diversity |
| `selective_filter` | Prices/attributes near useful threshold boundaries |
| `sparse_metadata` | Missing fields and robustness to incomplete feeds |
| `stale_inventory` | Freshness and source-of-truth conflict |
| `fresh_launch` | High relevance with limited behavioral evidence |
| `popularity_bias` | Popularity conflicts with relevance or quality |
| `compatibility` | OS, connector, platform, size, or mounting constraints |
| `review_evidence` | Review snippets can materially support the recommendation |
| `sponsored_low_relevance` | Governance rule: sponsorship must not silently dominate relevance |

## Hard-negative examples

- A shoe description contains plate-adjacent language but `carbon_plate=false`.
- A headphone offers passive isolation but not active noise cancellation.
- A desk has standing-oriented styling but fixed height.
- A popular product matches broad keywords but violates price or compatibility constraints.

These examples are critical for showing why candidate retrieval and final ranking are different jobs.

## Synthetic-data posture

All products, brands, reviews, model numbers, performance signals, and inventory states are synthetic. The corpus is designed to feel commercially plausible without representing a real merchant catalog or claiming real-world product performance.
