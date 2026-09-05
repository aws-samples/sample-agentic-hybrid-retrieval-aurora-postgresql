# Mosaic UI design system

What the storefront and the Playground actually look like, why, and what
enforces it. The values below are read from `ui/src/styles.css`; where a
number is a measurement, the section says how it was measured.

## Direction

Mosaic is a premium product catalog that is also an L400 inspection tool.
Product photography and an editorial serif carry the shopping context; a
grotesk carries the interface; monospaced type carries SQL, identifiers,
run ids, and measurements, and nothing else. The canvas is ivory, the accent
is maroon, and the two never trade places: maroon is for actions, the active
state, and flagged boundaries, not for large fills.

The interface is not patterned after a named retailer. It uses no gradients
as decoration, no grid-line backgrounds, no accent bars thicker than a
quotation rule, and no eyebrow labels above headings.

## Palette

Every color in the two stylesheets is a role from this block. Aliases point
at their source with `var()` rather than repeating a value, so no two roles
share a hex.

| Token | Value | Role |
|---|---|---|
| `--ivory` | `#fbf8f1` | page canvas, `html` and `body` |
| `--paper` | `#fffdfa` | cards, panels, fields |
| `--paper-strong` | `#ffffff` | the brightest surface; text on maroon |
| `--paper-warm` | `#f3eee5` | tinted surfaces inside paper: table heads, quotes, secondary panels |
| `--ink` | `#171514` | primary text |
| `--ink-soft` | `#5f5955` | supporting text, labels, chips |
| `--line` | `#dfd7cc` | dividers inside a panel: table rules, list separators |
| `--line-strong` | `#b5a999` | the boundary of a card, panel, or field |
| `--maroon-950` … `--maroon-700` | `#2b0d13` `#45101b` `#671825` `#7e2431` | dark surfaces, primary actions, emphasis text |
| `--maroon-100`, `--maroon-50` | `#f4e9e9`, `#fdf4f1` | maroon tints for the finale and Ask Mosaic surfaces |
| `--maroon-line` | `#d7b7bd` | border of a maroon-tinted chip |
| `--green`, `--green-soft`, `--green-line` | `#246a4b` `#e9f2ed` `#bad5c7` | pass, ready, in stock |
| `--gold`, `--gold-deep`, `--gold-bright` | `#9a5d20` `#6a4a18` `#e0a94a` | rating, caution, the vector lens's own accents and chart fills |
| `--gold-soft`, `--gold-line` | `#f6ead9` `#e6d2ae` | gold chip fill and border |
| `--danger`, `--danger-soft`, `--danger-line` | `#a33c43` `#fff8f6` `#e5bdb7` | failed requests and failed checks |
| `--focus` | `var(--maroon-800)` | every focus ring |
| `--shadow` | `0 16px 36px rgb(43 13 19 / 8%)` | the one elevation |

Text tokens against the three light surfaces, measured with the WCAG
relative-luminance formula:

| Token | on ivory | on paper-warm | on maroon-50 |
|---|---:|---:|---:|
| `--ink` | 17.2:1 | 15.8:1 | 16.8:1 |
| `--ink-soft` | 6.5:1 | 6.0:1 | 6.4:1 |
| `--maroon-800` | 11.4:1 | 10.5:1 | 11.2:1 |
| `--maroon-700` | 9.1:1 | 8.3:1 | 8.9:1 |
| `--gold` | 5.0:1 | 4.6:1 | 4.9:1 |
| `--gold-deep` | 7.6:1 | 7.0:1 | 7.4:1 |
| `--danger` | 6.0:1 | 5.5:1 | 5.9:1 |
| `--green` | 6.1:1 | 5.6:1 | 6.0:1 |

`--gold-bright` is a chart fill and never text.

Why ivory rather than white. Paper on ivory is 1.04:1, so a card is not
separated from the canvas by its fill; the hairline is the only edge it has.
That is why boundaries use `--line-strong` at 2.18:1 against ivory while
dividers inside a panel keep the lighter `--line`. The earlier single line
token at 1.34:1 disappeared at projector distance.

Local variables are allowed when a shared rule reads a per-variant value,
as the storage bar's `--segment` does, but the value must be a palette
token.

## Typography

Both faces are self-hosted as Latin variable `woff2` files.

- Display and masthead: Newsreader, weights 400 to 600. Discover and Shop
  headlines, product names, prices, and the large benchmark figures.
- Interface: Schibsted Grotesk, weights 400 to 700. Navigation, controls,
  cards, answers, and every lab surface.
- Technical: the platform monospace stack. SQL, source references, run ids,
  scores, and settings values only. Monospace is never a costume for
  "technical".

The lab surfaces use one scale: display `clamp(36px, 3.6vw, 54px)`, stage
headings `clamp(30px, 2.6vw, 40px)`, section headings 19px, lead 17px, body
15px, detail 13px, micro 12px, and monospace 13px. Uppercase labels sit at
micro size with 0.05em tracking.

## Geometry

- Site header 70px, 66px under 1100px, 62px under 720px, sticky at the top.
- Page width 1480px; the shell is `min(92vw, 1480px)`.
- Radius 8px for cards and panels, 6px inside them, 10px for callouts, and
  999px for chips.
- Boundaries are 1px. Maroon on a boundary means active or flagged. The
  only rule thicker than 1px is the 2px left rule on a blockquote or a
  failed check, which is a quotation mark, not an accent.
- One shadow token, offset and blurred; no zero-offset halos.

## Chrome behaviour

- The labs rail is sticky under the header. Once it sticks it condenses:
  the edit line and the next-lab link fold away and the lab name, stage
  links, and state chips share one row. `LabRail` reads the stuck state from
  an `IntersectionObserver` against a root shrunk by the header, and holds
  its flow footprint constant with a matching negative bottom margin so
  nothing under it moves. It measures its own height into
  `--labs-rail-height`, which the stage anchors add to their scroll margin.
- The rank comparison box chains vertical scrolling to the page and caps its
  height at the viewport below the sticky chrome, never a fraction of the
  screen.
- With a query on the URL, the Shop hero drops its editorial still, the
  headline falls to one line, and the console meets it, so the first result
  is inside the first viewport on a 1366x768 laptop. Without a query the
  full hero stands.
- Stage 04 Prove reads verdict, then the maintainers' release baseline,
  then the package finale. While the baseline is held for an unmeasured
  revision it collapses to one disclosure line; opened, the full record and
  its provenance are there.
- Disclosures are native `<details>`, each with a hint of what is inside.

## Route architecture

| Path | Surface |
|---|---|
| `/`, `/discover` | Discover: the three lab queries as hero prompts, each carried into Shop |
| `/catalog` | Shop: faceted browsing, hybrid search, product cards, Ask Mosaic as a sidecar |
| `/search` | Search: a product need or an agent-assembled collection |
| `/products/:productId` | Product detail: media, catalog copy, price and availability, attributes, evidence excerpts |
| `/labs/retrieval` | Playground: stages 01 Retrieve, 02 Rank, 03 Reason, 04 Prove, with the labs rail and readiness strip above them |
| `/mosaic-labs/hnsw` | Vector index at scale: `ef_search`, filter selectivity, iterative scan, storage, measured against Aurora |
| `/mosaic-labs/studio` | Studio: real catalog objects as a composition study, not a recommendation |

`/playground`, `/labs/performance`, and `/mosaic-labs` redirect to the
Playground.

## Interaction principles

- Search, agent, and lab results come from the typed API. There are no
  content constants or offline fallbacks in the renderer.
- PostgreSQL owns filtering, retrieval, and rank fusion; the interface shows
  what it did and never recomputes it.
- Per-arm ranks, fused rank, rerank, and final rank stay visually distinct.
- Citations and source revisions are inspectable from the answer.
- Technical detail discloses progressively without blocking the task.
- Controls keep stable dimensions while content loads.

## Image boundary

`data/media/asset_labels_200.json` is the product-to-media contract for the
exact-photography set. Product media never serves as evidence for an
attribute.

## Accessibility

- Every focus ring draws from `--focus`; 44 `:focus-visible` rules across
  the two sheets.
- 15 `prefers-reduced-motion` blocks, including smooth scrolling.
- Semantic headings, labelled regions, native forms and tables, and a
  screen-reader-only caption on the rank comparison.
- Status is never carried by color alone; a chip or badge also says its
  state in words.

## Enforcement

`ui/src/styles.test.ts` reads both stylesheets and fails when a referenced
custom property is undefined, when two palette tokens share a value, when a
hex-valued custom property outside the palette block is not an override of
a palette token, or when raw hex literals outside the palette block rise
above the ratchet, currently 252. Each check is proven against a fixture
that fails it. `npm run build` type-checks both configurations before
bundling. The impeccable design detector reports no findings for the two
sheets at this revision.
