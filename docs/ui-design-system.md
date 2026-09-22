# Mosaic UI design system

What the storefront and the Playground actually look like, why, and what
enforces it. This is the incumbent design record. Shared tokens come from
`ui/src/styles.css`; surface behaviour comes from `surfaces.css`,
`discover.css`, `shop-editorial.css`, `inspector.css`, `instrument.css`, and `reason-products.css`.
`workspace-continuation.css` styles the supporting Shop collection;
`session-memory.css` and `result-product-card.css` own the memory inspector and
shared answer/retrieval cards. Where a number is a measurement, the section
says how it was measured.

## Direction

Mosaic is a premium product catalog that is also an L400 inspection tool.
Product photography and open editorial composition carry the shopping context.
A native sans serif unifies headings, product names and the interface;
monospaced type carries SQL, identifiers,
run ids, and measurements, and nothing else. The canvas is white, the accent
is maroon, and the two never trade places: maroon is for actions, the active
state, and flagged boundaries, not for large fills.

Alex, a software engineer building a home office for coding, calls and focused
work, connects the shopping and inspection surfaces. Monitor, chair and
headphones imagery establishes that context without changing the lab missions.
The interface is not patterned after a named retailer. The main canvas stays
plain; Shop's opening Ask action uses a quiet maroon outline and sparkle icon.

## Palette

The palette block owns shared color roles. Aliases point at their source with
`var()` rather than repeating a value, so no two palette roles share a hex.
Remaining surface literals are bounded by the stylesheet test's ratchet.

| Token | Value | Role |
|---|---|---|
| `--canvas` | `var(--paper-strong)` | white page canvas, `html` and `body` |
| `--ivory` | `#fbf8f1` | retained warm palette color |
| `--paper` | `#fffdfa` | cards, panels, fields |
| `--paper-strong` | `#ffffff` | the brightest surface; text on maroon |
| `--paper-warm` | `#f3eee5` | tinted surfaces inside paper: table heads, quotes, secondary panels |
| `--surface-muted` | `#f5f5f7` | neutral grey for interface hover states, waiting panels and memory code disclosures |
| `--ink` | `#171514` | primary text |
| `--ink-soft` | `#5b5b63` | neutral charcoal for supporting text, labels, chips |
| `--footer-surface` | `#242426` | charcoal background for the shared storefront footer |
| `--footer-ink` | `var(--paper-strong)` | footer brand, headings, emphasized links and focus rings |
| `--footer-muted` | `#b9b9bf` | footer supporting text and navigation |
| `--footer-line` | `#48484e` | dividers within the footer |
| `--line` | `#e2e2e7` | neutral grey dividers inside a panel: table rules, list separators |
| `--line-strong` | `#b5b5bd` | the boundary of a card, panel, or field |
| `--maroon-950` … `--maroon-700` | `#2b0d13` `#45101b` `#671825` `#7e2431` | dark surfaces, primary actions, emphasis text |
| `--maroon-100`, `--maroon-50` | `#f4e9e9`, `#fdf4f1` | maroon tints for the finale and Ask Mosaic surfaces |
| `--maroon-line` | `#d7b7bd` | border of a maroon-tinted chip |
| `--green`, `--green-soft`, `--green-line` | `#246a4b` `#e9f2ed` `#bad5c7` | pass, ready, in stock |
| `--gold`, `--gold-deep`, `--gold-bright` | `#9a5d20` `#6a4a18` `#e0a94a` | rating, caution, the vector lens's own accents and chart fills |
| `--gold-soft`, `--gold-line` | `#f6ead9` `#e6d2ae` | gold chip fill and border |
| `--danger`, `--danger-soft`, `--danger-line` | `#a33c43` `#fff8f6` `#e5bdb7` | failed requests and failed checks |
| `--focus` | `var(--maroon-800)` | every focus ring |
| `--shadow` | `0 16px 36px rgb(43 13 19 / 8%)` | shared elevation |

Text tokens against the three light surfaces, measured with the WCAG
relative-luminance formula:

| Token | on ivory | on paper-warm | on maroon-50 |
|---|---:|---:|---:|
| `--ink` | 17.2:1 | 15.8:1 | 16.8:1 |
| `--ink-soft` | 6.3:1 | 5.8:1 | 6.2:1 |
| `--maroon-800` | 11.4:1 | 10.5:1 | 11.2:1 |
| `--maroon-700` | 9.1:1 | 8.3:1 | 8.9:1 |
| `--gold` | 5.0:1 | 4.6:1 | 4.9:1 |
| `--gold-deep` | 7.6:1 | 7.0:1 | 7.4:1 |
| `--danger` | 6.0:1 | 5.5:1 | 5.9:1 |
| `--green` | 6.1:1 | 5.6:1 | 6.0:1 |

`--gold-bright` is a chart fill and never text.

The user chose white on 2026-09-20 after comparing the Editorial design with
the real-product sample. White lets product photographs sit naturally on the
page; warm paper remains a secondary panel treatment. Boundaries continue to
use `--line-strong`, with the lighter `--line` reserved for internal dividers.
The contrast table above records the earlier warm surfaces; the text colors
also meet their contrast requirements against the lighter white canvas.

The shared storefront footer uses charcoal instead of cream. Its white text
measures 15.49:1 against the background, and its supporting text measures
7.94:1. The page canvas and secondary warm surfaces retain their own roles.

Shared dividers and supporting text use neutral greys to connect the white
canvas with the charcoal footer. Subtle interface panels use `--surface-muted`;
product photography retains its warm framing. Supporting text measures 6.73:1
on white and 6.18:1 on the neutral panel surface.

Local variables are allowed when a shared rule reads a per-variant value,
as the storage bar's `--segment` does, but the value must be a palette
token.

## Typography

The user approved a native sans serif across the application on 2026-09-20,
including the Mosaic wordmark and its M badge. The shared `--sans` stack is
`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial,
sans-serif`; `--display` and `--masthead` alias it. Apple platforms use their
native system face, with the listed installed-font fallbacks on other platforms.
The default does not download Newsreader or Schibsted Grotesk. Font metrics can
differ across platforms, so headings and controls must wrap without clipping.

- Display and masthead: native sans serif for Discover, Shop, Playground,
  product names and prices, section titles and benchmark figures. Size, weight
  and spacing establish hierarchy within the shared family.
- Interface: the same native sans serif for navigation, controls, cards,
  answers and lab details. The Mosaic wordmark uses weight 600; the M badge is
  a text glyph using `--sans`, rather than a separately drawn letterform.
- Technical: the platform monospace stack for SQL, source references, run ids,
  scores and settings values. This role remains distinct from prose.

Discover section headings, Shop product and comparison headings, and the
Retrieve / Rank / Reason headings use weight 500 for a consistent middle step
between body copy and page titles. Prices, ratings, comparison tables and page
counts use tabular figures so numbers stay aligned. Header navigation is 14px
with natural letter spacing; active navigation and category tabs use burgundy
text and a 2px underline within the control's bounds.

Discover, Shop and the default Playground share the page-title role:
`--page-title-size`, upright `--masthead`, weight 500, line height 1.12 and
letter spacing −0.015em. The size is `clamp(40px, 4.2vw, 60px)` by default,
`clamp(40px, 4.1vw, 54px)` above 760px wide when the viewport is at most 800px
high, and `clamp(36px, 8vw, 44px)` at 760px wide and below. These are the same
rules on all three pages. Discover's two-line headline, “A room built around
the way you work.”, is charcoal with “you” in burgundy. Shop's burgundy emphasis
is upright and inherits the headline's weight and line height. “Meet Alex.” is
an h2 at `clamp(32px, 3vw, 42px)` in the shared display family, beside his portrait.

A development-only comparison remains available with `?type=editorial`:
Newsreader for display and mastheads, Schibsted Grotesk for the interface,
and italic commerce emphasis. These Latin variable `woff2` faces are loaded
only by the development preview stylesheet. `?type=system` selects the adopted
modern typography. The choice follows navigation within that browser tab;
closing the preview restores modern typography. The switcher, editorial font
rules and stylesheet are excluded from the production bundle.

The guided lab shares `--page-title-size` with the other Playground views; stage
headings `clamp(30px, 2.6vw, 40px)`, section headings 19px, lead 17px, body
15px, detail 13px, micro 12px, and monospace 13px. Uppercase labels sit at
micro size with 0.05em tracking. Session & Memory, Hybrid retrieval, Scale & HNSW,
and the benchmark workbench share rounded action controls, native sans serif
headings, white fields, and open sections divided by hairlines. Selections retain
their native select behavior; roundness does not replace accessible labels.

Session & Memory leads with the optional lab's question, read from
`optional_labs.memory` in the mission contract. The saved message and actual
extracted records are the primary content; strategy mechanics stay in disclosures.
New session and Start fresh retain their distinct identity behavior. A green
connection dot appears only for an active Memory connection, pulses gently, and
stays static under `prefers-reduced-motion: reduce`.

12px is the floor for new text. It already holds for the sitewide
`.eyebrow`, Shop's per-card retrieval breakdown and its Compare label, the
search-progress steps, code blocks and the site footer; some older chrome
still sits below it. The stylesheet test holds a ratchet on `font-size`
literals under 12px: 204 legacy declarations remained on 2026-09-09, and
the count may only fall.
Long-form copy on the Build view and the Scale page is capped at 70ch.

Hybrid retrieval, Scale & HNSW and Session & Memory use the shared page-title
role through `.inspector-intro h1`, followed by inspection content in the
same family. Alex's
circular Hybrid retrieval portrait is 72px on desktop and 56px under 760px;
the request uses the shared display token and the Run Mosaic action remains labelled on mobile.

## Geometry

- Site header 70px, 66px at 900px and below, 62px at 460px and below, sticky
  at the top.
- Page width 1480px; the shell is `min(92vw, 1480px)`.
- Shop product imagery has square corners; the three story photographs and
  Discover's joined photo-and-brief frame use 16px corners.
  Discover and Shop share the catalog search
  geometry described below; Ask Mosaic retains its pill shape. Shared
  answer/retrieval cards use 16px, inner details 6px, inspector callouts and
  memory records 12px, and chips and other pill actions 999px.
- Boundaries are 1px. Maroon on a boundary means active or flagged. The
  2px left rule on a blockquote, a failed check, or the gold coverage notice
  signals a quotation or caution. The selected memory strategy uses a 2px
  maroon underline.
- The shared shadow is offset and blurred. Shop's paper-plane Search button,
  filled Ask action and sidecar retain their established elevation. Hybrid retrieval and Scale use rules and warm fills.
  Code blocks carry a 1px ink-soft boundary and no shadow of their own.

## Chrome behaviour

- Discover opens with “A room built around the way you work.” in native sans
  serif, without a top eyebrow. Below it, a joined, rounded frame places a large room photograph on the
  left and the full “Meet Alex.” brief on a neutral grey surface at its right.
  The photograph has a five-step introduction: starting point, headphones,
  chair, monitors, then the complete-room vision. Each need highlights its
  place in the room and gives a short explanation with a scoped Shop link.
  It advances every eight seconds while both the picture and explanation are
  visible, then stops at “Start with clearer calls.” Next, Previous, direct
  step selection and Replay pause automatic playback. Pause/Play is explicit;
  hover, keyboard interaction and hidden tabs also hold the current step.
  Reduced-motion viewers use the manual controls without image transitions.
  The caption counts introduction steps, never purchases or lab completion.
  Green checks identify the
  desk and laptop already in place; white category pills identify the headphones,
  chair and monitor still to choose. “Explore Alex’s brief” is a burgundy pill
  without an arrow icon. Content determines the panel height, so
  larger text remains readable. The studio stacks at 760px and below. The
  focusable brief at `#alex-profile` clears the sticky header.
- Three illustrated needs follow in manifest order: Clearer calls, Comfortable
  days and Room to code. Each gives Alex's situation, “What matters” and a text
  link carrying the same scoped query as Shop. Category links carry only the
  category filters. One general search field uses the shared readiness API
  count; `discoverData` fetches no catalog products. Discover ends with a Shop
  invitation, without an inventory grid, completion tracking or lab instructions.
  Its disclosure identifies Alex as fictional and the imagery as illustrative.
- Discover and Shop use one `CatalogSearchComposer` visual standard, owned by
  the component's shared styles: a 64px-tall white field with a 12px radius,
  an 18px plain Search icon, and a 46px round burgundy submit button with a
  16px Send icon. The submit button retains its accessible action name, tooltip,
  soft shadow, maroon-900 fill and maroon-800 hover state. Keyboard focus in the
  input draws a 2px maroon ring around the form with a 3px offset; the submit
  button keeps its own focus indicator. Page styles control placement and
  available width, while field geometry, icons and focus treatment stay shared.
- Shop results run three across at laptop width on clean 3:2 image plates.
  The product name uses native sans serif at 26px, one voice with
  the product page; brand and category are one sans line; the specification
  is clamped to one line; “Why this match” and the price row sit on hairline
  rules, not in boxes. The filter row is text with the navigation's underline
  for the open sheet and the active stock switch, so it does not compete with
  the photography beneath it. The results line sets the shopper's own words
  in italic native sans serif at 26px under a 12px uppercase label.
- Under 900px the Try Ask Mosaic rail docks across the bottom of Shop and the
  page reserves 88px beneath its results, so the rail never covers a result
  line or a card price. The Ask Mosaic answer offers "Show the full answer"
  while it is still being written, which ends the paced reveal for the turn.
- The site header contains navigation, Code Editor when configured, Alex's
  portrait labelled “Alex”, and the bag. His profile popover is headed “Alex” and gives a short
  introduction and links to the full Discover brief at `#alex-profile`, rather
  than repeating the quotation, biography and requirements. Repair status belongs to the
  guided Playground rail and completion proof. Its labels
  distinguish “Code repaired” from “SQL repair applied”; neither substitutes
  for passing behavioral checks. The rail refreshes after a new run or proof.
- The guided lab's rail is sticky under the header. Once it sticks it condenses:
  the edit line and the next-lab link fold away and the lab name, stage
  links, and state chips share one row. `LabRail` reads the stuck state from
  an `IntersectionObserver` against a root shrunk by the header, and holds
  its flow footprint constant with a matching positive bottom margin so
  nothing under it moves. It measures its own height into
  `--labs-rail-height`, which the stage anchors add to their scroll margin.
- The rank comparison box chains vertical scrolling to the page and caps its
  height at the viewport below the sticky chrome, never a fraction of the
  screen.
- Shop opens with “Find what fits your world.” and one short lede:
  “Search for a product, compare the details, or ask Mosaic to help you choose.”
  Alex's full brief remains on Discover. Three large 4:3 photographs establish
  the story: headphones for focus, a chair for comfort, and the complete workspace.
  Each has a 20px step number, a stage label and fine rule above, then its caption
  below. Search spans the first two story columns underneath; “A little help
  choosing?” and Ask Mosaic align with the third. The invitation has no enclosing
  banner. The button retains its burgundy gradient, gold sparkles, inset highlight
  and metallic hover sheen. Shadow changes ease with hover, and pressing adds a
  small scale change. Reduced motion disables the sheen and movement. Example
  links use quiet underlines. On mobile, the search and invitation stack.
  Retrieve, Rank and Reason names and order come from the core mission manifest.
  Captions remain editorial.
  React/Vite and Aurora-backed data remain the application foundation.
  On mobile, the focusable image sequence scrolls horizontally using native
  scrolling. An active query or open Ask panel removes the image sequence.
- “Continue the workspace” adds a desk light, dock and laptop stand after
  Shop's first default Workspace browse page. It appears only without a query,
  open Ask panel, agent results, active filters or browse error. The product
  IDs come from `supporting_product_ids` in
  `data/media/workspace_collection.json`; cached API reads verify each returned
  identity before rendering ordinary catalog cards. Partial failure preserves
  loaded products and offers retry. Three desktop columns become one at 540px
  and below. This is a browse collection, with no compatibility guarantee or
  change to search ranking.
- Explore and Ask suggestions share the Hybrid retrieval request manifest: Clearer
  calls, Comfortable days, then More screen space. The retired synthetic exact-model
  shortcut has been removed from this shared list, including Hybrid retrieval.
  Ask shows the requests compatible with the current filters. The
  Hybrid retrieval's default is `clear-calls`; the chair request is a scoped
  shopping intent, not a replacement lab mission.
- The default Hybrid retrieval opens with canonical scene choices, Alex's portrait and
  request, and one labelled paper-plane send (Run Mosaic). It makes a real agent request; the three
  stages inspect saved records. A carried Shop event is read without rerunning
  it. If the agent searched several times, Retrieve and Rank share one selected
  search receipt. SQL, settings, citations and tool traces use disclosures.
- Every send on the Playground uses `MosaicRunButton`, sharing the catalog
  search's paper-plane motif. It is a 44px maroon-900 disc with a soft shadow, maroon-800
  under the pointer, a 16px plane, and a spinner while the request is in flight.
  The guided lab's query field uses it alone, named by its tooltip. Hybrid
  retrieval prints the current action beside the disc. Session & Memory prints the
  label beside the disc because the guide tells participants to choose
  **Ask Mosaic** and a second button sits next to it. No arrow, no stage marks;
  the status line under the card and the column states carry progress.
- Desktop retrieval columns share grid rows for headers, content, disclosure
  buttons and panels. Search details, Why the order changed and Answer and
  sources stay aligned, with each panel contained in its column. Open gutters
  and fine top rules separate Retrieve, Rank and Reason; no enclosing frame or
  vertical dividers surround the sequence. Waiting states and the closing
  invitation use the white canvas rather than nested tinted boxes.
- Hybrid retrieval Retrieve and Rank use `ResultProductCard` for the same set of up to
  three returned products: Retrieve orders them by recorded pre-rerank positions; Rank
  shows final order with before/final positions in the footer. Photography fills
  the card width in a 3:2 frame, with the image contained inside it. Category,
  native-sans product name, actual rating and review count, price and stock status
  sit below the image. These cards retain the shared maroon/cream tokens.
- `ProductAnswer` places each returned recommendation once, immediately after
  the first paragraph naming its title or model; unmatched recommendations
  append after the prose. Cards appear only when the answer prose is complete.
  Hybrid retrieval Reason, guided Reason, Ask Mosaic and saved memory turns share this
  renderer. Hybrid retrieval cards include distinct cited-source counts and links to
  the recorded search and rank; their main link opens product detail. Ask uses
  horizontal photo/copy cards, retaining product-drawer selection, catalog
  highlighting and the existing stock-aware Add to bag action.
- Hybrid retrieval displays streamed answer prose; Ask Mosaic uses `useTypewriterReveal`
  for paced prose, with completed answers mounted afresh shown immediately and
  reduced motion removing the pacing. An interrupted Hybrid retrieval run clears its
  answer and streamed prose while retaining partial candidates and tool receipts
  for diagnosis.
- Session & Memory introduces events, strategies and recall, then shows Alex's
  connection status and session controls. The desktop inspector puts conversation
  entry and stored events on the left, with a wider strategy/records column on
  the right. At 760px and below it stacks in the same DOM order: conversation,
  strategies, then recall. Collapsed events show a two-line message preview;
  opening the native disclosure reveals all messages, roles and the event ID.
- New session keeps the browser’s Alex and his memories. Start fresh rotates
  the private browser cookie, clears displayed sessions, records and answers,
  and begins a separate Alex. Earlier records remain stored; no shared Memory
  resource or other browser’s records are deleted.
- Four built-in memory choices—Facts, Preferences, Summaries and
  Past outcomes—show actual connection status, scope and processing steps, followed
  by returned records. Record details disclose IDs, namespaces and original
  content; strategy configuration and AWS references remain expandable. Empty
  records explain background processing separately from read errors. Examples
  fill the editable event field; only submission stores an event. Recall and
  Ask sit below the inspector with an explicit memory toggle, relevant records
  and a cited answer only after the visitor submits a request. Saved turns live
  in the collapsed “Earlier answers” disclosure; switching sessions or adding an
  event clears the current answer display. This surface teaches memory through conversation,
  without budget controls or a manual preference form.
- The footer’s Playground column and the tab strip share `PLAYGROUND_TABS` in
  `navigation.ts`: Hybrid retrieval, Scale & HNSW, Session & Memory. Browser
  titles use those same names. Catalog Studio is no longer linked or served.
  Discover, Shop and product pages share the charcoal footer, white Mosaic
  mark, subdued navigation and light keyboard-focus rings. Official payment
  artwork keeps its colors on compact white plates. Footer text is at least
  12px, including the demo disclosure and copyright.
- Bottom-of-page links follow the Playground tabs: Hybrid retrieval leads to Scale &
  HNSW, which leads to Session & Memory using the same heading, copy and arrow link.
- How it finds neighbors names HNSW beside a cream 3D sculpture: three floating
  layers, connected product types and a restrained maroon search path. Watch the
  search guides the visitor through the layers; pause, resume, replay, drag,
  keyboard and zoom controls remain available. Candidate cards appear at the
  end and identify illustrated product types. The caption states that this is
  not a recorded Aurora traversal. Hidden views pause; reduced motion uses
  fixed-camera steps; WebGL failure offers a flat graph and retry.
- The advanced instrument shares Hybrid retrieval's open layout: Index & storage,
  Recall & filters, and Scale experiments use section rules, light charts and
  progressive detail. Live probe controls remain available. Historical
  provenance starts collapsed while its warning remains visible. Mobile
  tables scroll within their regions and long index names wrap.
- The guided Playground opens with its title and query controls, then the
  sticky lab rail. The rank table's reading guide collapses when a recorded
  response is available. Run provenance names Aurora and the event ID; replay
  does not claim the request ran just now in this browser.
- Ask Mosaic shows the activity trail during retrieval. When the answer
  becomes available, the trail folds into “Steps and sources” so the answer
  leads while the searches, comparisons, evidence, and tool activity remain
  inspectable. Waiting and collapsed completed steps use compact rows; disabled
  disclosure buttons retain full text contrast. Nested product rows have no
  additional drop shadow and reflow against the panel width, not the viewport.
- Ask Mosaic's entry uses a short welcome and wrapping 44px starting pills.
  Each shows only its shared request label; selecting it submits the complete
  manifest query and filters. The white header, charcoal title, burgundy mark
  and plain white composer match the storefront. Full questions appear in the
  conversation after submission, alongside their actual results and sources.
- Ask is a desktop sidecar and becomes a fixed overlay at 1180px and below.
  The desktop grid and panel share `--ask-panel-width` (480–600px, with 35vw
  between). The catalog retains its 24–40px inline gutter at every open-panel
  width, and search questions wrap instead of being clipped to a single line.
  The overlay starts below the site header and reaches the viewport bottom;
  its title and close action remain visible after scrolling Shop. The `.page`
  entry animation uses `backwards` fill so its completed transform cannot
  become the containing block for fixed overlays.
- Navigation preserves the header, resets scroll and keyboard focus for a new
  page, and leaves the current page mounted for query changes.
- The guided Playground's agent run moves focus to one results area when submitted.
  Subsequent stream updates do not move focus or scroll the page. The service's
  latest stage and client elapsed time sit above a stable answer area. Retrieval
  details contain compact product rows; evidence and citations form a separate
  disclosure that opens after an error. Partial receipts never appear above
  the answer and push it down as they arrive.
- The guided lab's unnumbered Prove section reads verdict, then the maintainers' release baseline,
  then the package finale. While the baseline is held for an unmeasured
  revision it collapses to one disclosure line; opened, the full record and
  its provenance are there.
- Disclosures are native `<details>`, each with a hint of what is inside.
- Completion proof keeps failed checks visible and passing checks expandable.
  Both outcomes retain their receipts and can download the exact measured
  JSON. The final skill download packages the canonical skill folder and its
  relative references.

## Route architecture

The development-only `/catalog-preview` compares real-product samples without
replacing Shop or claiming a live search. Gallery keeps original photographs
and source disclosures in the editorial grid; Compare features aligns the same
requirements across products in a native table. Small screens scroll the table
within its labelled region, retaining row labels. Both layouts share the same
facts, filters and source text. Both layouts put photographs directly on clean
white without simulated lighting. In Compare, native-sans product names and
horizontal hairlines organize the columns without an enclosing frame, vertical
grid or tinted label column.

Documented fit, requirement mismatch and needs verification have distinct text
and icons as well as colors. Unknown evidence never becomes a negative feature
claim. Catalog membership comes from `data/real-catalog-examples.json`, with
reference samples identified separately. Filters narrow displayed specifications;
they do not reproduce production search or ranking. Historical rating aggregates
remain labelled as dataset values. The preview keeps its source payload outside
public assets and is excluded from the production route bundle.

The development-only `/design-studio` is an inspectable Precision Studio
alternative, not the storefront's adopted design. Its scoped paper/graphite
palette and sans-serif workspace contain local Discover, Shop and Playground
views. Requirement controls, sample filtering, shortlists, comparisons and an
optional source pane work with the reviewed public-catalog sample. The page
labels itself a prototype and the Playground a walkthrough; neither invokes
retrieval, reranking or an agent. Its own navigation replaces storefront chrome
only on this route, and production builds exclude it. Editorial Mosaic remains
the identity of the real application.

White is the adopted default across Discover, Shop, Playground and the product
sample preview. The temporary per-tab canvas switch has been removed.

| Path | Surface |
|---|---|
| `/`, `/discover` | Discover: Alex's room brief, three illustrated shopping needs, general search and category browsing; product inventories live in Shop |
| `/catalog` | Shop: faceted browsing, hybrid search, product cards, Ask Mosaic as a sidecar |
| `/products/:productId` | Product detail: media, catalog copy, price and availability, attributes, evidence excerpts |
| `/labs/retrieval` | Hybrid retrieval: read-only inspection of 01 Retrieve, 02 Rank, 03 Reason; one paper-plane send (Run Mosaic) starts a real run, and `scene` selects a canonical request |
| `/labs/retrieval?view=lab` | Guided Playground: Retrieve, Rank, Reason, Prove, lab rail and completion proof; URLs containing `example` or `run` also select this surface |
| `/mosaic-labs/hnsw` | Scale & HNSW: read-only index explanation, current Aurora substrate and attributed recorded measurements, including optional halfvec/binary comparisons |
| `/mosaic-labs/memory` | Session & Memory: AgentCore events, four built-in strategies and actual records; conversation and strategy columns lead to recall and Aurora-backed cited answers |
| `/mosaic-labs/hnsw?view=bench` | Full benchmark workbench: Index & storage, Recall & filters, Scale experiments; live probes, recorded experiments and projections carry distinct labels |
| `/mosaic-labs/studio` | Retired composition page; redirects to Hybrid retrieval |

`/playground`, `/mosaic-labs` and `/inspiration` redirect to Hybrid retrieval;
`/shop` redirects to Shop and `/labs/performance` redirects to Scale & HNSW.
Aliases preserve query parameters and section anchors, including filters, saved
search IDs and advanced-view choices. Existing guide and proof links keep the three stages and unnumbered Prove
section reachable without making it the default inspection surface.

## Interaction principles

- Search, agent, and lab results come from the typed API. There are no
  content constants or offline fallbacks in the renderer.
- PostgreSQL owns filtering, retrieval, and rank fusion; the interface shows
  what it did and never recomputes it.
- Per-arm ranks, fused rank, rerank, and final rank stay visually distinct.
- Citations and source revisions are inspectable from the answer.
- Technical detail discloses progressively without blocking the task.
- Controls keep stable dimensions while content loads.
- Ask follow-ups carry context from the prior grounded agent run. AgentCore
  facts and preferences are extracted from conversation under this browser's
  actor; starting a new session keeps that actor and its long-term memories.
  Memory supplies context; Aurora supplies product facts and citation evidence.
  The welcome portrait itself makes no claim about stored preferences.
- Scale distinguishes current index facts from recorded experiments. When
  attribution does not match the current catalog or code, the comparison stays
  historical. The new presentation does not establish new benchmark results,
  end-to-end latency or concurrent workshop capacity.
- Instrument size ratios compare representations within the same recorded
  artifact; they do not mix historical fp32 sizes with the live index. Build
  parameters are labelled recorded. Half precision is a choice to measure,
  not an unconditional recommendation. Live probe timing names its second,
  warm execution separately from the returned-neighbor measurement.

## Image boundary

`data/media/asset_labels_200.json` is the product-to-media contract for the
exact-photography set. Product media never serves as evidence for an
attribute.

Shop's workspace scenes are editorial, not catalog SKU portraits.
`data/media/alex-shop-story-v3.json` records the user-provided Grok reference
JPEGs, their WebP conversions and hashes. No crop or generative changes were
applied; the imagery establishes no product specifications.

Discover shares the room and headphone scenes from that source. Its additional
long-day chair and screen-space illustrations are recorded in
`data/media/alex-discover-studio-v1.json`, also converted from the user-provided
Grok reference. The room remains uncropped; need-card imagery fills 4:3 frames.
Shop's continuation instead uses the live products' catalog photography.
The Session & Memory and shared answer/retrieval-card extension reuses the
existing Alex portrait and product media; it introduces no shipping raster assets.

The default Workspace edit currently selects 71 products from that 200-product
photographed cohort through `data/media/workspace_collection.json`; the UI reads
the actual count from Aurora. Keyword search still uses the full 500,000-product
catalog. The catalog proposal under `data/curated/proposals/` has not been
promoted to the live CSV or embedding cache.

## Accessibility

- Focus uses the maroon palette, through `--focus` or the inspector's matching
  maroon rule.
- Reduced-motion rules cover entrance effects and smooth scrolling.
- Semantic headings, labelled regions, native forms and tables, and a
  screen-reader-only caption on the rank comparison.
- Status is never carried by color alone; a chip or badge also says its
  state in words.

## Enforcement

`ui/src/styles.test.ts` reads `styles.css`, `surfaces.css`, `discover.css`,
`playground.css`, and `inspector.css`, and fails when a referenced
custom property is undefined, when two palette tokens share a value, when a
hex-valued custom property outside the palette block is not an override of
a palette token, or when raw hex literals outside the palette block rise
above the ratchet, currently 252. Each check is proven against a fixture
that fails it. `npm run build` type-checks both configurations before
bundling.

## Review boundary

The Grok-reference Shop update received a **ship** review of its desktop and
mobile captures, with no fixes requested. This is the reviewer's verdict, not
separate user approval of the rendered result. The advanced instrument's fresh
finish review was **ship**, with no material fixes requested.
The Session & Memory and shared product-card extension received a fresh review
of six desktop/mobile captures for memory, Hybrid retrieval and Ask Mosaic. Its final
verdict was **ship**, scoring both requested memory fixes resolved: collapsed
event previews with disclosure markers and removal of the redundant recall
eyebrow. The verdict pass covered those
fixes; it does not imply user approval. Current evidence lives in
`.impeccable/review/{memory,pipeline,ask}-{desktop,mobile}.png`.
The Discover studio, its three needs and the Shop continuation received a
scoped **ship** review with no must-fix findings across desktop, mobile and
the user's 2048px viewport. The studio detector reported no findings.


### Product detail and recommendations

Product names, editorial headings, facts and controls share the native sans serif,
with their hierarchy expressed through size and weight. Product pages expose Save and the catalog warranty and shipping
values. The back link carries a validated Shop return path through successive
product visits. It never assumes the previous browser entry was Shop.

“Similar monitors” is a vector-ranked merchandising selection within the installed
photography. “Complete your setup” uses three category cards with capsule links,
explicit mounting/connection requirements and no compatibility guarantee. Product
cards keep short descriptions to two lines. Long-tail search cards use concrete
attribute summaries in place of repeated generated filler copy.
