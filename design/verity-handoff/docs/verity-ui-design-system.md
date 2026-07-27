# Verity UI — design system & screen set (v1, Jul 24 2026)

Concept-screen design language for **DAT410**, the 2026 RIV session on hybrid retrieval with Aurora PostgreSQL. Inherits the Traceline v2 palette and motifs (paper/ink/red-thread, Fraunces/Inter/Plex Mono) and re-points them at the Verity narrative (INC-2047 / CHG-1842 incident forensics).

Seven self-contained HTML mockups, cross-linked through a shared nav. Every file is standalone — no build step, no shared stylesheet, no external JS.

| # | File | Screen | Interactive |
|---|---|---|---|
| 01 | `verity-lab.html` | Retrieval comparison lab — four arms beside the fused column | archetype presets, principal, rerank, per-row receipt expand |
| 02 | `verity-plan.html` | Query-plan X-ray — index nodes, ACL gates, stage budget, Aurora strip | `ef_search` knob, SQL ⇄ EXPLAIN toggle |
| 03 | `verity-fusion.html` | RRF anatomy — contribution bars, naive score-sum comparison | k + three weight sliders, fusion mode, rerank overlay |
| 04 | `verity-ask.html` | Ask & decompose — plan chips, six-tool thread, receipt, timeline | principal switcher |
| 05 | `verity-eval.html` | Evaluation lab — per-archetype ablation, traversal judged separately | static |
| 06 | `verity-graph.html` | Evidence graph & verdicts — BFS traversal, canonical vs inferred | depth, edge class, principal |
| 07 | `verity-scale.html` | Scale & capacity — HNSW sizing, overfetch, build strategy | corpus, selectivity, `ef_search`, instance, Optimized Reads |

---

## 1. Color

### 1.1 Core tokens

Declared in `:root` on every file. Identical across all seven (`--clay` omitted from `verity-ask.html`; `--amber` is `verity-scale.html` only).

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#FAF4EC` | page background, inset wells, chip backgrounds |
| `--ink` | `#211C16` | primary text, dark panels, active segmented-control fill |
| `--ink-soft` | `#584F45` | secondary text, body copy in cards |
| `--muted` | `#94897C` | tertiary text, axis labels, disabled/absent states |
| `--hair` | `#E9DFD2` | hairline borders, dashed dividers, axis lines |
| `--red` | `#C13A26` | primary accent — evidence thread, category labels, active chips |
| `--red-deep` | `#9E2F1E` | accent text on light washes, fused ranks, hover |
| `--wash` | `#FBEDE8` | red tint — highlights, restricted badges, "hot" advisories |
| `--green` | `#2E7D54` | positive/confirmed states, rank improvement, exact match |
| `--blush` | `#F7E2D6` | radial background bloom only |
| `--card-bd` | `rgba(33,28,22,.07)` | card border (softer than `--hair`) |
| `--clay` | `#DE9C7C` | **fill/stroke only** — vector arm, inferred edges, secondary bars |
| `--amber` | `#8A5A2B` | text on clay-tinted backgrounds (`#FDF1E9`) |

### 1.2 Extended surfaces

Used inline; promote to tokens if a fourth screen needs them.

| Hex | Use |
|---|---|
| `#EEF6F1` | green wash — `not_affected`, "good" advisories, positive stat tiles |
| `#FDF1E9` | clay wash — `evidence_supports` verdict chips |
| `#fff` | card surface (distinct from `--paper`; the paper/white pairing is what gives cards their lift) |

### 1.3 Dark panel (SQL / EXPLAIN)

Background `--ink`. Syntax palette tuned for the warm neutral, not a generic dark theme.

| Hex | Role |
|---|---|
| `#EFE7DC` | body text |
| `#F2B8A9` | keywords, panel eyebrow label |
| `#A9D3B9` | function names |
| `#E8C9A8` | bind parameters (`:q`, `:principal`) |
| `#9A8E80` | comments, footnotes |
| `#C9BCA9` | inactive segmented-control label |

### 1.4 Semantic color rules

These are meaning-bearing, not decorative. Changing them changes what the screen asserts.

- **Red = the thread of evidence**, not danger. It marks what the system found and followed. A red chip is not a warning.
- **Green = a negative finding confirmed** (`not_affected`, `change_ruled_out` context, rank improvement, exact match). Ruling something out is a positive result.
- **Clay = the vector/inferred family.** Semantic arm in every chart, inferred edges in the graph, overflow-beyond-cache in the memory bar. Consistently "derived, not asserted."
- **Muted + dashed = absent, not failed.** An arm that returned nothing is dashed and muted; it never reads as an error.
- **`--clay` is never a text color on a light surface** (2.29:1 against white). It is a fill or a stroke. Text over clay is `--ink` (7.37:1); text near clay is `--amber`.

---

## 2. Typography

Three families via Google Fonts, each with a system fallback so the set degrades gracefully offline.

| Family | Stack | Use |
|---|---|---|
| **Fraunces** | `Fraunces, Georgia, serif` | display headlines only (`h1` 33px/600, `em` italic 500 in `--red-deep`), plus the synthesized answer lead (17.5px) |
| **Inter** | `Inter, system-ui, -apple-system, "Segoe UI", sans-serif` | all UI text, body copy, captions |
| **IBM Plex Mono** | `"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace` | identifiers, scores, queries, labels, SQL, table data |

### Scale in use

| Pattern | Spec |
|---|---|
| Hero headline | Fraunces 600 · 33px · `-.01em` · 26px below 780px |
| Hero deck | Inter 400 · 14px · `--ink-soft` · max-width 660–700px |
| Section eyebrow (`.klabel`) | Plex Mono 600 · 10px · `.16em` · uppercase · `--red` |
| Wordmark | Plex Mono 600 · 12.5px · `.24em` |
| Pill / chip | Plex Mono 500 · 10.5px |
| Table header | Plex Mono 600 · 9.5px · `.11em` · uppercase · `--muted` |
| Table cell | Plex Mono 500 · 11.5px · `--ink-soft` |
| Stat value | Plex Mono 600 · 19–20px · `--ink` |
| Diagram node label | Plex Mono 600 · 11.5px; kind label 8.5px/`.11em`/`--red` |
| SQL panel | Plex Mono 400 · 10.6px · line-height 1.58 |

**Rule:** anything a database would return — an identifier, a score, a latency, a key — is monospace. Anything a person wrote is Inter. Anything the session asserts is Fraunces. Mixing these is the fastest way to make the set feel generic.

---

## 3. Form

### Radius

| Value | Applied to |
|---|---|
| 16px | cards (`.card`), dark SQL panel |
| 12px | nested cards, stat tiles, advisory rows |
| 10px | segmented controls, omnibox, buttons |
| 8–9px | small chips, graph nodes (SVG `rx="9"`) |
| 6px | signal chips, `kbd`, verdict badges |
| 999px | pills, progress bars |

### Elevation

Only three shadows exist. Do not invent a fourth.

```css
/* inset tiles, stat cards */
box-shadow: 0 1px 2px rgba(33,28,22,.04);

/* standard card */
box-shadow: 0 1px 2px rgba(33,28,22,.04), 0 10px 30px rgba(33,28,22,.06);

/* dark panel — deeper, warmer */
box-shadow: 0 1px 2px rgba(33,28,22,.08), 0 12px 34px rgba(33,28,22,.16);
```

### Background

```css
background: var(--paper)
  radial-gradient(1100px 700px at 94% -10%, var(--blush) 0%, rgba(247,226,214,0) 62%)
  no-repeat;
```

Identical on all seven screens — it is what makes them read as one set when clicked through.

### Layout

- Container `max-width: 1280px`, padding `0 26px`
- Card padding `14–16px`; hero block `30px 0 18px`
- Grid gaps `12px` (tiles) / `14–18px` (cards)
- Wide diagrams and tables sit in `.hscroll` wrappers with an explicit `min-width` rather than reflowing — a query plan that rewraps is a query plan you can't read
- Breakpoints: `900px` (dual → single column), `780px` (hero size, omnibox wraps full-width). Screens with denser grids add `860/960/980px`.

---

## 4. Components

### Chrome (all screens)

Wordmark with circle-and-thread glyph → mono omnibox showing the live query with `⌘K` → nav (Ask · Lab · Fusion · Plan · Eval · Graph · Scale, active item underlined 2px `--red`) → principal pill + avatar. The omnibox is a **display** of current state, not an input.

### `.klabel`

The workhorse. Mono, uppercase, letterspaced, `--red`. Labels every card, column, and panel. Set to `--muted` when it labels a control rather than content.

### `.pill`

Read-only metadata: run IDs, latencies, counts, endpoint paths. White, hairline border, mono 10.5px. Never interactive.

### `.seg`

Segmented control for mutually exclusive state. Active = `--ink` fill, paper text. This is the only "filled dark" element outside the SQL panel.

### `.chip`

Interactive preset selection (archetype queries). Active = `--red` fill, white text. Distinct from `.seg` — chips choose *content*, segments choose *mode*.

### Signal chips (`.sig .s`)

Per-arm rank badges on fused results: `T #1`, `V #4`, `F —`. Present = solid hairline; absent = dashed + `--muted`. The `RRF` score chip is bolded `--ink`; the rerank chip is `--red-deep`.

### Bars

- **Contribution bars** — segmented, colored by arm (red/clay/green), width ∝ score share
- **Stage budget** — width ∝ √ms, so a 1,240ms stage doesn't erase a 7.9ms one; the √ is disclosed in a pill
- **Memory bar** — `--red` up to capacity, `--clay` for the overflow beyond it

### SVG diagram conventions

- Canonical relationships: solid `--red` 1.6px + arrowhead marker
- Inferred: dashed `--clay` (`4 3`) + distinct arrowhead, confidence in the label
- Flowing/animated thread: dashed 1.5px, `stroke-dashoffset` animation, **gated behind `prefers-reduced-motion`**
- Edge labels: mono 9.5px on a `--paper` backing rect with 28%-opacity stroke
- Nodes: 178×42 `rect`, `rx="9"`; seed nodes get 2.2px `--red` border; restricted nodes get `--wash` fill + dashed border
- Anchors computed from relative position (right→left, or bottom→top when columns align) — never hand-placed

---

## 5. Data-display conventions

Domain rules. These are the reason the set is credible in front of an expert audience, and they override aesthetic preference.

1. **Ranks fuse; raw values never do.** `ts_rank`, cosine distance, and trigram similarity appear only as diagnostics, visually subordinate to rank position. The naive score-sum toggle exists specifically to show why (intended 67/33 → effective 93/7).
2. **Aurora score and model score stay separate.** RRF and rerank are always distinct columns/chips. There is no blended "final score" anywhere in the set, and no confidence ring.
3. **No score is presented as a probability.** Every footer carries "scores are diagnostics, not probabilities."
4. **Absence is silent.** ACL-filtered evidence does not appear dimmed, greyed, or annotated. It is gone. Only the explanatory caption discusses it.
5. **An empty arm is a legitimate result.** Rendered as "0 candidates — arm contributes zero," never as an error state.
6. **Illustrative numbers are labeled at the point of use**, not just in the footer — modeled projections get a dashed-border note naming the release gate that will replace them.
7. **Formulas are shown expanded** where they'd otherwise be magic: `RRF = 2/(60+1) + 1/(60+3) + 1/(60+1) = 0.06505`.
8. **Every interactive control changes something real.** No control is decorative; where one would appear inert in a given state (Optimized Reads at lab scale), the copy names the threshold at which it starts to matter.

---

## 6. Accessibility

Measured WCAG 2.1 contrast ratios for the pairs actually used:

| Pair | Ratio | Level |
|---|---|---|
| `--ink` on `--paper` | 15.47 | AAA |
| `--paper` on `--ink` (dark panel) | 15.47 | AAA |
| SQL body `#EFE7DC` on `--ink` | 13.79 | AAA |
| SQL keyword `#F2B8A9` on `--ink` | 9.82 | AAA |
| `--ink` on `--clay` (stage bar) | 7.37 | AAA |
| `--ink-soft` on `--paper` | 7.34 | AAA |
| `--red-deep` on `--wash` | 6.38 | AA |
| `--red` on white | 5.38 | AA |
| white on `--red` | 5.38 | AA |
| SQL comment `#9A8E80` on `--ink` | 5.28 | AA |
| `--amber` on `#FDF1E9` | 5.29 | AA |
| `--green` on white | 5.03 | AA |
| `--red` on `--paper` | 4.93 | AA |
| `--green` on `#EEF6F1` | 4.57 | AA |
| `--muted` on white | 3.43 | AA-large only |
| `--muted` on `--paper` | 3.14 | AA-large only |
| `--clay` on white | 2.29 | fails — fill/stroke only |

**Constraints that follow:** `--muted` is restricted to ≥11px supporting text (captions, axis labels, footers) and never carries information unavailable elsewhere. `--clay` never renders text on a light surface. Color is never the sole channel — arms carry letter prefixes (`T`/`V`/`F`), edge classes carry dash patterns and explicit provenance labels, rank deltas carry `▲`/`▼` glyphs alongside green/red.

Motion is limited to one dashed-thread animation, wrapped in `prefers-reduced-motion: reduce`.

---

## 7. Narrative constants

Keep these identical across screens — drift here is what makes a set look assembled rather than designed.

**Corpus:** 12,011 documents · 48,226 ready chunks · 1,024-d · `us.cohere.embed-v4:0` (`output_dimension` pinned explicitly on both ingest and query) · rerank `cohere.rerank-v3-5:0` · synthesis `claude-sonnet-5` via Converse.

**Fusion:** weighted RRF, text : vector : fuzzy = 2 : 1 : 1, k = 60, pool 24/arm, absent arm contributes zero, `DISTINCT ON (evidence_id)` for one strongest passage.

**Retrieval:** HNSW m=16, `ef_construction` 64, `ef_search` 40, `iterative_scan = relaxed_order` set transaction-locally via `retrieval.configure_ann_runtime`. Trigram threshold 0.30 on identifiers and titles only.

**Run receipts:** `rr_9b41d7` (full agent run), `rr_9b41d4` (semantic-symptom), `rr_9b41d5` (exact-change), `rr_9b41d6` (fuzzy-change-id), `rr_9b41d2` (customer-impact).

**Timings:** SQL 7.9ms (exact+FTS 2.3 · vector 3.8 · fuzzy 1.1 · fuse 0.7) · rerank 74ms · synthesis 1,240ms · agent total 1,356ms · shared hit 362, read 0.

**Fixtures:** `INC-2047` (Sev-2, checkout writes) · `CHG-1842` (ordinary `CREATE INDEX`, confirmed cause) · `CHG-1838` (ruled out) · `LOCK-2047-001/002` (blocked writer 4182/4210 ← blocking 3944) · `CASE-7419` Acme Retail (affected) · `CASE-7421` (restricted, affected — visible only to `support-lead`) · `CASE-7424` Zenith Corp (not affected) · `RB-017` (concurrent index builds) · `COMMIT-4471` (RCA by May 21) · `CHG-1907` (rebuild CONCURRENTLY) · `INC-1980` (2025 look-alike, the cross-arm consensus artifact rerank demotes).

**Timeline:** 09:17 build starts → 09:19 first lock snapshot → 09:24 Sev-2 declared → 09:38 Acme reports → 09:51 build cancelled (~34 min of blocked writes) → May 20 RB-017 adopted.

**Principals:** `workshop` (default) and `support-lead` (sees `CASE-7421`).

---

## 8. Implementation notes

- **Self-contained.** One file per screen; all CSS and JS inline. Drop the seven in a folder and the nav works.
- **No browser storage.** No `localStorage` / `sessionStorage` anywhere — all state is in-memory JS objects.
- **Fonts.** Google Fonts with system fallbacks. Acceptable for concept mockups; **the shipped React workbench forbids remote fonts**, so these files must not be ported in as-is. Substitute a local or system stack at that point.
- **Derived, not hardcoded.** Fused orderings, RRF sums, BFS reachability, capacity figures, and contrast-sensitive states are computed at runtime from small data tables at the top of each script. Editing a rank array updates every dependent number and bar. This is deliberate: hardcoded result tables drift out of agreement with their own formulas (the failure mode in the earlier prototype pass, where a published RRF value of 0.0491 didn't match its own stated inputs of 0.06505).
- **Verification.** Each file passes tag-balance parsing and `node --check` on its inline script; model outputs are spot-checked for monotonicity and plausibility before shipping.

## 9. Not yet built

Two screens designed but not produced, using the same system: **ingestion & projection** (`is_current` versioning, embedding backlog, drift, re-embed on model change) and **degradation console** (Bedrock throttle → extractive fallback, citation-validation failure, INVALID index cleanup).

When these graduate from concept screens into the actual React workbench, the sidebar IA and per-kind color coding from the alternate prototype pass are worth revisiting — that structure suits a persistent tool, whereas this set is built for a linear on-stage walk.
