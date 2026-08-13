# Mosaic image assets

The `curated/` set and the files at this directory's root are copied verbatim
from the supplied asset package:

    mosaic-premium-image-assets/runtime/  ->  public/assets/images/

Do not regenerate, re-crop, or re-encode those. Re-encoding a delivered WebP
compounds its compression artefacts, and the upstream package is the place where
they get corrected.

## Locally derived files

`mosaic/*-scene.webp`, `mosaic/*-alt.webp`, `mosaic/*-studio.webp`,
`mosaic/carryall-sleeve.webp`, `mosaic/hero-landing-scene.webp`, and
`mosaic/category/*.webp` are **not** in the package. They are square or portrait
crops of the PNG renders in

    mosaic-premium-image-assets/references/mosaic-products/

re-encoded to WebP at quality 88-92. They are here because the landing board
(`references/mosaic-ui/landing.png`) needs a hero photograph and five category
tiles that no delivered runtime asset matches. Treat the reference PNGs as the
source of truth and re-derive rather than editing these in place.

`mosaic/posters/*.png` contains byte-for-byte copies of the four selected
editorial boards. They are used only on matching product-detail pages; the UI
places the canonical Mosaic `M` over the legacy header mark without altering the
source PNG.

`mosaic/category/home.webp` is the one exception: it is upscaled 4x from the
board's own 125x168 thumbnail, because the Aug-8 render set contains no
equivalent styled-shelf photograph. It is softer than its four neighbours.

`mosaic/hero-landing-wide.webp` and `mosaic/editorial-fitness-wide.webp` come
from two 1672x941 editorial scenes supplied on 2026-08-12. Each source PNG gets a
light unsharp pass (Pillow `UnsharpMask(radius=1.2, percent=55, threshold=3)`,
chosen because it recovers edge detail without a halo on the flat wall) and is
then encoded with `cwebp -q 94 -m 6 -sharp_yuv`. No crop and no resize, so 1672px
is all the detail that exists: the hero band is 1440 CSS px wide, so a Retina
laptop upscales it. A third scene from the same batch (tools and material
samples) was rejected because the drill carries a legible third-party maker mark
and no catalog domain covers power tools.

The editorial posters contain product names and feature bullets composited into
the pixels. They are not used as catalog photography.

## Verification

`asset-manifest.json` in the source package records a SHA-256 for 11 of the
files (the original `mosaic/` set). All 11 verify byte-for-byte against the
installed copies. The files under `curated/` and the root are not in the
manifest, and neither are the locally derived files listed above.

To re-verify after a resync:

    rsync -a --exclude '.DS_Store' <package>/runtime/ public/assets/images/

then compare hashes against `asset-manifest.json`.

## Aspect ratios drive the CSS, not the reverse

| Asset group | Native size | Frame that uses it |
|---|---|---|
| `mosaic/hero-landing-wide.webp` | 1672x941 (16:9) | `.discover-backdrop` above 640px |
| `mosaic/hero-landing-scene.webp` | 1568x1908 (770:938) | `.discover-backdrop` at 640px and below |
| `mosaic/editorial-fitness-wide.webp` | 1672x941 (16:9) | `.discover-plate-media` |
| `mosaic/category/*.webp` | 500x672 (125:168) | `.category-card img` |
| `thumb-*.webp` | 480x600 (4:5) | domain tiles |
| `mosaic/*-thumb.webp` | 640x800 (4:5) | domain tiles |
| `mosaic/*.webp`, `curated/*` | 1200x1200 (1:1) | product cards |

The Discover hero is art-directed rather than cropped harder. Its frame is a wide
band on desktop and a tall card under 640px, so a `<picture>` serves the 16:9
scene to the band and the portrait scene to the card. Serving only the 16:9 file
would show about a third of it on a phone.

Two crops are deliberate:

- `.discover-backdrop img` uses `object-position: center 58%`. The band is
  roughly 1440x520 CSS and the photograph is 16:9, so cover-fit drops about 290
  device px; biasing downward keeps the headphones, earbuds, and keyboard in
  frame and spends the loss on empty wall.
- At 640px and below it becomes `54% center` against the portrait scene, which
  keeps the monitor and chair centred in a narrower card.

## Media identity is separate from product identity

`productImage()` in `src/media.ts` maps a product to an asset by subcategory, so
photographs can be replaced without touching catalog IDs or retrieval
judgments. An asset is never evidence for an attribute that is not in catalog
data.

Pool breadth matters at catalog scale. The live database has 2,098 Audio and
1,294 Seating products, so a pattern with two assets repeats one photograph
across adjacent cards in a 4-up grid. The headphone pool carries 8; chairs carry
3, which still collides. Add assets rather than reordering if that shows.

## Known contents

The supplied renders use the fictional Mosaic brand but several depict
recognizable real products, and some carry legible third-party maker marks.
Page text is also baked into the pixels of a few frames. These are accepted for
now and will be corrected upstream in the asset package, not here.
