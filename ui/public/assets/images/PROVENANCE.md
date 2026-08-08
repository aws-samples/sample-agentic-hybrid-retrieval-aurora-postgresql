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
| `mosaic/hero-landing-scene.webp` | 1586x992 (1.6) | `.hero-image` |
| `mosaic/category/*.webp` | 500x672 (125:168) | `.category-card img` |
| `thumb-*.webp` | 480x600 (4:5) | domain tiles |
| `mosaic/*-thumb.webp` | 640x800 (4:5) | domain tiles |
| `mosaic/*.webp`, `curated/*` | 1200x1200 (1:1) | product cards |

One crop is deliberate:

- `.hero-image > img` uses `object-position: 60% 50%`. The frame is 770x964
  portrait and the photograph is 1586x992 landscape, so cover-fit shows a 792px
  window of it; this keeps the chair focal while giving the headphone stand more
  breathing room than the earlier right-biased crop.

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
