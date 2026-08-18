# Mosaic image generation guide

Everything needed to produce the workshop's photography: exact sizes, the prompt
to paste into ChatGPT, the filename to save to, and what already exists.

Sizes below are **measured from the running app**, not estimated. The rule is
that a runtime file must supply at least as many pixels as the frame occupies on
a Retina display (CSS pixels x 2), because every laptop in the room is Retina.

---

## 1. What we already have (do not regenerate)

Twelve files, covering all six flagship products in both crops:

| Product | Catalog 3:2 | Detail 1:1 |
|---|---|---|
| Mosaic Auraluxe H9 | `ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp` | `…-detail-1x1.webp` |
| Mosaic EchoBud S2 | `ce-true-wireless-earbuds-echobud-s2-catalog-3x2.webp` | `…-detail-1x1.webp` |
| Mosaic Pulse One | `ce-smartwatches-pulse-one-catalog-3x2.webp` | `…-detail-1x1.webp` |
| Mosaic Stride Pro | `rf-carbon-racing-shoes-stride-pro-catalog-3x2.webp` | `…-detail-1x1.webp` |
| Mosaic Forma Ergonomic | `ho-ergonomic-office-chairs-forma-ergonomic-catalog-3x2.webp` | `…-detail-1x1.webp` |
| Mosaic Atelier 32 | `ho-ultrawide-monitors-atelier-32-catalog-3x2.webp` | `…-detail-1x1.webp` |

Plus two landing heroes (`hero-landing-wide.webp`, `hero-landing-scene.webp`), the
Shop editorial plate (`editorial-fitness-wide.webp`), and five category tiles
under `mosaic/category/`. See section 5 for how the two heroes divide.

**The premium cohort is complete: 120 of 120 catalog images and 6 of 6 detail
images are installed.** The product-bound media source is now the single
200-product `data/media/asset_labels_200.json` manifest. Its
`catalog_still_to_generate` value is the authority for any focused image still
awaiting review or replacement.

What remains is a different job. 120 photographs cover 105 of the 161 live
subcategories at one image each, and a results page renders 12 cards, so a grid
still repeats. `docs/image-prompts-category-plates.md` owns that: 115
category-representative plates plus 3 per-domain still-lifes, none of them bound
to a specific product.

The same manifest adds 80 exact-product bindings outside the premium cohort:
49 products from the six flagship HNSW neighbourhoods, plus 16
running-and-fitness and 15 home-office products from frequent Search, Discover,
and lab paths. `docs/hnsw-focused-product-prompts.md` contains the product-bound
prompt set and exact output filenames. Reviewed files are marked installed and
hashed in the 200-product manifest; pending rows remain unavailable to the UI.
They also improve normal search surfaces whenever the same product IDs rank.
Products outside the 200-product bound set continue to use category plates as
explicitly representative fallbacks.

---

## 2. Sizes and aspect ratios

| Role | Generate at | Save runtime as | Why |
|---|---|---|---|
| Product catalog | **1536x1024** (3:2) | 1200x800 WebP | Card frame is 396x264 CSS at its largest; 1200 covers 2x with headroom for the wider Shop grid |
| Product detail | **1024x1024** (1:1) | 1200x1200 WebP | Flagship hero frame is ~520 CSS square; 1200 covers 2x |
| Category tile | **1024x1536** (2:3 portrait) | 500x672 WebP | Tile frame is 125x168 CSS; portrait source avoids cropping the subject out |
| Landing hero, wide | **1536x1024** (3:2) | 1672x941 WebP | Desktop frame is a full-bleed band; see section 5 |
| Landing hero, narrow | **1024x1536** (2:3 portrait) | 1568x1908 WebP | Under 640px the frame is a tall inset card |
| Editorial plate | **1536x1024** (3:2) | 1672x941 WebP | `.discover-plate-media` is a 16:9 frame ~720 CSS wide |

ChatGPT's image tool produces 1024x1024, 1536x1024 (landscape) and 1024x1536
(portrait). Use those three sizes exactly — asking for other dimensions gets you
an upscale, not more detail. Downscaling to the runtime size is done by script,
never by hand.

**Important:** generate product shots at **1536x1024 landscape**. The card frame
is 3:2 landscape, so a portrait source would be cropped down the middle.

---

## 3. The prompt

Paste this, replacing only the bracketed subject line. Everything else must stay
identical or the 120 images will not read as one catalog.

```text
Premium e-commerce product photograph for a high-end catalog.

SUBJECT: [PRODUCT DESCRIPTION]

The product is the single hero of the frame, centred, in sharp focus, shown
three-quarter front at eye level, filling roughly 65% of the frame.

SET: a warm minimalist interior surface — travertine stone or cream plaster —
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the product.

PALETTE: warm sand, bone, cream, and soft taupe, with a single deep maroon
accent. No cool tones, no grey, no white seamless studio backdrop.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
```

Two notes from the images already generated:

- Screens (monitors, watches, phones) must show an **abstract warm gradient**,
  never a UI. Add: `the display shows a soft abstract maroon and sand gradient`.
- ChatGPT sometimes composites brand marks onto products. If a mark appears,
  regenerate rather than accept it — `PROVENANCE.md` records that legible
  third-party marks in earlier renders are a known defect to correct upstream.

---

## 4. Naming and drop-in

Filename is the contract. Save the runtime WebP to:

```text
ui/public/assets/images/mosaic/<asset-key>.webp
```

Where the key is:

```text
<domain>-<subcategory>-<discriminator>-<role>

ce = consumer electronics   catalog-3x2 = card / grid / rail
rf = running and fitness    detail-1x1  = product page hero (flagships only)
ho = home office
```

Examples:

```text
ce-over-ear-headphones-02-catalog-3x2.webp
rf-road-running-shoes-01-catalog-3x2.webp
ho-laptop-stands-catalog-3x2.webp
```

The discriminator is a two-digit number only when a subcategory holds more than
one product; single-product subcategories omit it. `docs/media-shot-list.md`
gives the exact filename for every outstanding image, so no name has to be
derived by hand.

To convert a generated PNG to the runtime file:

```bash
uv run python scripts/import_generated_images.py --source ~/Downloads/mosaic-batch
```

That script matches by filename, crops to the role's aspect ratio, resizes, and
writes WebP at quality 88. It refuses to write a file whose name is not in the
cohort manifest, which is what keeps the folder honest.

---

## 5. The landing hero is two files

The Discover hero frame changes shape with the viewport, so a `<picture>` serves
one of two photographs and neither is force-fitted:

| Viewport | File | Native | Frame |
|---|---|---|---|
| above 640px | `hero-landing-wide.webp` | 1672x941 (16:9) | full-bleed band, ~1440x520 CSS |
| 640px and below | `hero-landing-scene.webp` | 1568x1908 (portrait) | inset card, ~396x560 CSS |

Both are short of 2x on a Retina laptop (the band alone wants 2880 device px), so
a wider replacement is the one worthwhile upgrade here. Do not upscale to reach
the number — that adds bytes, not detail.

Generate the wide scene at **1536x1024 landscape** and the portrait scene at
**1024x1536**. The portrait file is what `--hero` writes:

```bash
uv run python scripts/import_generated_images.py --source ~/Downloads --hero
```

Subject line for the wide hero prompt:

```text
SUBJECT: a sunlit limestone desk shot side-on — premium cream over-ear
headphones, a fabric-wrapped speaker, an open earbud case, a tablet on a stand,
and a low-profile keyboard spread left to right, with the left third of the frame
empty plaster wall carrying a soft diagonal light shaft
```

Subject line for the portrait hero prompt:

```text
SUBJECT: a sunlit home office corner — a cream leather ergonomic task chair at a
travertine desk, premium cream over-ear headphones on a slim metal stand in the
foreground, one cream running shoe with a maroon heel on the floor, a large
monitor showing a soft abstract maroon gradient behind the desk
```

The wide frame needs the empty third: the headline sits over it. The portrait
frame needs products stacked foreground to background rather than spread left to
right, so nothing is lost when a narrow card crops the sides.

---

## 6. Display targets

The landing scrolls by design. What has to survive a projector is the hero band:
the headline, the subtitle, and the two buttons. `.discover-hero` in
`ui/src/surfaces.css` sets `min-height: clamp(440px, calc(100vh - 344px), 700px)`,
so the band leaves 344 CSS px of the next section visible wherever the viewport
allows it, and stops shrinking at 440px. The search field lives further down the
page and `Start exploring` scrolls to it.

| Display | Inner height | Hero band | Below the fold |
|---|---:|---:|---:|
| 4K external, 1440 scaled | 1353 | 700 | 653 |
| 1080p external | 993 | 649 | 344 |
| 16" MacBook Pro, default | 943 | 599 | 344 |
| 15" laptop 1440x900 | 758 | 440 | 318 |
| 1440x758 with large chrome | 671 | 440 | 231 |

Inner heights are measured; the band and remainder columns are the clamp
evaluated at each one. The 440px floor is what keeps the two buttons on screen in
the last row, where `calc(100vh - 344px)` would otherwise give 327.

Mirroring a 16" laptop to a large monitor keeps the laptop's CSS viewport, so what
reads on the laptop reads on the projector. For the largest rooms, use **"More
Space"** in Display settings (2056 logical width); the hero goes full-bleed and
the body is capped at 1320 CSS px, so extra width becomes margin.
