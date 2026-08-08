# Image attribution

All photographs are from Unsplash under the Unsplash License (free for
commercial use, no permission required; attribution appreciated, not required).

## Product photography — `catalog/`

1200x1200 WebP, q88, centre-cropped from 2000px sources.

| File | Unsplash photo ID |
|---|---|
| `anc-headphones-yellow.webp` | `1505740420928-5e560c06d30e` |
| `anc-headphones-grey.webp` | `1546435770-a3e426bf472b` |
| `onear-headphones-tan.webp` | `1484704849700-f032a568e944` |
| `onear-headphones-black.webp` | `1583394838336-acd977736f90` |
| `keyboard-mech-marble.webp` | `1618384887929-16ec33fab9ef` |
| `keyboard-colorkeys.webp` | `1595225476474-87563907a212` |
| `chair-task-fabric.webp` | `1580480055273-228ff5388ef8` |
| `chair-shell-black.webp` | `1592078615290-033ee584e267` |
| `monitor-desk.webp` | `1616763355603-9755a640a287` |
| `monitor-workspace.webp` | `1547082299-de196ea013d6` |
| `shoe-running-white.webp` | `1600185365483-26d7a4cc7519` |
| `shoe-running-pair.webp` | `1595341888016-a392ef81b7de` |

## Landing hero

- `hero-discovery.webp`: EFFYDESK, photo `MtoAG0GujOI`
  (`1683836809739-c10a7be81028`). 1400x2000 WebP q92, portrait-cropped from
  the 3362x2344 original without upscaling. The source is a free Unsplash
  photograph (`premium: false`, `plus: false`).

The crop centers an unbranded mesh chair against real window light and keeps
screen content out of view. A small blue sticker on the closed background
laptop was removed during asset preparation so the hero contains no visible
maker mark.

The concept board remains a lighting and composition reference only. Its own
hero panel contains legible On Running and Bang & Olufsen marks and is not
shipped.

## Category tiles

560x420 WebP q90 (4:3): `tile-audio.webp`, `tile-fitness.webp`,
`tile-workspace.webp`, `tile-electronics.webp`.

## Sized for the delivery screen

The workshop is presented from a 14-15" MacBook, so element sizes are measured
at those viewports rather than at an arbitrary desktop width:

| Viewport | Hero | Category tile | Domain tile |
|---|---|---|---|
| 14" MacBook Pro (1512x982) | 696x819 | 160x120 | 413x413 |
| 15" MacBook Air (1470x956) | 676x819 | 154x115 | 413x413 |

The hero was 1400x2000 at 628 KB, which is more pixels than a 2x laptop panel
can show in this slot; 1400x1750 q88 covers 819 CSS px of height at 2x and costs
201 KB. Whole landing image payload is roughly 286 KB.

Do not size these assets by eye. Measure the rendered box first, double it for
the 2x panel, and encode to that.

Each is re-cropped at its own zoom rather than sharing one setting. A wide
subject cannot fill a 4:5 frame lengthwise: the keyboard at the same zoom as the
others produced a tile that read as "marble worktop", so it is framed on the key
field at 1.85x.

Each is encoded once from the original JPEG source, not from the `catalog/`
WebP files. The first version of these tiles was re-compressed from the
already-lossy 1200x1200 WebP assets, and that second generation was visible at
tile size even though the pixel dimensions were sufficient. Re-encoding a lossy
file compounds its artefacts: always crop from the original.

## Category fallbacks — top level

- `headphones.webp`: C D-X, photo `1505740420928-5e560c06d30e`
- `workspace.webp`: Nastuh Abootalebi, photo `1497366811353-6870744d04b2`
- `chair.webp`: Inside Weather, photo `1586023492125-27b2c045efd7`
- `running-track.webp`: Matt Lee, photo `1549896869-ca27eeffe4fb`

## Selection rules

**Resolution.** Sources are pulled at 2000px and downscaled. The superseded set
in `_superseded/` was cropped out of a page screenshot and enlarged to 800x900,
which left every tile near 0.4 bits/px and visibly soft when projected. Cropping
and then enlarging cannot restore detail — replacements must come from a larger
source.

**Licence.** Unsplash mixes free photographs with paid Unsplash+ results, and
the Unsplash+ previews carry a repeating watermark. The search API flags these as
`plus` / `premium`; filter on those fields before downloading. In one hero sweep
14 of 57 results were Unsplash+.

**Trademark screening.** Each candidate is reviewed at full resolution, one at a
time. Thumbnail review is not sufficient: it previously passed a Nike swoosh and
a set of tiles with a heart icon baked into the pixels. Of 20 catalog
candidates, 8 were rejected — an Apple Magic Keyboard, Apple EarPods,
AirPods/Pixel Buds, a SONY wordmark, an off-topic travel photograph, and a desk
scene with no product in it.

Filtering captions for brand names is a cheap first pass but not sufficient on
its own: rejected hero candidates included a "DT 770 PRO" headphone, a "BenQ"
monitor with an "EDIFIER" speaker, an Eames lounge chair, and Call of Duty cover
art, none of which named a brand in the caption. Roughly 70% of stock product
photography carries a legible mark, so unbranded environmental shots are the
dependable source for backdrops.

One residual: `onear-headphones-tan.webp` carries a small "aēdle" maker mark on
the headband. It is legible only at full size, not at card scale. Replace it if
the workshop ships publicly.

**Media identity is separate from product identity.** `productImage()` maps a
product to an asset by subcategory, so photographs can be replaced without
touching catalog IDs or retrieval judgments. An asset is never evidence for an
attribute that is not in catalog data.
