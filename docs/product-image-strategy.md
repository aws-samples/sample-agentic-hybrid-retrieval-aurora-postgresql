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

The checked-in runtime layer lives under `ui/public/assets/images`. It uses the
supplied Mosaic package as its only visual source:

- the landing hero uses the original `mosaic/hero-editorial-mosaic.webp`
  source asset;
- EchoBud S2, Pulse One, Stride Pro, and Atelier 32 retain the supplied Mosaic
  product assets and marks;
- Auraluxe H9 and Forma Ergonomic complete the six-product Mosaic showcase;
- curated demonstration products and deterministic category fallbacks cover
  the remaining catalog.

`data/full/product_image_urls.csv.gz` maps all 500,000 products to those local
assets. `scripts/load_media.py` verifies each path, stores its SHA-256 digest,
and publishes only `approved` rows to `mosaic.product_media`.

The design boards in `ui/design-references` and runtime files in
`ui/public/assets/images` are retained in their original formats. Asset
corrections happen in the image-generation source and are imported as full
replacements, never as local retouching.
