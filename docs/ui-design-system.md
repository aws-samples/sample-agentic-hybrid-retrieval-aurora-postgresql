# Mosaic UI design system

## Direction

Mosaic combines a realistic premium catalog with inspectable retrieval
evidence. Product photography and editorial type establish the shopping
context; compact sans-serif and monospaced treatments carry retrieval
diagnostics, SQL, model identifiers, and benchmark settings.

The interface is not patterned after a named retailer and does not use the
retired purple concept direction.

## Brand qualities

- premium, restrained, and product-led;
- credible as both a catalog and an L400 workshop tool;
- clear about source evidence and ranking provenance;
- progressively technical rather than dashboard-heavy;
- responsive without hiding core workshop controls.

## Palette

| Token | Value | Use |
|---|---|---|
| `--mosaic-charcoal` | `#17201e` | Ask Mosaic, technical hero, and trust bands |
| `--maroon-800` | `#671825` | primary actions and Reason-stage emphasis |
| `--mosaic-canvas` | `#f3f5f3` | Shop and Labs page background |
| `--mosaic-surface` | `#ffffff` | tools and product cards |
| `--ink` | `#171514` | primary text |
| `--ink-soft` | `#5f5955` | supporting text |
| `--mosaic-line` | `#dce2df` | borders and table rules |
| `--mosaic-teal` | `#0f6b63` | Retrieve, provenance, readiness, and stock |
| `--mosaic-blue` | `#315d82` | Rank-stage emphasis |
| `--gold` | `#9a5d20` | rating and projection cautions |
| `--danger` | `#a43d43` | failed requests or constraints |

Do not use gradients, decorative orbs, or a single-hue maroon treatment.
Photography, white, cool gray, charcoal, teal, blue, maroon, and gold provide
distinct visual signals.

## Typography

- Display: platform editorial serif for the discover hero, page titles, prices,
  and large benchmark values.
- Interface: platform sans-serif for navigation, controls, cards, and answers.
- Technical: monospaced type only for SQL, source URIs, run IDs, and scores.

Large display type is limited to discovery and product-detail moments. Search,
retrieval, and performance surfaces use compact headings for scanning.

## Geometry and spacing

- 8 px base spacing rhythm;
- 8 px maximum card radius;
- stable `3 / 2` media frames for product cards;
- restrained one-pixel borders and limited shadow;
- 72 px desktop shell and 64 px mobile shell;
- full-width page bands rather than nested cards.

## Route architecture

### Discover

Full-bleed product photography, one search composer, four sample intents, and a
compact `Retrieve -> Rank -> Reason` rail. Every search moves into Shop.

### Shop

Faceted product browsing, direct hybrid search, stable product cards, sort
controls, pagination, and links to source-backed product detail. Ask Mosaic is a
contextual sidecar and the only agent composer, opened from the Shop header.
Desktop compresses the product grid; tablet overlays it; mobile uses the full
working width. Recommendations, retrieved-by labels, the searches behind the
shortlist, rank movement, evidence, citations, and tool receipts stay connected
to the products still visible in Shop.

### Product detail

One product image, descriptive catalog copy, price and availability, source URI
and revision, structured attributes, and review excerpts. Product media never
serves as evidence for an attribute.

### Mosaic Labs

The three labs establish the retrieval sequence. Three Broken -> Fix -> Prove
cards and eight participant runs expose candidate provenance, rank movement,
tool boundaries, and citation grounding without creating additional labs.

### Retrieval Lab

One query is preserved while participants inspect Full-text, `pg_trgm`, Vector,
RRF, and Rerank orderings. The canonical SQL checkpoint remains beside the
candidate table and is directly copyable.

### HNSW Performance Tuning

Scale, `ef_search`, filter selectivity, and iterative-scan controls prepare a
benchmark envelope. Projection badges and measurement-boundary copy prevent
simulated values from being presented as Aurora observations.

## Interaction principles

- Search, agent, and lab results always come from the typed API.
- PostgreSQL remains the owner of filtering, retrieval, and RRF.
- Raw arm scores, RRF, rerank, and final rank remain visually distinct.
- Product citations and source revisions are inspectable.
- Technical detail progressively discloses without blocking the primary task.
- Controls have stable dimensions and do not move when content loads.
- Mobile navigation, filters, tables, and stage controls remain keyboard and
  touch accessible.

## Image boundary

The 120-product premium cohort has a checked-in, content-screened 1200 x 800
catalog asset for every product. `data/media/asset_labels_120.json` is the
product-to-media contract, including the six flagship mappings. Cards render
the complete 3:2 catalog asset with no crop or hover zoom; square detail
photography remains a product-detail concern. Product media never serves as
evidence for an attribute.

## Accessibility

- visible keyboard focus;
- semantic headings, forms, tables, and labels;
- text equivalents for status and chart values;
- no color-only encoding;
- WCAG-aware text contrast;
- reduced-motion support;
- layouts verified at 1440 x 900, 1920 x 1080, 834 x 1112, and 390 x 844.
