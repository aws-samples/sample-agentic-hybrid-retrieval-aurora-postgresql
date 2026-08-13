# Category plates: prompts for the demo queries

`docs/image-generation-guide.md` covers the 120-product cohort, where each image
is bound to one product. This covers the other case: the corpus holds 499,880
products with no photograph, and the demo queries return them.

## 1. What is broken, measured

Every query the workshop actually uses was run against the live API
(`POST /api/search`, the parameters the UI sends: `limit` 12, `rerank` true, the
mission's own `filters` and `top_k`) and each returned product was passed through
`ui/src/media.ts` to see which file it resolves to.

| Query | Cards | Distinct photographs | Most repeated |
|---|---|---|---|
| Discover hero 1, Workspace | 12 | 4 | 6x |
| Discover hero 2, Performance | 12 | 4 | 5x |
| Discover hero 3, Travel | 12 | 5 | 4x |
| Lab 1 typo-recovery | 10 | 8 | 3x |
| Lab 2 rank-with-evidence | 10 | 8 | 2x |
| Lab 3 agentic-research | 6 | 5 | 2x |
| Canonical example 03, USB-C dock | 12 | 2 | 8x |
| Canonical example 04, mesh Wi-Fi | 12 | **1** | **12x** |
| Canonical example 15, sound masking | 12 | **1** | **12x** |

Across 268 audited cards, 28 resolve to a cohort plate, 197 to a keyword pool and
43 to a domain fallback. The distinct-photograph count above is generous: two
pool members are frequently two crops of one source, so the Workspace hero shows
three photographs, and at card size it reads as two.

Two failure modes, not one:

1. **Repetition.** `spread()` hashes a product id into a pool. A pool of 2 or 3
   assets over 12 cards cannot look like a catalog. Even a pool of 12 cannot: 12
   independent draws from 12 assets yields about 7.7 distinct values, so hashing
   alone never reaches 12 of 12. Guaranteed distinctness needs a grid-level
   assignment pass on top of a pool of at least 12.
2. **Wrong subject.** The pools are keyed by a regex over
   `title + category_path + brand + model`. `mesh-wi-fi-systems` matches nothing
   and falls through to the `consumer_electronics` domain asset, so twelve
   Wi-Fi routers are illustrated with a photograph of headphones. Twelve
   sound-masking devices get a photograph of an office chair. Twelve electric
   standing desks match `/stand/` and get a laptop riser.

Failure mode 2 is fixed in code (section 6). Failure mode 1 is now bounded by how
many photographs exist, which is what the rest of this document is for.

## 1a. What the code fix bought, measured

Same harness, re-run against the live API after the resolver rewrite, with the
production `ui/src/media.ts` bundled rather than reimplemented. All 21 queries
the workshop can reach: 3 Discover heroes, 3 lab missions, 15 canonical examples.

| Query | Cards | Distinct before | Distinct now | Worst repeat now |
|---|---|---|---|---|
| Discover hero 1, Workspace | 12 | 4 | 4 | 3x |
| Discover hero 2, Performance | 12 | 4 | 6 | 2x |
| Discover hero 3, Travel | 12 | 5 | 6 | 2x |
| Lab 1 typo-recovery | 10 | 8 | 6 | 2x |
| Lab 2 rank-with-evidence | 10 | 8 | 3 | 4x |
| Lab 3 agentic-research | 6 | 5 | 3 | 2x |
| Example D-004, mesh Wi-Fi | 12 | 1 | 1 | 12x |
| Example D-015, sound masking | 12 | 1 | 1 | 12x |

Two of those numbers went down, and that is the fix working. Lab 1 fell from 8
distinct to 6 because four of the eight were scraped screenshots of the wrong
product; the six that remain are all over-ear headphones. Example D-004 still
shows one photograph twelve times, but it is now a photograph of a mesh Wi-Fi
system rather than a photograph of headphones. Correctness first, then inventory.

Worst-repeat is now at its arithmetic floor everywhere: no photograph appears
more than `ceil(cards / pool)` times, so what is left to fix is the pool size.
Three categories no longer resolve to another category's product at all
(`treadmills`, `sound-masking-devices`, `lumbar-supports`); they hold the
per-domain slot until the neutral still-lifes in section 3 are generated.

## 2. Assets that must leave the repository

Zooming the pool members at full resolution shows the substrate is scraped
product-card screenshots, not generated photography:

| File | Defect | Cards affected in the audit |
|---|---|---|
| `curated/luma-770nc.webp` | legible **JBL** wordmark on the earcup | 7, four of them in the Travel hero |
| `curated/northstar-q45.webp` | legible **Soundcore** logo on the earcup | 1 |
| `curated/riser-laptop-stand.webp`, `catalog-stand.webp` | two crops of one photograph of a **MacBook**, Apple logo legible | 12 |
| `curated/sonora-xm5.webp` | baked-in heading text, "...u might also like" | 4 |
| `curated/auraluxe-h95.webp` | baked-in wishlist heart icon, product on a display stand | 2 |
| `catalog-keyboard.webp`, `curated/keysmith-keyboard.webp` | two crops of one photograph, wishlist heart baked in, dark walnut set that breaks the palette | 24 |
| `catalog-chair.webp`, `curated/formamesh-chair.webp` | two crops of one photograph, wishlist heart baked in | 15 |
| `catalog-monitor.webp`, `curated/vistaview-monitor.webp` | two crops of one photograph, wishlist heart, screen shows a photographic landscape | 0 in the audit, live in the pool |
| `curated/sennova-momentum.webp` | white letterbox band from the source card | 5 |

The three third-party marks are the blocking item. This is a public
`aws-samples` repository and the marks are attached to fictional products
("SonicCore OH-F355X"). They are the same defect `PROVENANCE.md` already records
for `auraluxe-h9.webp`; that pass caught the flagship set and missed
`curated/*`.

## 3. How many plates

A results page renders 12 cards, so a category needs 12 distinct photographs
before its first page can avoid a repeat. Cohort plates count toward that.

| Priority | Category | Have | Generate | Surfaces |
|---|---|---|---|---|
| 0 | per-domain neutral still-lifes | 2 | **1** | every category with no plate of its own |
| 1 | `quiet-keyboards` | 2 | **10** | Discover hero 1, D-005, D-013 |
| 1 | `road-running-shoes` | 2 | **10** | Discover hero 2 |
| 1 | `over-ear-headphones` | 6 | **6** | Discover hero 3, Lab 1, D-001, D-002 |
| 2 | `ergonomic-office-chairs` | 3 | **9** | Lab 2, Lab 3, D-011, D-012 |
| | **Priority 0, 1 and 2 total** | | **36** | |
| 3 | `treadmills` | 0 | 12 | D-009 |
| 3 | `sound-masking-devices` | 0 | 12 | D-015 |
| 3 | `lumbar-supports` | 0 | 12 | D-011 |
| 3 | `charging-docks` | 1 | 11 | D-003 |
| 3 | `mesh-wi-fi-systems` | 1 | 11 | D-004 |
| 3 | `mobility-tools` | 1 | 11 | D-010 |
| 3 | `electric-standing-desks` | 1 | 11 | D-014 |
| | **Priority 3 total** | | **80** | |

Priority 0 stops the wrong-subject fallbacks and covers the 56 live subcategories
no plate reaches. Two of the three are installed: `treadmills` no longer resolves
to a photograph of the Stride Pro. `ho-domain-neutral` is the one still open, so
`sound-masking-devices` and `lumbar-supports` still show the Forma chair — see
section 7 for why that one resisted four generations. Priority 1 and 2 make the
three Discover heroes and the three labs repeat-free at 12 cards; that is
measured, not projected, by replaying the audit with the authored plate counts
substituted in. Priority 3 finishes the canonical examples a participant can
reach from the search field, and takes all 21 audited queries to zero repeats.

`mechanical-keyboards`, `carbon-racing-shoes` and `trail-running-shoes` were on
this list and are not any more. `relatedCategories` in `ui/src/media.ts` lets
each borrow from an interchangeable neighbour, so the Priority 1 keyboard and
road-shoe plates already carry them: examples D-005 to D-008 reach 12 distinct
with no plates of their own. That removed 32 generations from this table.

All 115 plates and all 3 neutral still-lifes have a finished prompt in
`docs/category-plate-prompts.md`. Every subject within a category is a different
form factor, colour or material, because twelve prompts that differ only in
adjective produce twelve images that differ only in noise.

One generation still produces one plate, but one *message* orders several. Each
block in that document states the set, palette, style and constraint text once and
then carries a numbered `SHOT` per plate, each with its own target filename, so
every plate in a block is generated against byte-identical wording. That is what
makes a grid read as one catalog. 115 plates come to 18 blocks.

What a block must not become is a contact sheet. ChatGPT emits 1024x1024,
1536x1024 or 1024x1536, so a 2x2 sheet sliced into four plates leaves each at
512px, under what the card needs at device pixel ratio 2. Every block says so
explicitly. Check the returned images are separate files at the full size before
importing.

**Stopping early is legitimate.** Six plates in a category puts two copies of
each photograph in a 12-card grid, spread six cards apart; one plate puts twelve
copies of one. The curve is steep at the start and flat at the end, so the first
half of any category's list is worth much more than the second.

**Bundle cost.** `ui/src/media.ts` imports the whole manifest, so the 80 new
plates cost 19.8 kB raw and 3.65 kB gzipped in the browser bundle, none of which
the browser uses: the runtime reads `plate_id`, `category_key` and `installed`,
never `subject` or `extra_constraints`. That is not worth a generated
runtime-only manifest at 115 plates. It is worth one past roughly 300.

## 4. Getting a prompt

`docs/category-plate-prompts.md`. Copy a block, paste it, save the files. There is
nothing to run until the images are on disk.

That document holds the finished text for all 118 plates and its own progress
checklist. It was generated once from the manifest and then frozen, because
generating these plates is a one-time job and a script that renders text nobody
will re-render again is a step between the reader and the prompt. Editing a
prompt now means editing the markdown.

Two consequences worth knowing. `data/media/category_plates.json` stays the
authority for `plate_id`, `category_key` and `installed`, which is what the
runtime and the importer read; its `subject`, `framing` and `extra_constraints`
fields are now a record of what each plate was generated against rather than the
input to anything, so an edit there changes no prompt. And the shared body is
repeated 18 times instead of stated once, so a change to the palette or the
constraints has to be applied to all 18 blocks or the set stops matching.

The body is `docs/image-generation-guide.md` section 3 with two deliberate
changes:

- **The framing sentence is per plate.** Section 3 fixes every shot at
  three-quarter front, eye level, 65% fill. Twelve keyboards from one camera
  position read as twelve photographs of one keyboard. Six framings (`F1` to
  `F6`) are defined in the manifest and assigned per plate, so a grid varies by
  camera as well as by product.
- **Per-category constraints are appended.** Generic "no text, no logos" does not
  survive contact with a keyboard, whose keycaps carry legends by default, or
  with headphones, where the earcup is exactly where the model composites a
  maker's mark. Each category adds two explicit lines; these are the constraints
  that failed in the assets in section 2.

Everything else, the set, palette, style and the base constraints, is
byte-identical to the cohort prompt.

## 5. Naming, import, provenance

Plate filenames are `<plate_id>-catalog-3x2`, where `plate_id` is
`<domain>-<category>-plate-NN`:

```text
ho-quiet-keyboards-plate-01-catalog-3x2.png     generated, in ~/Downloads/batch
ho-quiet-keyboards-plate-01-catalog-3x2.webp    runtime, 1200x800
```

Plate numbering always starts at 01. The `plate-` token is what separates this
namespace from the cohort's product-bound `ho-quiet-keyboards-01-catalog-3x2`,
so the two never collide even where a category holds both.

```bash
uv run python scripts/import_generated_images.py --source ~/Downloads/batch --dry-run
uv run python scripts/import_generated_images.py --source ~/Downloads/batch
```

The importer now validates against both manifests, crops to 3:2, resizes to
1200x800 and writes WebP at quality 88, the same path the cohort images take. A
filename in neither manifest is still refused.

**Renaming a batch.** The generator names its own downloads, so a batch of ten
arrives as ten files that must be renamed to the `save as` line of the shot they
came from. The ordered target list for every category is the progress checklist
at the top of `docs/category-plate-prompts.md`. Order within a category is the
cheap kind of mistake: plates are not bound to products, so swapping plate-04 and
plate-05 changes no card, only the accuracy of that plate's recorded subject line,
which matters when a plate has to be regenerated. Crossing categories is the
expensive kind, and every block covers one category so it cannot happen inside
one.

**Provenance.** A plate is verified to show the right category, the Mosaic set,
and no third-party mark. It is not a photograph of the specific product whose
card it appears on. `data/media/asset_labels_120.json` is the only manifest that
carries product-bound provenance. Nothing in the UI or in `PROVENANCE.md` may
describe a plate as product-verified.

**Check every generation before importing:** the mark on the earcup, the legends
on the keycaps, the logo on the shoe, a screen showing a UI. Regenerate rather
than accept. That check is the whole reason section 2 exists.

## 6. What the plates need from the code

Files alone change nothing. The wiring is in place; importing a plate now puts it
on a card with no further code change.

1. **Category-keyed pools.** Done. `ui/src/media.ts` matches the API's
   `category_key` exactly and unions cohort plates with category plates for that
   key. The regex table is deleted, not deprecated. Each cohort image registers
   under both the bare subcategory slug and the fully qualified
   domain-family-subcategory slug, because the service emits the qualified form
   only when two domains share a subcategory name; "Portable Monitors" is the one
   live collision and a slug-only join silently dropped its photograph.
2. **Grid-level assignment.** Done. `productImageMap()` places product-bound
   photography first, reserving each file, then gives every remaining row the
   least-used photograph in its category pool. An unused plate always wins, so a
   pool of 12 fills a 12-card grid with no repeat; past exhaustion the surplus
   spreads evenly, bounding any grid at `ceil(rows / pool)` copies of one file.
   Callers pass `imageSrc` into `ProductCard`, so the six list surfaces, the
   search top-pick thumbnail and the Ask Mosaic rail all agree on what a product
   looks like.
3. **Only the generated namespace is trusted.** `image_url` from the database is
   honoured only under `/assets/images/mosaic/`. `data/full/product_image_urls.csv.gz`
   maps 499,973 products to eight scraped screenshots and
   `scripts/materialize_image_urls.py` loads that column, so without this one run
   of a documented script would put a photograph of a MacBook on 38,750 rows and
   bypass the pools entirely.
4. **Import records itself.** `scripts/import_generated_images.py` accepts both
   plate arrays, and writes `installed: true` plus the runtime WebP's sha256 back
   into the manifest. The runtime serves only installed plates, so a plate that
   is generated and imported but not recorded would never reach a card.
5. **Retire the tainted assets** from section 2. Still open, and it is not a
   deletion: `tests/test_media_assets.py` asserts every mapped URL exists on disk
   and pins three exact counts and `rows == 500_007`, and no producer script for
   `product_image_urls.csv.gz` exists. That column needs a producer and a
   regeneration without the 21 `curated_photorealistic` rows before the files can
   go. No `ui/src` code path reaches them today.

## 7. Which generator, measured

`stability.stable-image-ultra-v1:1` on Bedrock in `us-west-2` was tried against
these prompts. `amazon.nova-canvas-v1:0` is present in `us-east-1` but returns
`ResourceNotFoundException`: marked Legacy by the provider and not invoked in the
last 30 days.

| Prompt kind | Result | Evidence |
|---|---|---|
| Neutral still-life, single soft-goods object on a named ledge | usable | `ce-domain-neutral`, `rf-domain-neutral` installed |
| Neutral still-life naming a cable, a tray, or a whole desktop | fails | "brushed champagne tray" rendered a glass of champagne; "braided-fabric cable" rendered a braided cord with a gold clasp; "a desktop filling the frame" rendered a serving board on cool white marble, four times, breaking the palette rule |
| Product plate | fails | `ho-quiet-keyboards-plate-01` came back with pseudo-legends on the keycaps ("SHENO", "DEREN"); `rf-treadmills-plate-01` came back with the wordmarks "GOIOROK" and "V8030" and a numeric console |

Two conclusions the 115 product plates depend on. First, Stability's dedicated
`negative_prompt` field does not suppress any of this: moving the whole CRITICAL
CONSTRAINTS block into it changed nothing at a fixed seed, and adding `marble,
veined stone, white stone` still produced marble. Second, invented wordmarks on
fictional products are worse in a public `aws-samples` repository than the
repetition they would fix, which is the same defect section 2 is about.

The 120 cohort images do not have this problem: `ho-quiet-keyboards-01` has
genuinely blank keycaps. So the product plates go to whichever tool produced the
cohort, and the constraint lines in the manifest exist precisely because they are
the ones that fail when they are absent.
