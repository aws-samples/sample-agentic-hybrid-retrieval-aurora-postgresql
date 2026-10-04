# Mosaic UI design system

What the storefront and the Playground actually look like, why, and what
enforces it. This is the incumbent design record, derived from the shipped
stylesheets. Shared tokens and base chrome come from `ui/src/styles.css`;
surface behaviour comes from `surfaces.css`, `shop-editorial.css` (with
`workspace-walkthrough.css` for Alex's walkthrough), `inspector.css`,
`instrument.css`, and
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
`agent-answer-parts.css`, `surfaces-labs-shell.css`, `surfaces-hnsw.css`,
`surfaces-playground.css`, then `source-products.css`, `world.css` and, last,
`ask-mosaic.css`, which owns the Ask Mosaic sidecar.
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

Retrieval stages retain their semantic colors: Retrieve is violet, Rank is
orange, and Reason is green. Cobalt marks primary actions, with white labels
in both themes and a darker blue hover state. Links use a separate blue that
stays readable on their surface. Porcelain and cool grey define light mode;
black, graphite, and pale silver define dark mode. Surface contrast, spacing,
and typography separate sections without adding nested card frames.

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
role token follows because it is an alias. Shop's landing alternates grounds
band by band rather than switching the page canvas: `--canvas` for the hero and
light bands, `--paper-warm` for grey bands, and `--stage` for the dark band.
`--stage`, `--stage-ink`, `--stage-soft` and `--stage-link` are black,
near-white, grey and violet in light mode. In dark mode the band lifts to
`--paper-warm` on the black canvas, so it still reads as a band. Components
never branch on the theme. The one theme-specific rule outside the palette is in `world.css`: the
GitHub mark ships as a black SVG image, so dark mode inverts it.

## Palette

The palette block, the first `:root` of `styles.css`, owns shared colour roles.
Aliases point at their source with `var()` rather than repeating a value, so no
two palette roles share a hex. Values below are light / dark; a single value
means the token is an alias that follows its source in both themes.

Surfaces and ink:

| Token | Light | Dark | Role |
|---|---|---|---|
| `--canvas` | `#fafbfd` | `#000000` | page canvas, `html` and `body` |
| `--white` | `#ffffff` | | invariant white for action labels |
| `--paper-strong` | `var(--white)` | `#2b2b30` | raised cards, receipts, popovers |
| `--paper` | `var(--paper-strong)` | | cards, panels, fields |
| `--paper-warm` | `#eef0f4` | `#1c1c1e` | Shop's grey bands, spec highlights, the Ask invitation, the footer |
| `--surface-muted` | `var(--paper-warm)` | | subtle interface panels |
| `--ivory` | `var(--canvas)` | | retained name; now the canvas |
| `--ink` | `#20242b` | `#f5f5f7` | primary text |
| `--ink-soft` | `#58616e` | `#b9bdc6` | supporting text, labels, captions |
| `--line` | `#d9dde3` | `#414148` | internal dividers and hairlines |
| `--line-strong` | `#9ba2ad` | `#8d939f` | the boundary of a card or field; dotted receipt leaders |
| `--stage` | `#141820` | `#1c1c1e` | Shop's dark band |
| `--stage-ink` | `var(--paper-warm)`: `#eef0f4` | `var(--ink)`: `#f5f5f7` | headlines and emphasis on the dark band |
| `--stage-soft` | `#a1a1a6` | `var(--ink-soft)`: `#b9bdc6` | supporting text on the dark band |
| `--stage-link` | `#8fc5ff` | `var(--link)`: `#80bdff` | links and focus on the dark band |

Retrieval roles and action:

| Token | Light | Dark | Role |
|---|---|---|---|
| `--retrieve` | `#6b3fd4` | `#a78bfa` | the Retrieve stage (violet) |
| `--link` | `#005eb8` | `#80bdff` | text links |
| `--focus` | `var(--link)` | | every focus ring, unless a dark panel re-points it locally |
| `--rank` | `var(--gold-bright)` | | the Rank stage as a fill: dots, bars |
| `--reason` | `var(--green)` | | the Reason stage |
| `--action` | `#0668d7` | | the one action colour: primary buttons, the search submit disc, selected pills |
| `--action-hover` | `#005bbd` | | primary action hover |
| `--action-ink` | `var(--white)` | | text and icons on `--action` |

Status and legacy names:

| Token | Light | Dark | Role |
|---|---|---|---|
| `--green`, `--green-soft`, `--green-line` | `#1a7f45` `#e9f7ee` `#b9e3c8` | `#4cd07d` `#0e2818` `#1d4d30` | pass, ready, in stock; `--green` is also Reason |
| `--gold` | `#b45309` | `#ffa24d` | Rank-coloured text; rating and caution text |
| `--gold-deep` | `#8a3c06` | `#ffc28a` | darker caution text |
| `--gold-bright` | `#ff7a28` | `#ff8a3d` | the Rank fill; never text on the light canvas |
| `--gold-soft`, `--gold-line` | `#fff3e8` `#f6d2b0` | `#2b1a0c` `#5c3514` | caution chip fill and border |
| `--danger`, `--danger-soft`, `--danger-line` | `#c62828` `#fff4f4` `#f2c4c4` | `#ff6b6b` `#2b1111` `#5c1f1f` | failed requests and failed checks |
| `--maroon-950` | `#000000` | `#ffffff` | legacy name; the extreme ink |
| `--maroon-900` | `#0f0f10` | `#f0f0f2` | legacy name; high-contrast neutral ink |
| `--maroon-800` | `var(--ink)` | | legacy name; emphasis and active text |
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
| `--nav-glass` | `rgb(250 251 253 / 88%)` | `rgb(28 28 30 / 92%)` | the translucent sticky header, with `saturate(180%) blur(20px)` |
| `--tile-radius` | `18px` | | panel and tile corners |
| `--shadow` | `0 18px 40px rgb(0 0 0 / 10%), 0 2px 6px rgb(0 0 0 / 5%)` | `0 18px 44px rgb(0 0 0 / 60%), 0 2px 6px rgb(0 0 0 / 40%)` | shared elevation |
| `--footer-surface` | `var(--paper-warm)` | | footer background |
| `--footer-ink` | `#424245` | `#d1d1d6` | footer brand, headings, emphasized links, and the footer's focus ring |
| `--footer-muted` | `var(--ink-soft)` | | footer supporting text and navigation |
| `--footer-line` | `var(--line)` | | footer dividers |
| `--ease-out`, `--motion-fast`, `--motion-settle` | `cubic-bezier(0.16, 1, 0.3, 1)`, `160ms`, `320ms` | | shared easing and durations |

Local variables are allowed when a shared rule reads a per-variant value, as
the storage bar's `--segment` and the receipt's `--line` step do, but a colour
value must be a palette token.

### Contrast

Text tokens against the surfaces they are used on, computed on 2026-09-29 from
the token values above with the WCAG 2 relative-luminance formula. Canvas is
`--canvas`, card is `--paper-strong`, tile is `--paper-warm`.

| Token | Light canvas | Light card | Light tile | Dark canvas | Dark card | Dark tile |
|---|---:|---:|---:|---:|---:|---:|
| `--ink` | 15.04:1 | 15.57:1 | 13.65:1 | 19.29:1 | 12.94:1 | 15.63:1 |
| `--ink-soft` | 6.05:1 | 6.27:1 | 5.49:1 | 11.16:1 | 7.48:1 | 9.04:1 |
| `--retrieve` | 6.17:1 | 6.39:1 | 5.60:1 | 7.72:1 | 5.18:1 | 6.25:1 |
| `--link` | 6.16:1 | 6.38:1 | 5.59:1 | 10.64:1 | 7.14:1 | 8.62:1 |
| `--gold` | 4.85:1 | 5.02:1 | 4.40:1 | 10.53:1 | 7.06:1 | 8.53:1 |
| `--gold-deep` | 7.43:1 | 7.69:1 | 6.74:1 | 13.34:1 | 8.94:1 | 10.80:1 |
| `--green` / `--reason` | 4.87:1 | 5.04:1 | 4.42:1 | 10.63:1 | 7.13:1 | 8.61:1 |
| `--danger` | 5.43:1 | 5.62:1 | 4.93:1 | 7.57:1 | 5.08:1 | 6.13:1 |
| `--gold-bright` / `--rank` | 2.51:1 | 2.60:1 | 2.28:1 | 8.95:1 | 6.01:1 | 7.26:1 |
| `--line-strong` | 2.48:1 | 2.57:1 | 2.25:1 | 6.81:1 | 4.57:1 | 5.51:1 |

Paired roles, same method:

| Pair | Light | Dark |
|---|---:|---:|
| `--action-ink` on `--action` | 5.29:1 | 5.29:1 |
| `--action-ink` on `--action-hover` (hover) | 6.50:1 | 6.50:1 |
| `--footer-ink` on `--footer-surface` | 8.78:1 | 11.18:1 |
| `--footer-muted` on `--footer-surface` | 5.49:1 | 9.04:1 |
| `--ink` on `--maroon-100` (hover fill) | 12.75:1 | 12.80:1 |
| `--paper-warm` on `--ink` (code block) | 13.65:1 | 15.63:1 |
| `--stage-ink` on `--stage` (dark band) | 15.58:1 | 15.63:1 |
| `--stage-soft` on `--stage` | 6.91:1 | 9.04:1 |
| `--stage-link` on `--stage` | 9.82:1 | 8.62:1 |

**The Rank text rule.** Rank-coloured text uses `--gold`, never `--rank`.
`--gold-bright` measures 2.51:1 on the light canvas, below the 3:1 floor even
for large text, so the Playground stage numbers (`surfaces-playground.css`) and
the active Rank column heading and top edge (`inspector.css`) use `--gold`.
`--rank` stays a fill: the receipt's Rank dots.
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

- Display and masthead: the native sans serif for Shop, Playground,
  product names and prices, section titles and benchmark figures. Size, weight
  and spacing establish hierarchy within the one family.
- Interface: the same sans serif for navigation, controls, cards, answers and
  lab details.
- Technical: `--mono` for SQL, source references, run ids, scores and settings
  values. `.mono` is 12px.

Base headings in `styles.css`: `h1` 56px, `h2` 30px, both weight 600 with
−0.024em tracking and balanced wrapping; `h3` 17px; heading line height 1.08.
The body carries −0.01em tracking; controls reset to 0.

Shop and the Playground share `--page-title-size`:
`clamp(40px, 4.2vw, 60px)` by default, `clamp(40px, 4.1vw, 54px)` and
`clamp(36px, 8vw, 44px)` under the two `surfaces.css` media queries.
`.commerce-display` (the Shop headline) uses it in `--masthead`;
`world.css` sets its weight to 600, tracking −0.028em and line height 1.07, and
makes its `em` inherit the headline colour. Headlines carry weight and size,
not a coloured word. The Shop landing headline, while no query is active, is
`clamp(36px, 4vw, 56px)` at line height 1.1 and −0.04em tracking, at most
18em wide, wrapping only when the viewport requires it. With a query it is visually hidden
but stays the page's h1, and `Results for …` is the display line.

**The quiet label rule.** Labels sit beside or after what they name, never as
a tracked uppercase kicker above a heading. `.eyebrow` is 14px, weight 600, in
`--ink-soft`. Shop's editorial bands open on their headline, with nothing
above it.

Header navigation is 13px, weight 500, `--ink-soft`; hover and the active entry
turn `--ink`, and the active entry draws a 2px `--ink` underline within the
control's bounds. Prices, ratings, comparison tables, receipt figures and page
counts use tabular figures.

Every Playground tab (Hybrid retrieval, the guided lab, Scale & HNSW, Session &
Memory) shares one masthead scale through `MosaicLabsMasthead`: the title at
`clamp(32px, 3.4vw, 44px)`, weight 600, −0.03em, balanced, one line where it fits,
then a lede. One `.labs-lede` rule sets every lede on those pages (the masthead
deck, the guided lab's stage summaries and the pipeline page's section ledes):
`--ink-soft`, 17px, line height 1.45, at most 64ch. The rule's selectors
out-rank each tab's own masthead rules in `world.css`, so a tab cannot keep a
second scale.

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
the Ask Mosaic note beside results, the product page's photo stage, and the
Scale & HNSW and Session & Memory panels. Shop's editorial photographs, the
Meet Alex frame and the top result's feature plate take 28px, and 20px below
820px. The guided lab
(`playground.css`, scoped `.lab-page`) keeps one card level: its run form is a
26px request card, its completion proof and agent composer are 22px cards, its
figure grids are `--paper-warm` cells with 2px gaps inside a 22px shape, and
its rail, run summary, scorecard, repair evidence and matrix sit flat on the
page. Single-line controls are pills at 999px: the catalog search composer,
lab selects and query inputs, the Playground tabs, the lab rail's stage
control and state chips, submit buttons and evidence badges. Circular controls
(the search submit disc, the run disc, the save button) use 50%.

Other radii in use: the itemized receipt card 16px; result and answer cards
16px; product-card images 12px; ranked result plates 16px and the top
result's photograph 20px; spec highlight tiles on the product page
14px; thumbnails 12px; the shared `.primary-button` / `.secondary-button`
980px, which renders identically to 999px.

- **One segmented control** (`.pg-seg`, in `shared-states.css`): a `--paper-warm`
  pill track with a raised `--paper-strong` segment for the pressed button. The
  Playground orderings and Shop's "Shop / Shop + search details" switch use it. It
  never wraps: on a phone it scrolls sideways as a single row.
- **One disclosure style** (`world.css`): no native marker, a chevron after the
  label that turns over when the section opens, 14px `--ink-soft`. An accordion
  row such as the product page's sets `--disclosure-size`, `--disclosure-ink` and
  `--disclosure-weight` for its larger title and keeps the same chevron. Ask
  Mosaic's sidecar draws its own and is excluded.
- **Selects** hide the native arrow and draw one chevron inside the pill's right
  padding (`world.css`). Its SVG data URI repeats `--ink-soft`'s light and dark
  values, because a data URI cannot read a custom property. The Shop sort pill
  draws its own and is left alone.
- The search field's focus ring is one ring: the `--action` border is 2px (its own
  1px plus a 1px shadow) with a soft 16% halo, and the generic outline stands down.
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
   `diagnostics.candidate_counts.fused_pool`, a 6px `--line-strong` track
   (`.receipt-pool-bar`) on its own row, with a 12px `--rank` dot ringed in
   `--paper-strong`, marks the product's share of that pool, and a sub-line below
   it reads "position 21 of the 50 sent to reranking". Both are omitted when the
   pool size is unknown.
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
headline at `clamp(36px, 4vw, 56px)`, then a 17px lede at most 64ch wide. The pill search follows as the primary action, at most 680px wide,
with its scope line and centred example links. The workspace shelf comes next:
real product cards in a horizontal scroll region, category links and a full
catalog shortcut. The shelf shows whole cards only (4, 3, 2 or 1 at the width it
has) and the first starts under the heading; cards snap into view with touch,
keyboard or arrow controls.
The editorial bands follow in `shop-editorial.css`, each spanning the window with
`clamp(56px, 7vw, 96px)` of vertical padding:

1. Meet Alex on `--paper-warm`: the walkthrough and brief form one
   `--paper-strong` object with a 28px radius.
2. Headphones on `--stage`: centred copy above a full-measure 16:9 photograph,
   with Alex's situation and “What matters” in two columns beneath.
3. Monitors on `--paper-warm` and chairs on `--canvas`: splits that alternate
   image and copy, with 4:3 photographs at a 28px radius.
4. Ask Mosaic as a centred `--paper-warm` band.

Band headlines are `clamp(40px, 5.2vw, 64px)`, or `clamp(34px, 4.2vw, 52px)` in
the splits. Band links are 17px in `--link`, or `--stage-link` on the dark band.
Below 820px the splits stack copy, image, then notes.

**Ranked results.** A search or an Ask Mosaic shortlist replaces the story.
Ranked results read as an editorial list. The first in the final order is a
feature on a `--paper-warm` card with a 28px radius, photograph and facts side
by side, the copy vertically centred. The photograph follows the plate rule:
`multiply` on the image over `--plate` on its container, contained at about 82% of
the plate's width. The rest are rows: a 112px plate and the product details,
separated by 1px `--line` rules and 12px between a row's blocks. The final
position is a 24px `--paper-strong` hairline pill in the plate's top-left corner
(bottom-left when the Ask Mosaic pick badge holds that corner). Compare is a 999px
outline chip around a drawn checkbox. Browsing has no order, so it keeps the
product grid.

When Ask Mosaic's shortlist replaces the results, its headline is the label
alone ("Ask Mosaic shortlist", 28 to 32px) and the question sits under it as a
17px `--ink-soft` line clamped to two lines, with "Show all" only when the clamp
hides something (`ShortlistQuestion.tsx`). "Results for …" is one balanced 28 to
32px heading clamped to two lines; under 820px the ways to ask, the scope line and
the search-details switch step aside so results start near the top.

A failed search is one tile: an 18px `--danger-soft` panel with a `--danger-line`
border, a 15px/600 title, the service's message in 14px `--ink-soft`, a cobalt
"Retry search" pill and a hairline "Clear search" pill. An unknown product or
address is a centred title, one line and a "Back to Shop" pill.

## Chrome behaviour

- Shop's Meet Alex band joins the room walkthrough on the left and the “Meet
  Alex.” brief on the right. The walkthrough has a five-step introduction (the
  starting point, headphones, chair, monitors, then the complete room) ending
  at “Start with clearer calls”, with Next, Replay and explicit Pause/Play
  controls and a step count. Green checks identify the desk and laptop already
  in place; category links identify the pieces still to choose. “Explore
  Alex’s brief” is an ink pill that moves to the bands. The brief at
  `#alex-profile` clears the sticky header and takes focus when the address
  carries that hash; the retired `/discover` address lands there.
- Three bands follow, for headphones, monitors and chairs. Each carries Alex's
  situation, “What matters”, a link to the category and a link to the scoped
  search from the mission manifest. The landing ends with the Ask Mosaic band
  and a note that Alex is fictional and the imagery AI-generated and
  illustrative.
- Shop's search uses `CatalogSearchComposer`, styled by
  `catalog-search.css`: a pill (999px) at least 64px tall on `--canvas` with a
  1px `--line-strong` border that turns `--action` on focus within, an 18px
  search icon, a 15px input, and a 46px circular submit in `--action` with
  `--action-ink`. Page styles control placement and width; field geometry,
  icons and focus treatment stay shared.
- Shop's landing is described under the world layer. Beneath the search,
  Keywords, Typo and Intent example groups are one line of text links in
  `--link`, then a note that every example uses the same search pipeline. On a
  phone each label sits above its links, which form one strip that scrolls
  sideways. “A little help choosing?” and the Ask Mosaic button form the
  landing's closing band; once there are results the header's pill is the way
  in. The band's Ask button is a 999px pill with a gradient from
  `--maroon-800` to `--maroon-950` (ink to the extreme ink of the theme),
  `--paper` text, a sheen that sweeps on hover, and a 1px lift; reduced motion
  disables the sheen and movement. An active query, a shortlist or an open Ask
  panel removes the story bands.
- **Ask Mosaic's one entry point** is a 36px `--action` pill with a sparkle icon in
  the glass header (`SiteHeader.tsx`), on every page. On Shop it opens the panel
  through a window event (`askMosaicEntry.ts`); anywhere else it goes to
  `/catalog?ask=1`. Under 460px it collapses to a 36px circle that keeps its
  name. The product page's “Compare in Ask Mosaic” link stays. The edge tab and
  the docked phone bar are gone.
- Shop result cards for the real catalog (`source-product-card`) are the
  product-page tile: the whole card is a `--paper-warm` tile
  (`--tile-radius`), and the listing photo, `clamp(200px, 21vw, 280px)` high,
  sits directly on its plate with no border or inner box, contained rather
  than cropped. A ranked search prints the product's own recorded final
  position as a pill in the photo's corner (`.shop-card-position`); the
  assist-rank badge keeps the other corner for Ask Mosaic's separate pick order.
  Centred beneath the photo: a two-line 17px
  `--display` product name at weight 600, the brand/category meta, a typed
  spec-facts line (`specFacts`, up to three facts as "label value" pairs; a fact
  never breaks across lines and the line stops at two rows), and
  the price -- the recorded historical listing price with its rating and a
  “Historical listing price” caption for the real catalog, current price and
  stock for the legacy catalog. “Why this match”, in the shared disclosure style, opens the itemized
  receipt; Compare and the Original listing link stay in a left/right footer row
  below it, not centred. The price block has a fixed minimum height so footers
  align across a row of cards. Four
  cards across at 1440px (`.shop-product-grid`), two under 900px, one under
  360px.
- The site header contains navigation, Code Editor when configured, Alex's
  portrait, the theme toggle, and the bag. Repair status belongs to the guided
  Playground rail and completion proof, whose labels distinguish “Code
  repaired” from “SQL repair applied”. While the file still has the fault the
  Aurora label reads “Aurora runs the unrepaired SQL”
  (`labStateCopy.ts`), because “applied” there is the fault. Lab outcomes
  carry a `next` step, and UI command strings come from `participantCommands.ts`,
  which `tests/test_participant_commands.py` holds to the service's copies.
- The guided lab's rail is sticky under the header and condenses once it
  sticks. Row one is the lab's title (20px, weight 600) and its stages as a
  segmented control with a stage-coloured dot each; the current stage is the
  raised segment, and on a phone the control scrolls sideways with snap. Row two
  is the file to edit as a copyable hairline pill, the two state chips and the
  next-lab link at the right edge, with the task and next step in a line under
  them; the task folds away once the rail sticks. `LabRail` reads the stuck state from an `IntersectionObserver`,
  holds its flow footprint constant, and measures its height into
  `--labs-rail-height`, which the stage anchors add to their scroll margin.
- Retrieve, Rank and Reason keep their stage colours on the Playground as
  markers only: the pipeline page's stage chips and the lab rail carry a
  `--retrieve`, `--rank` or `--reason` dot. The guided lab's stage numerals are
  order, not identity, and stay `--ink-soft`. The three search methods are all
  Retrieve: the pipeline page draws their dots in `--retrieve` and tells them
  apart by label, and a method that found nothing gets a hollow dot, as in the
  Shop receipt. A stage the sequence does not name (Prove) uses the neutral
  `--line-strong`. The guided lab's content runs the shell's full width, with the
  numeral inline before each stage title.
- Every Playground send uses `MosaicRunButton`: a 44px `--action` disc with
  an `--action-ink` plane icon, `--action-hover` under the pointer, and a spinner
  while the request is in flight; reduced motion stops the spinner. Hybrid
  retrieval, Session & Memory and the guided lab's Reason composer print a label
  beside the disc.
- The pipeline page (`PlaygroundPage.tsx`, `components/playground/`,
  `playground-page.css` scoped to `.pg-a`) is a product page with receipts: a
  centred stage (request segmented control, the shared Labs masthead centred,
  Alex's request in a 26px-radius `--paper-strong` card), a compact final-choice
  summary and an expandable trace of every returned product. The trace names
  listing IDs, search positions, successful comparisons, registered evidence
  counts and final inclusion. The selected search's record and method-read chips
  expand on demand. Its first result uses a 144×152 photo beside its search number,
  position and agent-selection status, then Retrieve, Rank and Reason follow as
  full-width sections with 34px sentence headings and a stage chip. Retrieve's
  flow is five `--paper-warm` cells joined by 2px gaps; Rank pairs the shipped
  `ProductReceiptBody` with how the order was set, then four-across tiles with a
  Final order / Before reranking switch; Reason sets the answer beside a
  numbered source list and the picks below it.
- `ResultProductCard` shows up to three returned products with a 1px
  `--line-strong` border, 16px corners, the photo on the plate, a two-line 16px
  name, and a position pill in the photo's corner.
- `ProductAnswer` places each returned recommendation once, after the first
  paragraph naming it; Hybrid retrieval Reason, guided Reason and saved memory
  turns share this renderer. Ask Mosaic draws its own answer (`StreamedAnswer`)
  because it shows the picks as cards and rows beside the prose.
- Ask Mosaic (`ask-mosaic.css`, `components/ask-mosaic/`) is a floating sheet on
  desktop (22px corners, `--shadow`, 12px from the edges) and a full-width modal
  at 1180px and below, as before. The header is a sparkle mark in an `--ink`
  circle, "Ask Mosaic" with a one-line subtitle, the Builder view switch, clear
  chat (once there is a conversation) and close as 32px circular icon buttons
  with names. Starters are cards: a line icon in a `--paper-warm` circle, the
  label, the manifest notice in full (it is the card's description, not part of
  its name) and a chevron. The question is a `--paper-warm` bubble, shown in five
  lines with "Show all" when it is long.
  See "Ask Mosaic: the run and its answer" below.
- The footer is a `--paper-warm` band with `--footer-line` dividers,
  `--footer-muted` text and `--footer-ink` emphasis; its focus ring is
  `--footer-ink`.
- How it finds neighbors renders its HNSW scene from `--paper`,
  `--paper-warm` and `--line-strong` read from the computed style, and re-reads
  them, so the scene follows the theme. Hidden views pause; reduced motion
  uses fixed-camera steps; WebGL failure offers a flat graph and retry.
- Navigation preserves the header, resets scroll and keyboard focus for a new
  page, and leaves the current page mounted for query changes.
- Disclosures are native `<details>`, each with a hint of what is inside, drawn in
  the one disclosure style above.
- Text actions carry no decorative arrow. Retained icons are functional: send,
  carousel controls, chevrons and external-listing indicators.
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
three lines with an expand control in `--link`, the same price line the Shop card
prints (the historical price at 24px weight 600 with “Historical listing price”,
or “Price not recorded”), the historical rating, and up to three feature lines,
each clamped to three lines with balanced wrapping. Typed spec highlights follow as a two-column grid of
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
| `/` | Redirects to `/catalog` |
| `/discover` | Redirects to `/catalog#alex-profile`, Alex's brief on Shop |
| `/catalog` | Shop: Alex's brief and three needs before a query, faceted browsing, hybrid search, ranked results as an editorial list, product cards with itemized receipts, Ask Mosaic as a sidecar |
| `/products/:productId` | Product detail: plate photo stage, typed spec highlights, listing details, reviews |
| `/labs/retrieval` | Hybrid retrieval: read-only inspection of Retrieve, Rank, Reason; one run button starts a real run, and `scene` selects a canonical request |
| `/labs/retrieval?view=lab` | Guided Playground: Retrieve, Rank, Reason, Prove, lab rail and completion proof |
| `/labs/examples` | Reviewed examples: “Look beyond the first match.” |
| `/mosaic-labs/hnsw` | Scale & HNSW |
| `/mosaic-labs/hnsw?view=bench` | Full benchmark workbench |
| `/mosaic-labs/memory` | Session & Memory |
| `/mosaic-labs/studio` | Retired composition page; redirects to Hybrid retrieval |

`/playground`, `/mosaic-labs` and `/inspiration` redirect to Hybrid retrieval;
`/shop` redirects to Shop and `/labs/performance` redirects to Scale & HNSW. Any
other address shows a small centred “Page not found” with a “Back to Shop” pill
and keeps the address; it no longer silently shows Shop.

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
attribute. Shop's workspace scenes, in its walkthrough and bands, are editorial illustrations
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
`agent-answer-parts.css`, `surfaces-labs-shell.css`, `surfaces-hnsw.css`,
`surfaces-playground.css`, `shop-editorial.css`, `workspace-walkthrough.css`,
`playground.css`, `inspector.css`,
`playground-page.css`, `world.css` and `ask-mosaic.css`. Over those
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

`scripts/checks/labs_type_scale.py` fails when a rule whose selector names a Labs
family (`.labs-`, `.lab-`, `.hnsw-`, `.mosaic-studio-`, `.mosaic-labs-`,
`.retrieval-`) sets a `font-size` other than a `var(--labs-*)` token or a
`font-family` other than `--display`, `--masthead`, `--sans`, `--mono` or
`inherit`. It scans `styles.css` and `surfaces.css` only.

`npm run build` type-checks both configurations before bundling.

Known drift, recorded rather than canonized:

- On the Shop landing, `shop-editorial.css` overrides `world.css` with higher
  specificity for the fallback suggestion buttons (underlined text instead of
  pills), and `shop-search-details.css` for the example buttons (text links
  instead of bordered pills). What renders is the more specific rule.
- Applying `labs_type_scale.py`'s rule to every sheet reports off-scale Labs
  declarations in `hnsw-search-graph.css` (15), `playground.css` (4),
  `inspector.css` (3), `retrieval-readout.css` (2) and `session-memory.css`
  (1); the gate does not read those files.

## Review boundary

Earlier ship reviews of the Shop story, the advanced instrument, Session &
Memory and Discover were given against the maroon, gold and ivory palette.
They do not cover the light and dark palette, the world layer, the itemized
receipt or the product page described here.

### Ask Mosaic: the run and its answer

**While it runs**, one status line carries the phase in progress ("Reading your
request", "Searching the catalog in Aurora", "Comparing the picks", "Checking the
sources"): a pulsing `--action` dot, a quiet text shimmer and the seconds the
phase has been working. A bar of one segment per phase follows (four on a fresh
search, three on a follow-up that reuses the shortlist), `--green` when done and
`--action` for the current one. Each finished phase is listed with a check and
one finding counted from the stream's own rows (searches ran and products kept,
products compared, citations split into listings and reviews); nothing is
written in advance, and a phase that did nothing says so. A stopped or failed
request keeps the progress it made and says "Stopped before it finished" or
"Request interrupted".

**When it has answered**, the default view (Builder view off) is a collapsed fold
("How Mosaic answered", with steps, searches, sources and seconds; opening it
lists each phase's finding), the first recommendation as a top-pick card (photo,
name, a neutral "Top pick" pill that claims only its position, up to two quoted
facts with citation pills, and a stated requirement judged against the listing),
then the answer prose, then the other picks as compact rows, a hairline Sources
list (number pill, product, Listing or Review pill, title, quote), "Still
unknown", and up to three follow-ups as clear pills.

**The streaming reveal.** Characters arrive faint and darken over their first 24
characters of age. Age is counted across the whole answer, so the trail crosses
paragraphs and citation chips, and it only grows, so nothing ever gets lighter.
The clock runs 24 characters past the end of the text once the stream closes so
the last words finish darkening. Under `prefers-reduced-motion`, and for a turn
restored already answered, the text shows at once with nothing faint.

**Builder view** is a switch in the header, off by default, remembered per
viewer in `localStorage` (and working for the visit when storage is refused). On,
every answer swaps the fold for the recorded run: fact pills (short run id,
session id when present, outcome, total time, memory on or off), a dashed-pill
row "Not recorded on this run" for what `AgentResponse` has no field for (model
id, tokens, Gateway target, claim verdicts), and a timeline of phases whose step
rows come from `plan` and `trace` (tool name in mono, clear pills with stage dots
for the tool, who requested it and how it ended, result count, latency, saved
search id, arguments). Under the search phase, "How it ranked" has a tab per
search. Its rows come from `/api/retrieval/events/{id}`, fetched by each step's
`retrieval_run_id` only once Builder view is on: final position, combined
position, each retrieval method's position, the recorded rerank score, and a bar
splitting the combined score by method using the contributions the database
wrote (never recomputed, so no constant `k` lives in `ui/src`). `k` and the
reranker are printed from the saved search. If the saved search cannot be read,
the recommended products' own signals stand in and the block says "Ranks for the
recommended products". Picks and sources also print their search path and
evidence id, revision and type in mono.

Controls are clear 999px pills with a `--maroon-line` hairline; `--action` marks
the live status, a selected pill, the switch when on and the send disc. Stage
colours appear only as dots. Errors in the `agent_setup` family render as the
setup card only for the two build-it messages; every other message renders as an
alert with its full text.

### Optional inspection pages

Memory and Scale use the same centered introduction, display scale and rounded
neutral surfaces as Hybrid retrieval. Tables keep their own horizontal scroll
regions, and multi-column sections stack on narrow screens. All surfaces use
shared theme tokens; semantic retrieval and proof colors retain their meaning.

Product tiles separate price and the listing action with space. The historical
price caption occupies its own line; no divider touches the price row.

Primary actions use cobalt with white text in both themes; hover uses the darker
`--action-hover` token. Text actions omit decorative arrows. Native search/send,
carousel controls, disclosures and external-source indicators keep their functional icons.

The HNSW illustration uses neutral white lighting independent of UI surface
colors. Unvisited nodes follow the secondary-text role, the active route follows
the blue link role, and layer outlines remain visible in either theme. Theme
changes recolor the geometry without dimming its lighting.

Session & Memory starts with three linked action steps. Agent errors sit beside
the question and replace the idle answer prompt. A completed answer remains
visible while session history loads, including when that refresh fails.
