# Monitor image generation prompts

## Additional catalog corrections

Source: `ho-productivity-monitors-p421678-catalog-3x2.png`

Runtime: `ui/public/assets/images/mosaic/ho-productivity-monitors-p421678-catalog-3x2.webp`

```text
Use case: product-mockup. Create a replacement catalog photograph for fictional ModuDesk UM-V272X, product 421678. Reference image is STYLE ONLY; its wide screen is wrong. Subject: one flat, standard 16:9, 32-inch desktop monitor, thin graphite bezel, simple fixed-height central stand and stable low rectangular base. The catalog resolution is 1920x1080: the physical screen MUST be exactly the ordinary 16:9 shape, NOT curved or ultrawide. Warm ivory plaster wall, dark oak desk, soft natural side daylight. Restrained burgundy and charcoal abstract wallpaper, no UI. Landscape 3:2 photograph, near-front camera at screen centre, gentle 8-degree angle, minimal perspective. Complete monitor including all four screen corners, stand and entire base, with ample margins on every side. Crisp focus across full product, refined believable materials. No props, keyboard, other electronics, cables, logos, text, specs, captions, badges, comparison panels, watermarks or borders. Highest available native sharp resolution. Generate a whole new clean photo; do not stretch the old screen.
```

Source: `ho-ultrawide-monitors-p422310-catalog-3x2.png`

Runtime: `ui/public/assets/images/mosaic/ho-ultrawide-monitors-p422310-catalog-3x2.webp`

```text
Use case: product-mockup. Create a replacement catalog photograph of fictional AxisOffice UM-M725, product 422310. The reference is STYLE ONLY; its screen is not wide enough. Subject: exactly one 49-inch CURVED SUPER-ULTRAWIDE monitor, 5120x1440 physical 32:9 aspect ratio, width 3.56 times its height, visibly twice the width of a normal 16:9 screen. Long continuous concave panel, both outer edges coming toward viewer, thin matte graphite bezel. Refined silver height-adjustable central column, broad stable shallow V-shaped base. Warm wood-panel background and dark desktop, soft daylight, restrained premium catalog photography. Subtle slate-blue and warm sand abstract wallpaper, no UI or writing. Landscape 3:2 image. Near-front slightly elevated view with minimal horizontal perspective compression, complete entire monitor, all screen corners, entire stand and base visible with generous margins. Screen should occupy about 85% of image width, very wide but not tall. Sharp focus across complete product. No keyboard, props, other electronics, people, cables, logos, text, specs, badges, watermarks, border or comparison panel. Highest available native detail. New clean full image, no stretching the reference.
```

Generated with the built-in image-generation tool on 2026-09-19. The PNG masters are kept in `ui/design-references/monitor-refresh-2026-09-19/`. Runtime WebP files retain native dimensions, with a single quality-94 encode; no cropping, resizing, sharpening or upscaling was applied. These images illustrate product form; the catalog and source evidence remain the basis for specifications and compatibility.

| Image | Delivered native size | Runtime size |
|---|---|---|
| Atelier 32 catalog | 1536 × 1024 | 1536 × 1024 |
| HorizonView 38 catalog | 1536 × 1024 | 1536 × 1024 |
| Atelier 32 detail | 1254 × 1254 | 1254 × 1254 |
| ModuDesk UM-V272X catalog | 1536 × 1024 | 1536 × 1024 |
| AxisOffice UM-M725 catalog | 1536 × 1024 | 1536 × 1024 |

The prompts requested larger output where available; the table records the
actual files delivered. The legacy `ho-ultrawide-monitors-atelier-32-detail-1x1.webp`
URL is retained as a byte-identical copy of the new Atelier detail image so older
saved references remain usable. The active product-page mapping uses the
correct Productivity Monitors path. Original supplied assets such as
`mosaic/atelier-32.webp` remain unchanged.

## Storefront use

The replacement photographs are served through the product-bound manifest
(`data/media/asset_labels_200.json`) and the Atelier 32 product-page mapping in
`ui/src/media.ts`. They correct two wrong-subject images: the HorizonView 38
card showed a flat panel for a curved ultrawide, and the Atelier detail image
was published under an `ultrawide` path. Two further replacements correct the
Full HD ModuDesk's 16:9 proportions and the 49-inch AxisOffice's 32:9 proportions,
checked against the live Aurora product records. The retired Atelier campaign
poster showed a different monitor and is no longer used on the product page.
The detail photograph is bound to product 420001, so similarly named models
cannot inherit it.

Discover, Shop and the required Lab 3 now follow headphones, a chair and a
monitor, matching the presentation. The mission manifest owns the monitor-and-chair
request and its citation requirements. Product text, embeddings and retrieval
settings are unchanged by that exercise update. Earlier scorecards are historical;
release requires fresh measurements against the reviewed questions.

## Atelier 32 catalog

Source: `atelier-32-catalog.png`

Runtime: `ui/public/assets/images/mosaic/ho-productivity-monitors-atelier-32-catalog-3x2.webp`

```text
Use case: product-mockup.
Asset type: replacement catalog photograph for the fictional Mosaic Atelier 32 monitor, product 420001, in the existing Mosaic home-office shopping app.
Input image 1 is the current catalog photograph, a visual and industrial-design reference. Generate a complete replacement photograph with much wider framing; do not preserve its cropped composition.
Subject: one 32-inch FLAT desktop monitor. Its active screen has the standard 16:9 proportions of a 3840x2160 display, clearly taller in relation to width than an ultrawide. Thin graphite metal bezel, refined straight height-adjustable central column and simple stable low-profile base. Retain the restrained Mosaic design language and subtle small centered bezel mark from the reference. Warm illumination may reflect softly on the graphite finish.
Scene: warm oak desktop, quiet warm ivory plaster wall, soft side daylight, same premium residential atmosphere as the reference. Minimal background. No other electronics, no people, no desk clutter.
Screen: abstract burgundy and warm sand wallpaper, no text, no app UI, no icons. Physically plausible low-glare screen with crisp edges.
Composition: landscape 3:2 photograph. Whole monitor, all four screen corners, entire stand and entire base visible with generous clear margins; nothing touches or leaves the frame. The subject occupies about 78 percent of image width. Near-front camera, slight 10-degree view, at screen-center height, minimal perspective distortion. Sharp subject throughout, realistic materials, restrained reflections, no shallow-focus blur on the product.
Constraints: visibly flat 16:9 display, never curved or ultrawide. No specifications, prices, checkmarks, badges, captions, third-party branding, cables implying connectivity, or watermarks. This is one product photograph, not a comparison board or screenshot. The photograph must not claim USB-C capabilities; those are explained by the app's records.
Output intent: highest available native detail, preferably 3072x2048 or larger in the same 3:2 ratio, suitable for a crisp presentation on a high-DPI laptop. Do not upscale a blurry original; generate clean full-resolution detail.
```

## HorizonView 38 catalog

Source: `horizonview-38-catalog.png`

Runtime: `ui/public/assets/images/mosaic/ho-ultrawide-monitors-catalog-3x2.webp`

```text
Use case: product-mockup.
Asset type: replacement catalog photograph for fictional HorizonView 38 Studio monitor, product 420002, in Mosaic's home-office store.
Input image 1 is a style reference only: retain the warm oak desktop, warm ivory wall, daylight and restrained premium photography. Its flat, narrow monitor is incorrect for this product and must be replaced completely.
Subject: exactly one 38-inch CURVED ULTRAWIDE desktop monitor. The active panel is 3840x1600, so its width-to-height ratio is 2.4:1 (24:10). This is visibly wider and shallower than a normal 16:9 monitor. Show the continuous gentle concave curvature clearly across the top edge and screen surface. The two outer edges come toward the viewer. Physically plausible 38-inch productivity display, thin matte graphite-black bezel, black height-adjustable central column and broad stable minimalist low-profile base. No gaming LEDs.
Scene: warm oak desk against a quiet ivory plaster wall with soft daylight from the side, similar to the reference. Minimal background and no distracting props or other electronics.
Screen: restrained cool slate-blue abstract landscape/waves without text or UI; distinguish this screen from the burgundy wallpaper of the flat Mosaic monitor while keeping the same photographic mood. Screen reflections remain subtle, with believable material detail.
Composition: landscape 3:2 photograph. Slightly elevated near-front three-quarter view, approximately 15 degrees off-center, enough to make the curvature unmistakable without compressing the screen width. Whole monitor, all four screen corners, entire stand and base visible, generous margins all around; subject occupies about 82 percent of image width. Crisp focus over the complete monitor. No cropping, no tilted verticals, no fish-eye lens distortion.
Constraints: clearly CURVED ULTRAWIDE 2.4:1 panel, never a flat 16:9 panel. One complete product photo, not a comparison board or an interface screenshot. No people, no keyboard, no laptop, no cable implying video connectivity. No words, logos, third-party branding, badges, specs, prices, decorative overlays or watermarks. The photograph must not claim docking or video over USB-C.
Output intent: highest available native detail, preferably 3072x2048 or larger in the same 3:2 ratio; suitable for crisp catalog cards and a presentation. Generate sharp detail without upscaling an existing blurry image.
```

## Atelier 32 detail

Source: `atelier-32-detail.png`

Runtime: `ui/public/assets/images/mosaic/ho-productivity-monitors-atelier-32-detail-1x1.webp`

```text
Use case: precise-object-edit.
Asset type: square product-detail photograph of the fictional Mosaic Atelier 32.
Input image 1 is the approved product and visual identity. Change only the framing to a square 1:1 composition by extending the surrounding wall and desktop as needed. Keep this exact monitor: flat 16:9 panel, graphite-metal thin frame with its tiny centered circular mark, the same straight central column, burgundy accent at the bottom of that column, identical rectangular low-profile base, same warm burgundy and sand wallpaper, identical materials and proportions, oak desktop and ivory wall, soft daylight, camera angle and realistic shadows.
The complete monitor, all four screen corners, entire stand and whole base must stay inside the square with comfortable margins. Keep the monitor visually large while retaining its true 16:9 physical shape; do not stretch or compress the panel to fill the square. Nothing cropped. No added props or products. No text, labels, specifications, UI, badges, cables, watermarks or new logos. This is a reframing of the same approved product, not a redesign or different model.
Output intent: highest available native square resolution, preferably 2048x2048 or above, with sharp realistic detail throughout the product.
```
