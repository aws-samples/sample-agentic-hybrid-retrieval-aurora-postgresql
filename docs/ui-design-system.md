# Catalog Studio UI design system

## Direction

Catalog Studio combines a realistic premium catalog with inspectable retrieval
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
| `--maroon-950` | `#271017` | shell and trust bands |
| `--maroon-800` | `#591a2a` | primary actions and selected stages |
| `--maroon-100` | `#f2e6e9` | selected metadata chips |
| `--ivory` | `#fcfaf5` | page background |
| `--paper` | `#ffffff` | tools and product cards |
| `--paper-warm` | `#f6f1e8` | technical secondary surfaces |
| `--ink` | `#211d1c` | primary text |
| `--ink-soft` | `#625b57` | supporting text |
| `--line` | `#ddd5ca` | borders and table rules |
| `--green` | `#1c6b55` | stock, source readiness, success |
| `--gold` | `#9a6828` | rating and projection cautions |
| `--danger` | `#a43d43` | failed requests or constraints |

Do not use gradients, decorative orbs, or a single-hue maroon treatment.
Photography, ivory, charcoal, green, and gold provide the secondary visual
signals.

## Typography

- Display: platform editorial serif for the discover hero, page titles, prices,
  and large benchmark values.
- Interface: platform sans-serif for navigation, controls, cards, and answers.
- Technical: monospaced type only for SQL, source URIs, run IDs, and scores.

Large display type is limited to discovery and product-detail moments. Search,
retrieval, and performance surfaces use compact headings for scanning.

## Geometry and spacing

- 8 px base spacing rhythm;
- 3-4 px control and card radii;
- stable `4 / 3` media frames for product cards;
- restrained one-pixel borders and limited shadow;
- 74 px desktop shell and 66 px mobile shell;
- full-width page bands rather than nested cards.

## Route architecture

### Discover

Full-bleed category photography, one search composer, sample intents, three
domain entry points, and a compact retrieval trust band. The hero always leaves
the beginning of the catalog section visible.

### Catalog

Faceted product browsing with stable product cards, sort controls, pagination,
and direct links to source-backed product detail. Mobile filters collapse into
one disclosure so products remain in the first working viewport.

### Search and agent

A segmented Retrieval/Agent control shares one query composer. Retrieval shows
ranked products and stage signals; Agent shows a compact cited answer with
Summary, Recommendations, and Trade-offs. Diagnostics stay in a side rail on
desktop and follow the answer on mobile.

### Product detail

One product image, descriptive catalog copy, price and availability, source URI
and revision, structured attributes, and review excerpts. Product media never
serves as evidence for an attribute.

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

The checked-in photographs are screened, unbranded category fallbacks with
local attribution. Product identity and media identity remain separate. A
larger publication-safe merchandising set can replace the fallbacks without
changing product IDs, source evidence, or evaluation judgments.

## Accessibility

- visible keyboard focus;
- semantic headings, forms, tables, and labels;
- text equivalents for status and chart values;
- no color-only encoding;
- WCAG-aware text contrast;
- reduced-motion support;
- layouts verified at 1440 x 1000 and 390 x 844.
