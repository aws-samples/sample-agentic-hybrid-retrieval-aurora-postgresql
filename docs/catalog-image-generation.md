# Portable-display image

The portable-monitor catalog image was replaced using the built-in image
generation tool. The former image depicted a desktop monitor on a pedestal.
The replacement shows a thin portable screen supported by a folding cover.
It is synthetic product imagery, not evidence of measured product performance.

Runtime asset:
`ui/public/assets/images/mosaic/ce-portable-monitors-catalog-3x2.webp`

Source generation: 1536 × 1024. Runtime encoding: 1200 × 800 WebP, preserving
aspect ratio. The installed asset checksum is in
`data/media/asset_labels_200.json` for product 73425.

## Prompt

Create one premium photorealistic catalog image, landscape 3:2, sharp high
resolution. Show exactly one compact 16-inch OLED portable computer monitor: very
thin matte dark graphite body, 16:10 screen, slim black bezels, a folding charcoal
folio cover that forms a triangular kickstand directly behind the screen; bottom
edge rests on desk, no desktop pedestal, no tall stand. Three-quarter front view,
whole device with generous safe margins. Display a subtle abstract burgundy and
sand gradient, no text or UI. Warm cream travertine desk and warm plaster wall,
soft afternoon window light from left, restrained Mosaic editorial product
photography, gentle realistic contact shadows. A single understated USB-C cable
can leave the side, no other electronics, no keyboard, no mouse, no laptop, no
logos, no brand marks, no letters or watermarks. The product should visually read
as light and portable rather than a full-size desktop screen.

Changing only this image does not change product text embeddings. Product 73425 already describes a 16-inch OLED display with 2560 × 1600
resolution, so this photo correction does not require a replacement text vector.
Other portable-display records with incorrect specifications are corrected and
re-embedded separately.

## Missing-photo backdrop

The three domain fallback images now use the same empty warm travertine
ledge and plaster wall, with no fabric or other objects that could be mistaken
for the item. The UI labels these cards **Photo unavailable**.

Edit prompt: Remove the fabric completely. Deliver a clean photorealistic
landscape 3:2 image of an empty warm cream travertine ledge and subtle warm
plaster wall. No cloth, towels, mat, plant, product, prop, text or logo. Preserve
the cream/beige palette and soft natural light. This is an intentionally empty
photography backdrop for an item without a product photo.

Source: `exec-fc95b695-1566-48e4-836c-d9a9cf6d3ebd.png`, 1536 × 1024.
The three runtime files are 1200 × 800 WebP; checksums are recorded in
`data/media/category_plates.json`. No product text or vectors change.
