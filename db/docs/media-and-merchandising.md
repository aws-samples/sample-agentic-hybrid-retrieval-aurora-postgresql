# Media and merchandising

## Recommended tiers

| Tier | Coverage | Media policy |
|---|---:|---|
| Flagship | 6 products | catalog image + 1:1 detail hero + alternate/gallery views |
| Premium | 114 products | one unique 3:2 catalog photograph |
| Family | long tail | category/form-factor/material/color family image |
| Generic | rare fallback | neutral domain placeholder |

The 120-product premium cohort is a merchandising surface, not a separate search corpus. Search continues to run against all 500K products.

## Shop pagination

The included assignment uses 10 pages of 12 products. Twelve supports:

- 4 × 3 on laptop
- 3 × 4 on tablet
- 2 × 6 on mobile

## Media model

`mosaic.media_asset` stores the physical object metadata. `mosaic.product_media` gives an asset a product-specific role and crop behavior.

Important fields:

- `master_uri` and `runtime_uri`
- dimensions and MIME type
- aspect ratio
- crop anchor
- physical brand-mark zone
- media tier and bespoke flag
- checksum

The exact Mosaic mark should be composited after generation from one canonical vector source.
