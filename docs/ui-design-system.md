# Mosaic UI design system

What the storefront and the Playground actually look like, why, and what
enforces it. This is the incumbent design record, derived from the shipped
stylesheets. Shared tokens and base chrome come from `ui/src/styles.css`;
surface behaviour comes from `surfaces.css`, `discover.css`,
`shop-editorial.css`, `inspector.css`, `instrument.css`, and
`reason-products.css`; the cross-surface world layer is `world.css`.
`workspace-continuation.css` styles the supporting Shop collection;
`session-memory.css` and `result-product-card.css` own the memory inspector and
shared answer/retrieval cards; `source-products.css` owns the product page.
Where a number is a measurement, the section says how it was measured.

`styles.css` and `surfaces.css` are each one stylesheet split across several
files by surface, so no single file holds an unrelated mix of concerns. Import
order in `ui/src/main.tsx` is the cascade order: `styles.css`,
`ask-mosaic-panel.css`, `catalog-cards.css`, `shared-states.css`,
`shop-storefront.css`, `labs-agentic.css`, `commerce.css`, then `surfaces.css`,
`surfaces-ask-mosaic.css`, `surfaces-labs-shell.css`, `surfaces-hnsw.css`,
`surfaces-playground.css`, then `source-products.css` and, last, `world.css`.
A new rule belongs in the file already named for its surface; splitting further
only when a file's concerns are genuinely independent, never to hit a line
count.

Load order has one caveat. Page and component stylesheets imported by lazily
loaded routes and components (for example `shop-editorial.css` from
`CatalogPage`, `shop-search-details.css` from `ShopSearchDetails`,
`catalog-search.css` from `CatalogSearchComposer`) arrive after `world.css`, so
a rule there with equal or higher specificity wins over the world layer. Owners
of those sheets must not restate a property `world.css` sets for the same
element; remove the local declaration instead of out-specifying the world.

## Direction

Mosaic is a product catalog that is also an L400 inspection tool. Product
photography and open composition carry the shopping context. One native sans
serif unifies headings, product names and the interface; monospaced type
carries SQL, identifiers, run ids, and measurements, and nothing else.

Colour means retrieval. Retrieve is violet, Rank is orange, Reason is green,
and those three roles are the only chromatic colours in the interface. Every
other surface, line and action is neutral: near-white canvas and grey tiles in
light mode, black canvas and charcoal tiles in dark mode. There is one action
colour, `--action`, a near-black pill in light mode and a white pill in dark
mode. Violet also marks links and the keyboard focus ring.

Alex, a software engineer building a home office for coding, calls and focused
work, connects the shopping and inspection surfaces. Monitor, chair and
headphones imagery establishes that context without changing the lab missions.

## Themes

Light and dark are one palette with two value sets. `ui/src/theme.ts` reads the
`mosaic-theme` key from `localStorage`; when it holds neither `light` nor
`dark` the theme follows `prefers-color-scheme` and keeps following it while
no choice is stored. The result is written to `data-theme` on the root element.
An inline script in `ui/index.html` applies the same rule before first paint,
so the page never flashes the other theme, and the document declares
`color-scheme: light dark`. `ThemeToggle` in the site header (a sun or moon
icon, labelled "Switch to dark mode" or "Switch to light mode") stores the
viewer's choice; if storage is refused the switch still works for the visit.

`:root[data-theme="dark"]` in `styles.css` redefines the base values, and every
role token follows because it is an alias. Components never branch on the
theme. The one theme-specific rule outside the palette is in `world.css`: the
GitHub mark ships as a black SVG image, so dark mode inverts it.

## Palette

The palette block, the first `:root` of `styles.css`, owns shared colour roles.
Aliases point at their source with `var()` rather than repeating a value, so no
two palette roles share a hex. Values below are light / dark; a single value
means the token is an alias that follows its source in both themes.

Surfaces and ink:

| Token | Light | Dark | Role |
|---|---|---|---|
| `--canvas` | `#fbfbfd` | `#000000` | page canvas, `html` and `body` |
| `--paper-strong` | `#ffffff` | `#1c1c1e` | the raised surface: cards, receipts, popovers; the ink on the action pill |
| `--paper` | `var(--paper-strong)` | | cards, panels, fields |
| `--paper-warm` | `#f5f5f7` | `#161617` | tiles: journey tiles, spec highlights, the Ask invitation, the footer |
| `--surface-muted` | `var(--paper-warm)` | | subtle interface panels |
| `--ivory` | `var(--canvas)` | | retained name; now the canvas |
| `--ink` | `#1d1d1f` | `#f5f5f7` | primary text |
| `--ink-soft` | `#6e6e73` | `#a1a1a6` | supporting text, labels, captions |
| `--line` | `#d2d2d7` | `#38383a` | internal dividers and hairlines |
| `--line-strong` | `#aeaeb2` | `#636366` | the boundary of a card or field; dotted receipt leaders |

Retrieval roles and action:

| Token | Light | Dark | Role |
|---|---|---|---|
| `--retrieve` | `#6b3fd4` | `#a78bfa` | the Retrieve stage (violet) |
| `--link` | `var(--retrieve)` | | text links |
| `--focus` | `var(--link)` | | every focus ring, unless a dark panel re-points it locally |
| `--rank` | `var(--gold-bright)` | | the Rank stage as a fill: dots, bars |
| `--reason` | `var(--green)` | | the Reason stage |
| `--action` | `var(--ink)` | | the one action colour: primary buttons, the search submit disc, selected pills |
| `--action-ink` | `var(--paper-strong)` | | text and icons on `--action` |

Status and legacy names:

| Token | Light | Dark | Role |
|---|---|---|---|
| `--green`, `--green-soft`, `--green-line` | `#1a7f45` `#e9f7ee` `#b9e3c8` | `#4cd07d` `#0e2818` `#1d4d30` | pass, ready, in stock; `--green` is also Reason |
| `--gold` | `#b45309` | `#ffa24d` | Rank-coloured text; rating and caution text |
| `--gold-deep` | `#8a3c06` | `#ffc28a` | darker caution text |
| `--gold-bright` | `#ff7a28` | `#ff8a3d` | the Rank fill; never text on the light canvas |
| `--gold-soft`, `--gold-line` | `#fff3e8` `#f6d2b0` | `#2b1a0c` `#5c3514` | caution chip fill and border |
| `--danger`, `--danger-soft`, `--danger-line` | `#c62828` `#fff4f4` `#f2c4c4` | `#ff6b6b` `#2b1111` `#5c1f1f` | failed requests and failed checks |
| `--maroon-950` | `#000000` | `#ffffff` | legacy name; the extreme ink, end of the Ask button gradient |
| `--maroon-900` | `#0f0f10` | `#f0f0f2` | legacy name; the Playground run disc |
| `--maroon-800` | `var(--ink)` | | legacy name; emphasis and active text, hover of action controls |
| `--maroon-700` | `#3a3a3c` | `#d1d1d6` | legacy name; secondary dark ink |
| `--maroon-100`, `--maroon-50` | `#e8e8ed` `#f0f0f3` | `#2c2c2e` `#1f1f21` | legacy names; neutral hover and tint fills |
| `--maroon-line` | `#c7c7cc` | `#48484a` | legacy name; neutral chip border |

No maroon, burgundy, cream or ivory colour remains. The `--maroon-*` and
`--gold*` names survive because many rules reference them; read them by the
value they resolve to, not by the name.

World tokens:

| Token | Light | Dark | Role |
|---|---|---|---|
| `--plate` | `var(--paper-warm)` | `#e8e8ed` | the ground under every listing photo |
| `--nav-glass` | `rgb(251 251 253 / 80%)` | `rgb(22 22 23 / 72%)` | the translucent sticky header, with `saturate(180%) blur(20px)` |
| `--tile-radius` | `18px` | | panel and tile corners |
| `--shadow` | `0 18px 40px rgb(0 0 0 / 10%), 0 2px 6px rgb(0 0 0 / 5%)` | `0 18px 44px rgb(0 0 0 / 60%), 0 2px 6px rgb(0 0 0 / 40%)` | shared elevation |
| `--footer-surface` | `var(--paper-warm)` | | footer background |
| `--footer-ink` | `#424245` | `#d1d1d6` | footer brand, headings, emphasized links, and the footer's focus ring |
| `--footer-muted` | `var(--ink-soft)` | `#86868b` | footer supporting text and navigation |
| `--footer-line` | `var(--line)` | | footer dividers |
| `--ease-out`, `--motion-fast`, `--motion-settle` | `cubic-bezier(0.16, 1, 0.3, 1)`, `160ms`, `320ms` | | shared easing and durations |

Local variables are allowed when a shared rule reads a per-variant value, as
the storage bar's `--segment` and the receipt's `--line` step do, but a colour
value must be a palette token.

### Contrast

Text tokens against the surfaces they are used on, computed on 2026-09-28 from
the token values above with the WCAG 2 relative-luminance formula. Canvas is
`--canvas`, card is `--paper-strong`, tile is `--paper-warm`.

| Token | Light canvas | Light card | Light tile | Dark canvas | Dark card | Dark tile |
|---|---:|---:|---:|---:|---:|---:|
| `--ink` | 16.28:1 | 16.83:1 | 15.46:1 | 19.29:1 | 15.63:1 | 16.61:1 |
| `--ink-soft` | 4.91:1 | 5.07:1 | 4.66:1 | 8.16:1 | 6.61:1 | 7.03:1 |
| `--retrieve` / `--link` | 6.18:1 | 6.39:1 | 5.87:1 | 7.72:1 | 6.25:1 | 6.65:1 |
| `--gold` | 4.86:1 | 5.02:1 | 4.61:1 | 10.53:1 | 8.53:1 | 9.07:1 |
| `--gold-deep` | 7.44:1 | 7.69:1 | 7.07:1 | 13.34:1 | 10.80:1 | 11.48:1 |
| `--green` / `--reason` | 4.88:1 | 5.04:1 | 4.63:1 | 10.63:1 | 8.61:1 | 9.15:1 |
| `--danger` | 5.44:1 | 5.62:1 | 5.16:1 | 7.57:1 | 6.13:1 | 6.52:1 |
| `--gold-bright` / `--rank` | 2.52:1 | 2.60:1 | 2.39:1 | 8.95:1 | 7.26:1 | 7.71:1 |
| `--line-strong` | 2.14:1 | 2.21:1 | 2.03:1 | 3.51:1 | 2.84:1 | 3.02:1 |

Paired roles, same method:

| Pair | Light | Dark |
|---|---:|---:|
| `--action-ink` on `--action` | 16.83:1 | 15.63:1 |
| `--footer-ink` on `--footer-surface` | 9.20:1 | 11.89:1 |
| `--footer-muted` on `--footer-surface` | 4.66:1 | 4.99:1 |
| `--paper` on `--maroon-900` (run disc) | 19.16:1 | 14.95:1 |
| `--ink` on `--maroon-100` (hover fill) | 13.78:1 | 12.80:1 |
| `--paper-warm` on `--ink` (code block) | 15.46:1 | 16.61:1 |

**The Rank text rule.** Rank-coloured text uses `--gold`, never `--rank`.
`--gold-bright` measures 2.52:1 on the light canvas, below the 3:1 floor even
for large text, so the Playground stage numbers (`surfaces-playground.css`) and
the active Rank column heading and top edge (`inspector.css`) use `--gold`.
`--rank` stays a fill: the receipt's Rank dots and the Shop journey's Rank dot.
In dark mode both clear 7:1.

`--line-strong` is a boundary colour. At 2.14:1 on the light canvas it is not a
text colour; the places that currently use it as text are listed under
Enforcement as drift.

## Typography

The user approved a native sans serif across the application on 2026-09-20,
including the Mosaic wordmark and its M badge. The shared `--sans` stack is
`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial,
sans-serif`; `--display` and `--masthead` alias it. `--mono` is
`"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace`; no webfont
ships. Font metrics differ across platforms, so headings and controls must wrap
without clipping.

- Display and masthead: the native sans serif for Discover, Shop, Playground,
  product names and prices, section titles and benchmark figures. Size, weight
  and spacing establish hierarchy within the one family.
- Interface: the same sans serif for navigation, controls, cards, answers and
  lab details.
- Technical: `--mono` for SQL, source references, run ids, scores and settings
  values. `.mono` is 12px.

Base headings in `styles.css`: `h1` 56px, `h2` 30px, both weight 600 with
−0.024em tracking and balanced wrapping; `h3` 17px; heading line height 1.08.
The body carries −0.01em tracking; controls reset to 0.

Discover, Shop and the Playground share `--page-title-size`:
`clamp(40px, 4.2vw, 60px)` by default, `clamp(40px, 4.1vw, 54px)` and
`clamp(36px, 8vw, 44px)` under the two `surfaces.css` media queries.
`.commerce-display` (the Discover and Shop headlines) uses it in `--masthead`;
`world.css` sets its weight to 600, tracking −0.028em and line height 1.07, and
makes its `em` inherit the headline colour. Headlines carry weight and size,
not a coloured word. The Shop landing headline, while no query is active, is
`clamp(40px, 4.2vw, 56px)`.

**The quiet label rule.** Labels sit beside or after what they name, never as
a tracked uppercase kicker above a heading. `.eyebrow` is 14px, weight 600, in
`--ink-soft`. The Shop journey's stage name follows its caption rather than
heading it.

Header navigation is 13px, weight 500, `--ink-soft`; hover and the active entry
turn `--ink`, and the active entry draws a 2px `--ink` underline within the
control's bounds. Prices, ratings, comparison tables, receipt figures and page
counts use tabular figures.

The guided lab and the Labs views use the `--labs-*` scale: display
`clamp(36px, 3.6vw, 54px)`, h2 `clamp(30px, 2.6vw, 40px)`, h3 19px, lead 17px,
body 15px, detail 13px, micro 12px, and mono 13px.

A development-only comparison remains available with `?type=editorial`
(`TypographyPreview`, `typography-preview.css`), loaded only when
`import.meta.env.DEV`; production builds exclude it.

12px is the floor for new text. The stylesheet test holds a ratchet on
`font-size` literals under 12px across every sheet in `ui/src`: the ceiling is
204, and 174 such declarations remained across 35 sheets on 2026-09-28. The
count may only fall.

## Geometry

**The tile and pill rule.** Panels and tiles take `--tile-radius` (18px):
the Shop journey tiles, the Ask Mosaic invitation, the product page's photo
stage, the lab rail, run summary, completion proof, scorecard and repair
panels, and the Labs matrix. Single-line controls are pills at 999px: the
catalog search composer, lab selects and query inputs, the Playground tabs,
lab rail state chips, submit buttons and evidence badges. Circular controls
(the search submit disc, the run disc, the save button) use 50%.

Other radii in use: the itemized receipt card 16px; result and answer cards
16px; journey and product-card images 12px (the Shop landing's journey images
render at 16px, see Enforcement); spec highlight tiles on the product page
14px; thumbnails 12px; the shared `.primary-button` / `.secondary-button` and
the Shop landing example buttons 980px, which renders identically to 999px.

- Hairlines are 1px, `--line` inside a panel and `--line-strong` at the
  boundary of a card or field. The header's bottom edge is `--line` at 70%.
- The site header is `--topbar-height` (56px) high, sticky, on `--nav-glass`
  with a backdrop blur: the one place translucency is the effect.
- Page width 1480px; the shell is `min(92vw, 1480px)`.
- Elevation is `--shadow`: the receipt card, the Ask Mosaic button and
  sidecar. The run disc carries its own `0 7px 18px rgb(0 0 0 / 18%)`. The
  search submit disc has no shadow. Code blocks carry a 1px `--ink-soft`
  boundary and no shadow.

## The world layer

`world.css` is imported last in `main.tsx` and holds the rules that cut across
every surface.

**The plate rule.** Listing photos keep their original white grounds. Every
product image container (Shop cards, the product page stage and thumbnails,
result and Reason cards, reviewed examples, the Ask shortlist and drawer,
suggestion thumbnails, complements) sits on `--plate`, and the image itself is
transparent with `mix-blend-mode: multiply`, so the white ground disappears
into the plate in light mode and reads as a lit plate in dark mode. These
declarations use `!important` so no surface sheet can reintroduce a white box.

**The itemized receipt.** `ProductReceipt.tsx` renders one product's receipt
from the search that returned it, inside Shop's "Why this match" disclosure on
`ProductCard`. The card is `--paper-strong`, 16px corners, `--shadow`, 14px
sans. In order:

1. One line per retrieval method from `armLanguage`, with a Retrieve dot, the
   product's position in that method and its fusion contribution to four
   decimals. A method that did not find the product (`missed`) shows a hollow
   violet dot, `--ink-soft` text, no position and "no match". A position there
   would be one Mosaic invented. Beneath a found line, a 12px `--ink-soft`
   sub-line (`.receipt-how`) spells out the arithmetic -- "position 3 · 1 ÷
   (60 + 3)" -- reading `k` from the response's own
   `diagnostics.retrieval_profile.rrf_k`; beneath a missed line it reads "no
   match for this request". Neither line renders a `k` Mosaic did not
   receive: without diagnostics, the arithmetic sub-line is omitted and only
   the missed line's plain statement remains.
2. Before reranking (`FUSED_LABEL`): the combined position and fused score,
   with a Rank dot and a `--line` rule above. When the response carries
   `diagnostics.candidate_counts.fused_pool`, a slim `--line` track
   (`.receipt-pool-bar`) with a `--rank` dot marks the product's share of that
   pool, and a sub-line reads "position 21 of the 50 sent to reranking". Both
   are omitted when the pool size is unknown.
3. Reranked: the reranker's score to three decimals, only when one was
   recorded, with a sub-line reading "Cohere Rerank relevance score" when
   `diagnostics.rerank_model_id` names a Cohere model, or "relevance score"
   otherwise -- never a version number the model id does not spell out.
4. Final position (`FINAL_LABEL`): 22px weight 600 over a 2px `--ink` rule.
5. "What the listing states": up to four typed specs, each value with its
   verbatim listing quote in 12px `--ink-soft`, under a 12px `--reason`
   heading.

Each label runs to its figure along a 1.5px dotted `--line-strong` leader.
When the disclosure opens, lines settle in order (520ms, 80ms apart, using
`--ease-out`) and the total lands last; `prefers-reduced-motion: reduce`
removes the animation. The card is an inline-size container named `receipt`;
at 300px or narrower each line stacks its label over the position and value,
leaders drop, and the total shrinks to 18px. The `.receipt-how` sub-lines and
the pool-position track always span the row's full width, in both layouts.

**The Shop landing.** With no active query, the Shop heading centres: the
headline, then a lede at most 44ch wide at `clamp(17px, 1.5vw, 21px)`. The pill
search follows as the primary action, then the three journey tiles on
`--paper-warm` in manifest order. Each tile reads image, caption (title and
description), then the stage name at 14px weight 600 in `--ink`, preceded by an
8px dot in its stage colour: `--retrieve`, `--rank`, `--reason`. The Ask Mosaic
invitation is a `--paper-warm` tile with no top rule.

## Chrome behaviour

- Discover opens with “A room built around the way you work.” in the shared
  headline style, without a top eyebrow. “you” carries its own class, but its
  colour, `--maroon-800`, now resolves to `--ink`, so the headline is one
  colour. Below it, a joined frame places the room walkthrough on the left and
  the “Meet Alex.” brief on the right. The walkthrough has a five-step
  introduction (headphones, chair, monitors, then the complete room) ending at
  “Start with clearer calls”, with Next, Replay and explicit Pause/Play
  controls and a step count. Green checks identify the desk and laptop already
  in place; category links identify the pieces still to choose. “Explore
  Alex’s brief” is an ink pill. The brief at `#alex-profile` clears the sticky
  header.
- Discover's search row, “Start with what matters to you.”, uses the shared
  composer and the readiness API's product count. Three needs follow in
  manifest order under “Three needs. One working day.”, each with Alex's
  situation, “What matters” and a scoped Shop link. Discover ends with
  “Now, find the pieces that fit.” and a note that Alex is fictional and the
  imagery AI-generated and illustrative.
- Discover and Shop share `CatalogSearchComposer`, styled by
  `catalog-search.css`: a pill (999px) at least 64px tall on `--canvas` with a
  1px `--line-strong` border that turns `--action` on focus within, an 18px
  search icon, a 15px input, and a 46px circular submit in `--action` with
  `--action-ink`. Page styles control placement and width; field geometry,
  icons and focus treatment stay shared.
- Shop's landing is described under the world layer. Beneath the search,
  Explore offers Keywords, Typo and Intent example groups (pills) and states
  that every example uses the same search pipeline. “A little help choosing?”
  and the Ask Mosaic button sit in the invitation tile. The Ask button is a
  999px pill with a gradient from `--maroon-800` to `--maroon-950` (ink to the
  extreme ink of the theme), `--paper` text, a sheen that sweeps on hover, and
  a 1px lift; reduced motion disables the sheen and movement. An active query
  or open Ask panel removes the journey.
- Shop result cards for the real catalog (`source-product-card`) are the
  product-page tile: the whole card is a `--paper-warm` tile
  (`--tile-radius`), and the listing photo, `clamp(200px, 21vw, 280px)` high,
  sits directly on its plate with no border or inner box, contained rather
  than cropped. A ranked search prints the product's own recorded final
  position, quiet 12px `--ink-soft` text above the photo (`.shop-card-
  position`); the assist-rank badge keeps the photo's own corner for Ask
  Mosaic's separate pick order. Centred beneath the photo: a two-line 17px
  `--display` product name at weight 600, the brand/category meta, a typed
  spec-facts line (`specFacts`, up to three facts as "label value" pairs), and
  the price -- the recorded historical listing price with its rating and a
  “Historical listing price” caption for the real catalog, current price and
  stock for the legacy catalog. “Why this match ›”, in `--link` with a
  trailing chevron, opens the itemized receipt; Compare and the Original
  listing link stay in a left/right footer row below it, not centred. Four
  cards across at 1440px (`.shop-product-grid`), two under 900px, one under
  360px.
- Under 900px the Try Ask Mosaic rail docks across the bottom of Shop and the
  page reserves space beneath its results so the rail never covers a result.
- The site header contains navigation, Code Editor when configured, Alex's
  portrait, the theme toggle, and the bag. Repair status belongs to the guided
  Playground rail and completion proof, whose labels distinguish “Code
  repaired” from “SQL repair applied”.
- The guided lab's rail is sticky under the header and condenses once it
  sticks. `LabRail` reads the stuck state from an `IntersectionObserver`,
  holds its flow footprint constant, and measures its height into
  `--labs-rail-height`, which the stage anchors add to their scroll margin.
- Retrieve, Rank and Reason keep their stage colours on the Playground: the
  pipeline page's stage chips carry a `--retrieve`, `--rank` or `--reason` dot,
  and the guided lab's step numbers use `--retrieve`, `--gold` and `--reason`.
  A stage the sequence does not name (Prove) uses the neutral `--line-strong`.
- Every Playground send uses `MosaicRunButton`: a 44px `--maroon-900` disc with
  a `--paper` plane icon, `--maroon-800` under the pointer, and a spinner while
  the request is in flight; reduced motion stops the spinner. Hybrid retrieval
  and Session & Memory print a label beside the disc.
- The pipeline page (`PlaygroundPage.tsx`, `components/playground/`,
  `playground-page.css` scoped to `.pg-a`) is a product page with receipts: a
  centred stage (request segmented control, the shared Labs masthead centred,
  Alex's request in a 26px-radius `--paper-strong` card), the selected search's
  record with its method-read chips, the search's first result on a 460×320
  `--plate` with whether the agent picked it, then Retrieve, Rank and Reason as
  full-width sections with 34px sentence headings and a stage chip. Retrieve's
  flow is five `--paper-warm` cells joined by 2px gaps; Rank pairs the shipped
  `ProductReceiptBody` with how the order was set, then four-across tiles with a
  Final order / Before reranking switch; Reason sets the answer beside a
  numbered source list and the picks below it.
- `ResultProductCard` shows up to three returned products with a 1px
  `--line-strong` border, 16px corners, the photo on the plate, a two-line 16px
  name, and a position pill in the photo's corner.
- `ProductAnswer` places each returned recommendation once, after the first
  paragraph naming it; Hybrid retrieval Reason, guided Reason, Ask Mosaic and
  saved memory turns share this renderer. Ask Mosaic passes
  `placeCards={false}` because its comparison table already shows the picks.
- Ask Mosaic (`ask-mosaic-answer.css`, `components/ask-mosaic/`) shows the
  question as a `--paper-warm` bubble and the run as one live line that settles
  into a summary; the trace opens from that line. The answer is unboxed: the
  best pick on a 196px `--plate` with its retrieval path (shown again only when
  the pick changes), then a comparison table whose cells carry a source icon
  (`--green` listing, `--ink-soft` title only, `--gold` review, `--danger` short
  of a stated requirement) and citation numbers, then the `ProductAnswer` prose
  without inline cards, then a `--paper-warm` sources and “Still unknown” block.
  Ask is a desktop sidecar and a fixed overlay at 1180px and below.
- The footer is a `--paper-warm` band with `--footer-line` dividers,
  `--footer-muted` text and `--footer-ink` emphasis; its focus ring is
  `--footer-ink`.
- How it finds neighbors renders its HNSW scene from `--paper`,
  `--paper-warm` and `--line-strong` read from the computed style, and re-reads
  them, so the scene follows the theme. Hidden views pause; reduced motion
  uses fixed-camera steps; WebGL failure offers a flat graph and retry.
- Navigation preserves the header, resets scroll and keyboard focus for a new
  page, and leaves the current page mounted for query changes.
- Disclosures are native `<details>`, each with a hint of what is inside.
- Completion proof keeps failed checks visible and passing checks expandable,
  and can download the exact measured JSON.

## Product page

`SourceProductDetail.tsx` with `source-products.css`. The photo stage is
`clamp(340px, 38vw, 540px)` high (300px under 760px) with 44px padding,
`--tile-radius` corners and `--plate`; the photo is contained. A 40px round save
button sits in its corner. Thumbnails are 64px plate tiles with 12px corners;
the selected one draws a 2px `--ink` ring. A 12px caption reads “Original
listing photos” and the view count.

The summary gives brand and category (14px, weight 600, `--ink-soft`), the
title at `clamp(28px, 2.6vw, 40px)` weight 600 (25px under 760px), clamped to
three lines with an expand control in `--link`, the historical rating, and up
to three feature lines. Typed spec highlights follow as a two-column grid of
`--paper-warm` tiles with 14px corners: the value above at
`clamp(20px, 1.8vw, 26px)` weight 600 with tabular figures, the label beneath
at 13px `--ink-soft`, and the listing's words in the tile's title as “From the
listing: …”. The typed specs come from `service/product_specs.py`.

Below, Description, Specifications and Reviews are native disclosures divided
by `--line`. Under Specifications, the key specs list each value with its
verbatim listing quote in 13px `--ink-soft` inside curly quotes, then “All
listing details” lists the remaining attributes. “Similar options” closes the
page with a four-column grid (two under 760px).

## Route architecture

The development-only `/catalog-preview` and `/design-studio` routes are
registered only when `import.meta.env.DEV`; production builds exclude them.
`/catalog-preview` compares real-product samples without claiming a live
search. `/design-studio` is a prototype with its own scoped `--studio-*`
palette in `studio-prototype.css`; it is not the storefront's design.

| Path | Surface |
|---|---|
| `/`, `/discover` | Discover: Alex's room brief, three illustrated shopping needs, general search |
| `/catalog` | Shop: faceted browsing, hybrid search, product cards with itemized receipts, Ask Mosaic as a sidecar |
| `/products/:productId` | Product detail: plate photo stage, typed spec highlights, listing details, reviews |
| `/labs/retrieval` | Hybrid retrieval: read-only inspection of Retrieve, Rank, Reason; one run button starts a real run, and `scene` selects a canonical request |
| `/labs/retrieval?view=lab` | Guided Playground: Retrieve, Rank, Reason, Prove, lab rail and completion proof |
| `/labs/examples` | Reviewed examples: “Look beyond the first match.” |
| `/mosaic-labs/hnsw` | Scale & HNSW |
| `/mosaic-labs/hnsw?view=bench` | Full benchmark workbench |
| `/mosaic-labs/memory` | Session & Memory |
| `/mosaic-labs/studio` | Retired composition page; redirects to Hybrid retrieval |

`/playground`, `/mosaic-labs` and `/inspiration` redirect to Hybrid retrieval;
`/shop` redirects to Shop and `/labs/performance` redirects to Scale & HNSW.

## Interaction principles

- Search, agent, and lab results come from the typed API. There are no
  content constants or offline fallbacks in the renderer.
- PostgreSQL owns filtering, retrieval, and rank fusion; the interface shows
  what it did and never recomputes it. The receipt prints recorded positions
  and scores only.
- Per-method ranks, fused rank, rerank, and final rank stay visually distinct.
- Citations and source revisions are inspectable from the answer.
- Technical detail discloses progressively without blocking the task.
- Controls keep stable dimensions while content loads.
- Memory supplies context; Aurora supplies product facts and citation evidence.
- Scale distinguishes current index facts from recorded experiments.

## Image boundary

`data/media/asset_labels_200.json` is the product-to-media contract for the
exact-photography set. Product media never serves as evidence for an
attribute. Shop's and Discover's workspace scenes are editorial illustrations
recorded in `data/media/alex-shop-story-v3.json` and
`data/media/alex-discover-studio-v1.json`; they establish no product
specifications. Listing photos are shown uncropped and contained on the plate.

## Accessibility

- Focus uses `:focus-visible` with a 3px outline of `--focus` at 65% and a 3px
  offset; `--focus` is violet. The footer re-points it to `--footer-ink`, and
  `.code-block`, whose panel is `--ink`, re-points it to `--canvas` so the ring
  contrasts with the panel in both themes.
- Reduced-motion rules cover the receipt settle, the Ask button sheen, the run
  spinner, entrance effects and smooth scrolling.
- Semantic headings, labelled regions, native forms, tables and disclosures.
- Status is never carried by colour alone: a receipt line that missed says
  “no match”, and chips and badges say their state in words.

## Enforcement

`ui/src/styles.test.ts` reads the sheets in its `SHEETS` list: `styles.css`,
`ask-mosaic-panel.css`, `catalog-cards.css`, `shared-states.css`,
`shop-storefront.css`, `labs-agentic.css`, `commerce.css`, `surfaces.css`,
`surfaces-ask-mosaic.css`, `surfaces-labs-shell.css`, `surfaces-hnsw.css`,
`surfaces-playground.css`, `discover.css`, `playground.css`, `inspector.css`,
`playground-page.css`, `world.css` and `ask-mosaic-answer.css`. Over those
sheets it fails when:

- a referenced custom property is defined nowhere (except `--labs-rail-height`,
  `--low`, `--high` and `--sweep`, which components set inline);
- two hex values in the palette block, the first `:root` of `styles.css`, are
  equal (the dark block is not part of this check);
- a hex-valued custom property outside the palette block is not an override
  of a palette token;
- a raw hex literal appears outside a token definition, a mask or a `url()`.
  The ceiling is 0.

The sub-12px `font-size` ratchet (ceiling 204) reads every `.css` file in
`ui/src`, not only the list. Each check is proven against a fixture that fails
it. A sheet missing from `SHEETS` is not read by the hex, palette and
undefined-variable checks; `catalog-search.css`, `source-products.css`,
`mosaic-run-button.css` and the other component sheets are currently outside
it. A grep on 2026-09-28 found no hex literal in those sheets other than the
development-only `studio-prototype.css` palette.

`scripts/labs_type_scale.py` fails when a rule whose selector names a Labs
family (`.labs-`, `.lab-`, `.hnsw-`, `.mosaic-studio-`, `.mosaic-labs-`,
`.retrieval-`) sets a `font-size` other than a `var(--labs-*)` token or a
`font-family` other than `--display`, `--masthead`, `--sans`, `--mono` or
`inherit`. It scans `styles.css` and `surfaces.css` only.

`npm run build` type-checks both configurations before bundling.

Known drift, recorded rather than canonized:

- The search submit and run disc hover to `--maroon-800`, which equals the
  `--action` rest colour of the search submit, so that hover changes nothing.
  The run disc rests on `--maroon-900`, not `--action`.
- On the Shop landing, `shop-editorial.css` loads after `world.css` with
  higher specificity for the journey tiles (grid instead of flex, 16px image
  corners, heading weight 500) and for the fallback suggestion buttons
  (underlined text instead of pills); `shop-search-details.css` loads after it
  with equal specificity for the example buttons (1px `--line` border on
  `--canvas`). What renders is the later rule.
- Applying `labs_type_scale.py`'s rule to every sheet reports off-scale Labs
  declarations in `hnsw-search-graph.css` (15), `playground.css` (4),
  `inspector.css` (3), `retrieval-readout.css` (2) and `session-memory.css`
  (1); the gate does not read those files.

## Review boundary

Earlier ship reviews of the Shop story, the advanced instrument, Session &
Memory and Discover were given against the maroon, gold and ivory palette.
They do not cover the light and dark palette, the world layer, the itemized
receipt or the product page described here.
