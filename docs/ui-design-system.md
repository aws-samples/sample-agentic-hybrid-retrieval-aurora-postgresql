# Mosaic UI design system

What the storefront and the Playground actually look like, why, and what
enforces it. This is the incumbent design record. Shared tokens come from
`ui/src/styles.css`; surface behaviour comes from `surfaces.css`,
`discover.css`, `inspector.css`, `instrument.css`, and `reason-products.css`.
`workspace-continuation.css` styles the supporting Shop collection. Where a
number is a measurement, the section says how it was measured.

## Direction

Mosaic is a premium product catalog that is also an L400 inspection tool.
Product photography and an editorial serif carry the shopping context; a
grotesk carries the interface; monospaced type carries SQL, identifiers,
run ids, and measurements, and nothing else. The canvas is ivory, the accent
is maroon, and the two never trade places: maroon is for actions, the active
state, and flagged boundaries, not for large fills.

Alex, a software engineer building a home office for coding, calls and focused
work, connects the shopping and inspection surfaces. Monitor, chair and
headphones imagery establishes that context without changing the lab missions.
The interface is not patterned after a named retailer. The main canvas stays
plain; the existing Ask button retains its maroon gradient and gold sparkle.

## Palette

The palette block owns shared color roles. Aliases point at their source with
`var()` rather than repeating a value, so no two palette roles share a hex.
Remaining surface literals are bounded by the stylesheet test's ratchet.

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
| `--shadow` | `0 16px 36px rgb(43 13 19 / 8%)` | shared elevation |

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
  headlines, Pipeline and Scale introductions, product names, prices, and
  the large benchmark figures. The advanced instrument uses Newsreader for
  its introduction and section titles, with Schibsted controls and detail.
- Interface: Schibsted Grotesk, weights 400 to 700. Navigation, controls,
  cards, answers, and lab controls. “A little help choosing?” stays sans serif.
- Technical: the platform monospace stack. SQL, source references, run ids,
  scores, and settings values only. Monospace is never a costume for
  "technical".

The guided lab uses this scale: display `clamp(36px, 3.6vw, 54px)`, stage
headings `clamp(30px, 2.6vw, 40px)`, section headings 19px, lead 17px, body
15px, detail 13px, micro 12px, and monospace 13px. Uppercase labels sit at
micro size with 0.05em tracking.

Pipeline and Scale use an editorial introduction at `clamp(40px, 4.3vw, 64px)`
with 18px supporting copy, followed by sans serif inspection content. Alex's
circular Pipeline portrait is 128px on desktop, 112px under 1000px, and 88px
under 760px; the request and single Play action stay prominent on mobile.

## Geometry

- Site header 70px, 66px at 900px and below, 62px at 460px and below, sticky
  at the top.
- Page width 1480px; the shell is `min(92vw, 1480px)`.
- Radius 8px for product imagery and cards, 16px for Shop hero imagery and
  Alex's brief, 6px for inner details, 12px for inspector callouts, and 999px
  for Shop search, chips and Ask actions.
- Boundaries are 1px. Maroon on a boundary means active or flagged. The
  only rule thicker than 1px is the 2px left rule on a blockquote or a
  failed check, which is a quotation mark, not an accent.
- The shared shadow is offset and blurred. Shop's Ask action and sidecar keep
  their existing local elevation; Pipeline and Scale use rules and warm fills.

## Chrome behaviour

- Discover opens with “How a room learns you.” A full, uncropped 4:3 room
  photograph sits left of Alex's brief on a warm cream surface. His portrait
  is 88px on desktop, 72px at intermediate widths and 80px on mobile. The brief
  names the desk and laptop already in place, with headphones, chair and
  monitor still to choose. The studio stacks at 760px and below.
- Three illustrated needs follow in manifest order: Clearer calls, Comfortable
  days and Room to code. Each gives Alex's situation, “What matters” and a pill
  link carrying the same scoped query as Shop. Category pills carry only the
  category filters. One general search field uses the shared readiness API
  count; `discoverData` fetches no catalog products. Discover ends with a Shop
  invitation, without an inventory grid, numeric progress or lab instructions.
  Its disclosure identifies Alex as fictional and the imagery as illustrative.
- The site header contains navigation, Code Editor when configured, Alex's
  portrait with “Welcome, Alex!”, and the bag. Repair status belongs to the
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
- Shop pairs its headline with Alex's warm cream brief and 64px desktop
  portrait. Three large, uncropped 4:3 room photographs from the user-provided
  Grok reference follow: headphones for focus, a chair for comfort, and the
  complete workspace. A numbered Retrieve, Rank, Reason rail sits above them;
  stage names and order come from the core mission manifest. Captions remain
  editorial, without exercise instructions. Round search spans the first two
  desktop columns below the images; the Ask invitation sits under the third.
  The maroon paper-plane send control, example pills, sans “A little help
  choosing?” and gold-sparkle Ask button retain their established treatments.
  React/Vite, Aurora-backed data and Newsreader/Schibsted remain the system.
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
- Explore and Ask suggestions share the Pipeline request manifest: Clearer
  calls, Comfortable days, Room to code, then the Mosaic Atelier 32 exact-model
  control. Ask shows the requests compatible with the current filters. The
  Pipeline's default remains `room-for-code`; the chair request is a scoped
  shopping intent, not a replacement lab mission.
- The default Pipeline opens with canonical scene choices, Alex's portrait and
  request, and one Play button. Play makes a real agent request; the three
  stages inspect saved records. A carried Shop event is read without rerunning
  it. If the agent searched several times, Retrieve and Rank share one selected
  search receipt. SQL, settings, citations and tool traces use disclosures.
- Pipeline's Reason stage shows up to the first three partial candidates as
  “Under consideration”, explicitly labelled with the displayed and retrieved
  counts. The answer's recommendation set replaces that preview with product
  photographs, prices, distinct cited-source counts and product-detail links.
  The shared `ReasonProducts` gallery uses three desktop columns and two at
  760px and below; the guided Reason stage uses the same final gallery.
- Pipeline and Ask Mosaic share `useTypewriterReveal` for paced answer prose.
  Completed answers mounted afresh render immediately. Reduced motion removes
  both the typewriter pacing and the gallery's image entrance effect. An
  interrupted Pipeline run clears its answer and streamed prose while retaining
  partial candidates and tool receipts for diagnosis.
- The advanced instrument shares Pipeline's open layout: Index & storage,
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
  inspectable.
- Ask is a desktop sidecar and becomes a fixed overlay at 1180px and below.
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
- The guided lab's Stage 04 Prove reads verdict, then the maintainers' release baseline,
  then the package finale. While the baseline is held for an unmeasured
  revision it collapses to one disclosure line; opened, the full record and
  its provenance are there.
- Disclosures are native `<details>`, each with a hint of what is inside.
- Completion proof keeps failed checks visible and passing checks expandable.
  Both outcomes retain their receipts and can download the exact measured
  JSON. The final skill download packages the canonical skill folder and its
  relative references.

## Route architecture

| Path | Surface |
|---|---|
| `/`, `/discover` | Discover: Alex's room brief, three illustrated shopping needs, general search and category browsing; product inventories live in Shop |
| `/catalog` | Shop: faceted browsing, hybrid search, product cards, Ask Mosaic as a sidecar |
| `/products/:productId` | Product detail: media, catalog copy, price and availability, attributes, evidence excerpts |
| `/labs/retrieval` | Pipeline: read-only inspection of 01 Retrieve, 02 Rank, 03 Reason; one Play starts a real run, and `scene` selects a canonical request |
| `/labs/retrieval?view=lab` | Guided Playground: Retrieve, Rank, Reason, Prove, lab rail and completion proof; URLs containing `example` or `run` also select this surface |
| `/mosaic-labs/hnsw` | Scale & HNSW: read-only index explanation, current Aurora substrate and attributed recorded measurements, including optional halfvec/binary comparisons |
| `/mosaic-labs/hnsw?view=bench` | Advanced instrument: Index & storage, Recall & filters, Scale experiments; live probes, recorded experiments and projections carry distinct labels |
| `/mosaic-labs/studio` | Studio: real catalog objects as a composition study, not a recommendation |

`/playground` and `/mosaic-labs` redirect to the Pipeline; `/labs/performance`
redirects to Scale & HNSW. Existing guide and proof links keep the four-stage
lab reachable without making it the default inspection surface.

## Interaction principles

- Search, agent, and lab results come from the typed API. There are no
  content constants or offline fallbacks in the renderer.
- PostgreSQL owns filtering, retrieval, and rank fusion; the interface shows
  what it did and never recomputes it.
- Per-arm ranks, fused rank, rerank, and final rank stay visually distinct.
- Citations and source revisions are inspectable from the answer.
- Technical detail discloses progressively without blocking the task.
- Controls keep stable dimensions while content loads.
- Ask follow-ups carry context from the prior grounded agent run. Alex's
  welcome is a shopper persona, not stored user preferences; AgentCore
  preference memory is not implemented.
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
The Reason extension received a scoped **ship** review of the desktop and
mobile Pipeline captures; the guided gallery and motion paths were reviewed
from code, with runtime checks performed separately.
The Discover studio, its three needs and the Shop continuation received a
scoped **ship** review with no must-fix findings across desktop, mobile and
the user's 2048px viewport. The studio detector reported no findings.


### Product detail and recommendations

Product names and editorial headings use Newsreader; facts and controls use
Schibsted Grotesk. Product pages expose Save and the catalog warranty and shipping
values. The back link carries a validated Shop return path through successive
product visits. It never assumes the previous browser entry was Shop.

“Similar monitors” is a vector-ranked merchandising selection within the installed
photography. “Complete your setup” uses three category cards with capsule links,
explicit mounting/connection requirements and no compatibility guarantee. Product
cards keep short descriptions to two lines. Long-tail search cards use concrete
attribute summaries in place of repeated generated filler copy.
