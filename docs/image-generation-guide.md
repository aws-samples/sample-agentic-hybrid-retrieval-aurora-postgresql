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

Plus the landing hero (`hero-landing-scene.webp`) and five category tiles under
`mosaic/category/`. See section 5 for the hero's one outstanding issue.

**Still to generate: 114 catalog images.** One per remaining premium product,
3:2 only. Run `make media-shot-list` for the current list; the file is
`docs/media-shot-list.md`, which leads with the 24 retrieval anchors that appear
in scripted queries.

---

## 2. Sizes and aspect ratios

| Role | Generate at | Save runtime as | Why |
|---|---|---|---|
| Product catalog | **1536x1024** (3:2) | 1200x800 WebP | Card frame is 396x264 CSS at its largest; 1200 covers 2x with headroom for the wider Shop grid |
| Product detail | **1024x1024** (1:1) | 1200x1200 WebP | Flagship hero frame is ~520 CSS square; 1200 covers 2x |
| Category tile | **1024x1536** (2:3 portrait) | 500x672 WebP | Tile frame is 125x168 CSS; portrait source avoids cropping the subject out |
| Landing hero | **1024x1536** (2:3 portrait) | 1568x2352 WebP | Frame is 770x938 CSS portrait; needs 1540x1876 device px |

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
python scripts/import_generated_images.py --source ~/Downloads/mosaic-batch
```

That script matches by filename, crops to the role's aspect ratio, resizes, and
writes WebP at quality 88. It refuses to write a file whose name is not in the
cohort manifest, which is what keeps the folder honest.

---

## 5. The landing hero needs regenerating

The current hero is **1586x992 landscape**, but the frame it fills is
**770x938 CSS portrait**. Consequences:

- Horizontally it is fine (1540 device px needed, 1586 supplied).
- Vertically it is **884px short** of the 1876 device px a Retina 16" laptop
  demands, so the browser upscales it.
- Because the source is landscape and the frame is portrait, cover-fit shows
  only a 792px-wide window of the photograph. Most of the image is never seen.

Generate a **portrait** replacement at **1024x1536**, then:

```bash
python scripts/import_generated_images.py --source ~/Downloads --hero
```

Subject line for the hero prompt:

```text
SUBJECT: a sunlit home office corner — a cream leather ergonomic task chair at a
travertine desk, premium cream over-ear headphones on a slim metal stand in the
foreground, one cream running shoe with a maroon heel on the floor, a large
monitor showing a soft abstract maroon gradient behind the desk
```

Keep the vertical composition: products stacked from foreground to background
rather than spread left to right, so nothing is lost when the frame crops.

---

## 6. Display targets

The landing is designed to fit without scrolling on every laptop in the room.
Verified by measurement at these viewports (inner height in CSS px):

| Display | Inner height | Fits |
|---|---:|---|
| 4K external, 1440 scaled | 1353 | yes |
| 1080p external | 993 | yes |
| 16" MacBook Pro, default | 943 | yes |
| 15" laptop 1440x900 | 758 | yes |
| 1440x758 with large chrome | 671 | yes |
| Very short frames | < 640 | releases fixed height and scrolls |

Mirroring a 16" laptop to a large monitor keeps the laptop's CSS viewport, so
what fits on the laptop fits on the projector. For the largest rooms, use
**"More Space"** in Display settings (2056 logical width) — the card is capped at
1558 CSS px, so extra width becomes margin rather than stretched layout.
