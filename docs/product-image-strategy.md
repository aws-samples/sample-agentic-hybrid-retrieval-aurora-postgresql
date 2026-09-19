# Product image strategy

## Do not generate 500,000 unique images

The retrieval corpus needs 500,000 unique product records, not 500,000 original photographs. For a polished workshop UI, use a layered visual strategy:

1. **Hero set:** 12–24 premium photorealistic images for landing pages and featured searches.
2. **Category set:** 8–20 images per important subcategory, roughly 500–800 assets total.
3. **Authored variants:** select source-provided background, angle, accent, and color variants.
4. **Long-tail fallback:** consistent category silhouettes or studio renders.
5. **Deterministic mapping:** `image_key` maps each product to an asset without making image identity part of relevance ground truth.

## Recommended hero subjects

- over-ear ANC headphone on a reflective pedestal
- carbon-plated running shoe on a rock at dawn
- ergonomic mesh chair in a cinematic home office
- USB-C dock/monitor workspace
- trail shoe on wet technical terrain
- standing desk in a compact apartment

## Rules

- retain supplied assets byte-for-byte; do not crop, blur, obfuscate, or
  generate corrected runtime derivatives
- preserve Mosaic product names and marks
- make corrections to non-Mosaic marks in the upstream image source, then
  replace the original asset
- keep lighting/background consistent within a subcategory
- provide alt text based on product type, not invented visual specifications
- do not use the image itself as evidence for an attribute unless the attribute is in catalog data
- keep retrieval evaluation independent of image availability

## Adopted Mosaic media

The checked-in runtime layer lives under `ui/public/assets/images`. The supplied
Mosaic package provides the original visual direction. Reviewed replacement
photographs retain their generation prompts, source masters and runtime hashes:

- the landing hero uses the original `mosaic/hero-editorial-mosaic.webp`
  source asset;
- EchoBud S2, Pulse One, Stride Pro, and Atelier 32 retain the supplied Mosaic
  product assets and marks;
- Auraluxe H9 and Forma Ergonomic complete the six-product Mosaic showcase;
- curated demonstration products and deterministic category fallbacks cover
  the remaining catalog.

`data/full/product_image_urls.csv.gz` maps all 500,000 products to local
assets. The storefront resolves reviewed product photographs from
`data/media/asset_labels_200.json` and category photographs from
`data/media/category_plates.json`. This also works when the API returns no media
rows. `db/sql/04_media.sql` defines the media tables;
`db/sql/15_load_premium_cohort.sql` loads merchandising assignments, not physical
media records. The former `scripts/load_media.py` targeted the retired
`catalog.product_media` table and is no longer used.

The design boards in `ui/design-references` and runtime files in
`ui/public/assets/images` are retained in their original formats. Asset
corrections happen in the image-generation source and are imported as full
replacements, never as local retouching.

The 2026-09-19 monitor replacement set shows the complete flat Atelier 32 and
the curved HorizonView 38 ultrawide. Catalog images are 1536 × 1024; the matching
Atelier detail image is 1254 × 1254. Native dimensions are preserved. See
[monitor image prompts and source files](monitor-image-prompts.md).
