# Focused product photography for HNSW and search

These prompts cover 80 products outside the workshop's existing 120-product
photography cohort. The first 49 are the products in the six flagship queries'
exact top-10 HNSW neighbourhoods that do not already own product-bound
photography. The additional 31 cover 16 running-and-fitness products and 15
home-office products from frequent Search, Discover, and lab paths.

Both sets were derived from the live Aurora-backed API on 2026-08-17. The HNSW
set used `preset=none` and `k=10`. Together with the installed cohort, the
extension raises the planned product-bound catalog from 120 to 200 exact
products.

The same product IDs can appear in Shop, Search, Ask Mosaic, retrieval labs, and
the HNSW instrument. Binding each generated image to its exact product therefore
improves more than the graph. Products outside this 200-product set continue to
use verified category-representative plates; a fallback image is never presented
as product-bound photography.

## Generation contract

- Generate **one separate 1536x1024 landscape image per SHOT**.
- Do not create a contact sheet, collage, comparison image, or multiple variants
  inside one file.
- Save each output under the exact filename on its `SAVE AS` line.
- Keep the complete product inside the frame with clear margin on every side.
- Reject and regenerate any image with lettering, a logo, a watermark, a UI, or
  a visibly duplicated product.
- The `.png` files are generation inputs. They will be cropped, resized to
  1200x800, converted to WebP, and product-bound after review.

## Shared prompt

Paste this complete shared prompt with exactly one SHOT block from the sections
below.

```text
Use case: product-mockup
Asset type: exact product-bound catalog photograph for a premium commerce search
experience and a technical nearest-neighbour visualization

Create ONE separate 1536x1024 landscape photograph for the SHOT below. Do not
create a contact sheet, collage, comparison layout, or alternate views.

The named product is the single hero. Preserve the specified product category,
finish, silhouette, materials, and structural details. Show the complete product
in sharp focus with clear margin on all sides, filling roughly 60 to 68 percent
of the frame.

STYLE: believable high-end editorial e-commerce photography, natural material
texture, realistic manufacturing detail, restrained styling, 50mm commercial
product-photography character, soft but directional light, and natural contact
shadows. Photorealistic camera image, not an illustration, painting, or glossy
3D render.

CATALOG FAMILY: the 80 photographs must feel related without looking like one
photo repeated. Respect each SHOT's finish, silhouette, camera angle, surface,
and backdrop. Use a varied but compatible palette of limestone, bone, burgundy,
coral, plum, forest, ocean, graphite, slate, sand, pale oak, and warm metal.
Avoid making every scene beige.

CRITICAL CONSTRAINTS:
- No text, letters, numbers, logos, brand marks, model names, badges, labels, or
  watermarks anywhere in the image
- No people, hands, faces, body parts, packaging, instruction cards, or retail
  signage
- No extra copies of the product and no unrelated product in the foreground
- No impossible floating geometry, malformed hinges, duplicate controls, fused
  parts, asymmetrical pairs, or broken reflections
- No white seamless studio backdrop and no heavy artificial vignette
- Screens must show only a soft abstract maroon, amber, sand, or forest gradient
  with no interface, icons, windows, charts, clock face, or readable data

SHOT:
[PASTE ONE SHOT BLOCK HERE]
```

## Over-ear headphones - 8 images

```text
PRODUCT ID: 186
PRODUCT: FluxLogic OH-P900 Prime Over-Ear Headphone
SUBJECT: compact foldable over-ear headphones in an ocean-blue finish, slim oval
earcups, soft charcoal cushions, a visible but mechanically plausible brushed
metal folding hinge, and a narrow padded headband
COMPOSITION: three-quarter front from the left at eye level on a pale limestone
plinth; soft late-afternoon light; muted coral plaster behind it
SAVE AS: ce-over-ear-headphones-p186-catalog-3x2.png
```

```text
PRODUCT ID: 591
PRODUCT: AuriOne OH-S930S Prime Over-Ear Headphone
SUBJECT: non-folding cloud-white over-ear headphones with broad circular earcups,
deep bone cushions, a continuous softly padded headband, and slender champagne
metal yokes
COMPOSITION: nearly frontal and slightly elevated on a warm walnut block; diffuse
window light; deep burgundy paper backdrop
SAVE AS: ce-over-ear-headphones-p591-catalog-3x2.png
```

```text
PRODUCT ID: 943
PRODUCT: AuriAudio OH-E993X Tour Over-Ear Headphone
SUBJECT: lightweight stone-finish over-ear headphones with shallow oval earcups,
a thin headband, subtle perforated cushions, and compact low-profile pivots
COMPOSITION: clean side profile resting upright on textured sandstone; raking
light from the right; softly blurred forest-green wall
SAVE AS: ce-over-ear-headphones-p943-catalog-3x2.png
```

```text
PRODUCT ID: 2477
PRODUCT: AuriWave OH-F922X Essential Over-Ear Headphone
SUBJECT: compact foldable over-ear headphones with faceted plum earcups, dark
maroon cushions, a sturdy water-resistant shell, and exposed satin-metal hinges
COMPOSITION: rear three-quarter view showing the hinge geometry on a cream
plaster surface; low warm light; pale sand backdrop
SAVE AS: ce-over-ear-headphones-p2477-catalog-3x2.png
```

```text
PRODUCT ID: 5613
PRODUCT: AxionPulse OH-Z305 Prime Over-Ear Headphone
SUBJECT: substantial non-folding over-ear headphones in muted sage, large round
earcups, thick graphite cushions, a broad fabric-wrapped headband, and brushed
aluminum yokes
COMPOSITION: three-quarter front from the right on a burgundy lacquered surface;
soft overhead daylight; warm bone wall
SAVE AS: ce-over-ear-headphones-p5613-catalog-3x2.png
```

```text
PRODUCT ID: 6394
PRODUCT: OrbitWorks OH-M289P Essential Over-Ear Headphone
SUBJECT: robust foldable sand-finish over-ear headphones with squared-oval
earcups, a woven headband underside, deep taupe cushions, and chunky precision
hinges
COMPOSITION: low eye-level view on a dark forest-green stone slab; side light
catching the woven texture; pale oak backdrop
SAVE AS: ce-over-ear-headphones-p6394-catalog-3x2.png
```

```text
PRODUCT ID: 10183
PRODUCT: AuriAudio OH-E902X Flex Over-Ear Headphone
SUBJECT: midweight foldable over-ear headphones in coral, gently tapered earcups,
pale taupe cushions, a slim bone headband, and compact silver hinges
COMPOSITION: lightly top-down three-quarter view on honed travertine; soft leafy
shadow play; muted plum wall
SAVE AS: ce-over-ear-headphones-p10183-catalog-3x2.png
```

```text
PRODUCT ID: 12662
PRODUCT: AxionOne OH-M901X Essential Over-Ear Headphone
SUBJECT: large non-folding over-ear headphones in deep forest green, broad oval
earcups, perforated bone leather cushions, a substantial padded headband, and
dark metal pivots
COMPOSITION: crisp side profile on a pale oak surface; narrow shaft of daylight;
warm graphite plaster behind it
SAVE AS: ce-over-ear-headphones-p12662-catalog-3x2.png
```

## True wireless earbuds - 8 images

```text
PRODUCT ID: 17007
PRODUCT: EchoTech TWE-M259P Essential True Wireless Earbud
SUBJECT: a matched pair of plum in-ear earbuds with short angular stems, compact
silicone tips, small faceted touch surfaces, and an open low-profile charging
case in the same finish
COMPOSITION: eye-level three-quarter view on cream stone; one earbud seated and
one beside the case; soft sand backdrop
SAVE AS: ce-true-wireless-earbuds-p17007-catalog-3x2.png
```

```text
PRODUCT ID: 17367
PRODUCT: EchoTech TWE-Z618P Elite True Wireless Earbud
SUBJECT: tiny stemless forest-green in-ear earbuds with smooth bean-shaped
housings, subtle acoustic vents, compact tips, and a small rounded-square charging
case
COMPOSITION: restrained top-down view on pale oak with the open case behind the
pair; warm side light; burgundy edge entering the background
SAVE AS: ce-true-wireless-earbuds-p17367-catalog-3x2.png
```

```text
PRODUCT ID: 20967
PRODUCT: EchoTech TWE-M220S Tour True Wireless Earbud
SUBJECT: a matched pair of plum travel earbuds with longer tapered stems, rounded
in-ear bodies, dark silicone tips, and a smooth oval charging case
COMPOSITION: low three-quarter angle on a sand-colored plaster block; one bud
leaning naturally against the open case; muted forest backdrop
SAVE AS: ce-true-wireless-earbuds-p20967-catalog-3x2.png
```

```text
PRODUCT ID: 21494
PRODUCT: EchoWorks TWE-A776S Prime True Wireless Earbud
SUBJECT: brushed-silver in-ear earbuds with circular touch discs, very short
stems, charcoal tips, and a slim horizontal charging case with softly rounded
corners
COMPOSITION: symmetrical front three-quarter arrangement on dark plum stone;
cool-neutral daylight balanced by a warm bone background
SAVE AS: ce-true-wireless-earbuds-p21494-catalog-3x2.png
```

```text
PRODUCT ID: 22167
PRODUCT: EchoTech TWE-M752 Elite True Wireless Earbud
SUBJECT: compact navy in-ear earbuds with rounded triangular housings, small
straight stems, bone silicone tips, and a tall pebble-shaped charging case
COMPOSITION: three-quarter view from above on travertine; open case to the left,
paired earbuds to the right; soft coral backdrop
SAVE AS: ce-true-wireless-earbuds-p22167-catalog-3x2.png
```

```text
PRODUCT ID: 23774
PRODUCT: EchoWorks TWE-S391 Tour True Wireless Earbud
SUBJECT: substantial coral in-ear earbuds with sculpted ergonomic bodies, tapered
stems, deep maroon tips, and a wider charging case suggesting extended battery
capacity
COMPOSITION: dynamic side three-quarter arrangement on a graphite surface; one
bud upright and one lying flat; warm sand wall
SAVE AS: ce-true-wireless-earbuds-p23774-catalog-3x2.png
```

```text
PRODUCT ID: 24807
PRODUCT: EchoTech TWE-N726 Plus True Wireless Earbud
SUBJECT: very small stone-finish in-ear earbuds with open, airy short-stem
geometry, pale silicone tips, and an exceptionally slim horizontal charging case
COMPOSITION: precise top-down arrangement on burgundy paper with a narrow bone
border; soft diffuse light and gentle contact shadows
SAVE AS: ce-true-wireless-earbuds-p24807-catalog-3x2.png
```

```text
PRODUCT ID: 26924
PRODUCT: EchoEdge TWE-C292 Elite True Wireless Earbud
SUBJECT: ultra-light stemless stone earbuds with pebble-like housings, graphite
touch insets, tiny silicone tips, and a compact square charging case with rounded
edges
COMPOSITION: eye-level macro product view on a forest-green stone ledge; open
case softly behind the pair; warm cream plaster background
SAVE AS: ce-true-wireless-earbuds-p26924-catalog-3x2.png
```

## Smartwatches - 9 images

```text
PRODUCT ID: 116704
PRODUCT: PixelOne S-M126S Prime Smartwatch
SUBJECT: slim round smartwatch in a stone finish, narrow satin-metal bezel, woven
stone textile band, compact side crown, and a clean abstract maroon-to-sand
gradient on the display
COMPOSITION: three-quarter side view standing on a small limestone block; warm
window light; muted ocean backdrop
SAVE AS: ce-smartwatches-p116704-catalog-3x2.png
```

```text
PRODUCT ID: 117609
PRODUCT: PixelBeam S-E710P Max Smartwatch
SUBJECT: rugged round smartwatch in plum, raised protective bezel, substantial
plum silicone band with large perforations, two low-profile side buttons, and an
abstract amber gradient display
COMPOSITION: low heroic angle on graphite stone; soft rim light; pale bone wall
SAVE AS: ce-smartwatches-p117609-catalog-3x2.png
```

```text
PRODUCT ID: 117784
PRODUCT: PixelOne S-A206P Prime Smartwatch
SUBJECT: compact square smartwatch with softly rounded corners, polished silver
case, fine silver mesh band, single flush crown, and an abstract forest-to-sand
gradient display
COMPOSITION: straight-on elevated view on burgundy paper; gentle daylight;
cream plaster backdrop
SAVE AS: ce-smartwatches-p117784-catalog-3x2.png
```

```text
PRODUCT ID: 119344
PRODUCT: PixelOne S-N100X Tour Smartwatch
SUBJECT: cushion-shaped graphite smartwatch with an integrated graphite rubber
band, broad dark bezel, protected side crown, and an abstract coral-and-charcoal
gradient display
COMPOSITION: three-quarter front view on pale oak; directional side light;
muted sand background
SAVE AS: ce-smartwatches-p119344-catalog-3x2.png
```

```text
PRODUCT ID: 120009
PRODUCT: PixelBeam S-M777 Active Smartwatch
SUBJECT: narrow rectangular sport smartwatch in ocean blue, softly curved glass,
an ocean perforated band, minimal side control, and an abstract maroon-to-amber
gradient display
COMPOSITION: top-down diagonal arrangement on cream stone with the band gently
curved; subtle leafy shadow; warm graphite backdrop
SAVE AS: ce-smartwatches-p120009-catalog-3x2.png
```

```text
PRODUCT ID: 121553
PRODUCT: FluxPulse S-M079P Plus Smartwatch
SUBJECT: minimalist round graphite smartwatch with a nearly edge-to-edge display,
thin brushed bezel, smooth charcoal sport band, twin subtle side buttons, and an
abstract sand-and-burgundy gradient
COMPOSITION: centered frontal view on a coral plaster plinth; soft overhead
light; deep forest background
SAVE AS: ce-smartwatches-p121553-catalog-3x2.png
```

```text
PRODUCT ID: 121624
PRODUCT: PixelOne S-M712X Active Smartwatch
SUBJECT: athletic square smartwatch in cloud white, reinforced rounded case,
white perforated sport band, protected crown, and an abstract ocean-to-maroon
gradient display
COMPOSITION: crisp side three-quarter view on dark burgundy stone; warm raking
light; pale sand wall
SAVE AS: ce-smartwatches-p121624-catalog-3x2.png
```

```text
PRODUCT ID: 123064
PRODUCT: PixelOne S-M154P Elite Smartwatch
SUBJECT: refined octagonal smartwatch in polished silver, slim faceted bezel,
articulated silver link bracelet, a small knurled crown, and an abstract
forest-and-amber gradient display
COMPOSITION: elevated three-quarter view on honed travertine; narrow shaft of
daylight; plum backdrop
SAVE AS: ce-smartwatches-p123064-catalog-3x2.png
```

```text
PRODUCT ID: 123345
PRODUCT: LumaOne S-M581P Elite Smartwatch
SUBJECT: compact oval-round smartwatch in coral, smooth coral fluoroelastomer
band, domed glass, one flush side button, and an abstract graphite-to-sand
gradient display
COMPOSITION: gently elevated front view on pale oak with the band forming a
clean loop; soft light; muted ocean background
SAVE AS: ce-smartwatches-p123345-catalog-3x2.png
```

## Carbon racing shoes - 8 images

```text
PRODUCT ID: 234487
PRODUCT: AeroPeak CRS-M073P Active Carbon Racing Shoe
SUBJECT: lightweight navy carbon racing shoe with a zero-drop profile, high but
stable rocker cushioning, broad breathable engineered-mesh forefoot, and a thin
dark outsole
COMPOSITION: pure lateral profile on a coral stone block; crisp low daylight;
warm bone plaster backdrop
SAVE AS: rf-carbon-racing-shoes-p234487-catalog-3x2.png
```

```text
PRODUCT ID: 234602
PRODUCT: AeroRun CRS-V340P Pro Carbon Racing Shoe
SUBJECT: forest-green carbon road shoe with a five-millimetre drop, moderate
cushioning, narrow sculpted heel, ribbed knit upper, and a visible but unbranded
carbon plate edge
COMPOSITION: front three-quarter view from the toe on pale limestone; soft side
light; muted plum background
SAVE AS: rf-carbon-racing-shoes-p234602-catalog-3x2.png
```

```text
PRODUCT ID: 236987
PRODUCT: AeroGear CRS-X849X Pro Carbon Racing Shoe
SUBJECT: slate carbon racing flat with a zero-drop low-stack silhouette, dense
woven upper, wide stable forefoot, minimal heel counter, and a thin segmented
outsole
COMPOSITION: top-down diagonal view on warm oak; narrow burgundy strip behind
the heel; diffuse daylight
SAVE AS: rf-carbon-racing-shoes-p236987-catalog-3x2.png
```

```text
PRODUCT ID: 239237
PRODUCT: AeroGear CRS-P351P Pro Carbon Racing Shoe
SUBJECT: cloud-white carbon racing shoe with a six-millimetre drop, dramatic
maximum-cushion foam stack, airy white mesh, sculpted heel flare, and one deep
maroon structural insert
COMPOSITION: low side three-quarter angle on dark forest stone; strong softbox-like
window light; cream wall
SAVE AS: rf-carbon-racing-shoes-p239237-catalog-3x2.png
```

```text
PRODUCT ID: 239707
PRODUCT: AeroPeak CRS-R792P Pro Carbon Racing Shoe
SUBJECT: wide-fit graphite carbon racing shoe with a four-millimetre drop,
maximum cushioning, broad toe box, matte technical mesh, and a thick angular
foam platform
COMPOSITION: medial side profile on sand-colored plaster; low warm light; muted
ocean background
SAVE AS: rf-carbon-racing-shoes-p239707-catalog-3x2.png
```

```text
PRODUCT ID: 240310
PRODUCT: AeroTrail CRS-R172 Pro Carbon Racing Shoe
SUBJECT: substantial slate carbon road shoe with a zero-drop high-cushion
platform, wide fit, ripstop-like woven upper, reinforced heel geometry, and a
full-contact dark outsole
COMPOSITION: rear three-quarter view on a burgundy lacquered block; soft rim
light defining the heel; warm bone wall
SAVE AS: rf-carbon-racing-shoes-p240310-catalog-3x2.png
```

```text
PRODUCT ID: 240787
PRODUCT: AeroPeak CRS-Z872X Active Carbon Racing Shoe
SUBJECT: lightweight coral carbon racing shoe with a five-millimetre drop, high
cushioning, aggressive toe rocker, airy coral knit upper, and a narrow graphite
outsole
COMPOSITION: energetic front three-quarter view on pale travertine; diagonal
daylight; deep forest backdrop
SAVE AS: rf-carbon-racing-shoes-p240787-catalog-3x2.png
```

```text
PRODUCT ID: 241908
PRODUCT: AeroEndurance CRS-C475S Flex Carbon Racing Shoe
SUBJECT: cloud-white zero-drop carbon road shoe with moderate cushioning, subtle
medial stability geometry, a clean white engineered upper, broad heel contact,
and a restrained maroon midsole insert
COMPOSITION: inside medial profile on a graphite surface; soft overhead light;
muted coral plaster background
SAVE AS: rf-carbon-racing-shoes-p241908-catalog-3x2.png
```

## Ergonomic office chairs - 7 images

```text
PRODUCT ID: 370567
PRODUCT: FrameForm EOC-C042 Max Ergonomic Office Chair
SUBJECT: broad high-back graphite mesh task chair built for a larger user, strong
five-star base, substantial adjustable seat, articulated 4D armrests, and a
clearly integrated fixed lumbar structure
COMPOSITION: front three-quarter view on pale oak flooring; warm side light;
soft coral plaster wall
SAVE AS: ho-ergonomic-office-chairs-p370567-catalog-3x2.png
```

```text
PRODUCT ID: 371092
PRODUCT: FormDesk EOC-R524X Flex Ergonomic Office Chair
SUBJECT: compact mid-back graphite mesh office chair with a slim frame, modest
seat depth, simple 2D armrests, an adjustable lumbar pad, and a light five-star
base
COMPOSITION: clean side profile on cream stone flooring; narrow daylight beam;
deep burgundy background
SAVE AS: ho-ergonomic-office-chairs-p371092-catalog-3x2.png
```

```text
PRODUCT ID: 374727
PRODUCT: FrameForm EOC-F424S Tour Ergonomic Office Chair
SUBJECT: forest-green mesh ergonomic chair with a visibly responsive split-back
structure, dynamic lumbar section, compact 3D armrests, and a slender graphite
base
COMPOSITION: rear three-quarter view showing the back engineering on warm
travertine; soft rim light; pale sand wall
SAVE AS: ho-ergonomic-office-chairs-p374727-catalog-3x2.png
```

```text
PRODUCT ID: 375572
PRODUCT: FormDesk EOC-S782P Prime Ergonomic Office Chair
SUBJECT: tall slate mesh all-day task chair with a deep adjustable seat, robust
frame, dynamic lumbar support, 3D armrests, and a wide heavy-duty five-star base
COMPOSITION: near-frontal three-quarter view on a dark forest floor plane; warm
window light; bone plaster backdrop
SAVE AS: ho-ergonomic-office-chairs-p375572-catalog-3x2.png
```

```text
PRODUCT ID: 376102
PRODUCT: SpaceForm EOC-V452 Essential Ergonomic Office Chair
SUBJECT: compact-footprint ocean-blue mesh chair for a smaller room, narrow
shoulders, adjustable lumbar support, precise 4D armrests, a sliding seat, and a
strong but visually light base
COMPOSITION: centered frontal view on pale oak; diffuse light; muted plum wall
SAVE AS: ho-ergonomic-office-chairs-p376102-catalog-3x2.png
```

```text
PRODUCT ID: 377572
PRODUCT: FormDesk EOC-C007S Active Ergonomic Office Chair
SUBJECT: ocean-blue mesh ergonomic chair with a generous recline-ready back,
fixed loop armrests, adjustable lumbar support, a compact seat, and a broad dark
base
COMPOSITION: side three-quarter view suggesting the recline geometry without a
person, on coral stone; soft backlight; warm sand background
SAVE AS: ho-ergonomic-office-chairs-p377572-catalog-3x2.png
```

```text
PRODUCT ID: 378616
PRODUCT: ContourErgonomics EOC-M749 Elite Ergonomic Office Chair
SUBJECT: refined midnight mesh chair with a sculpted narrow-waist back, adjustable
lumbar carriage, precise 4D armrests, an adjustable-depth seat, and a satin-metal
five-star base
COMPOSITION: elevated front three-quarter view on honed limestone; controlled
side light; forest-green plaster wall
SAVE AS: ho-ergonomic-office-chairs-p378616-catalog-3x2.png
```

## Workspace monitors - 9 images

```text
PRODUCT ID: 415136
PRODUCT: FocusStudio PM-M158 Prime Productivity Monitor
SUBJECT: flat 32-inch productivity monitor in graphite, slim even bezels,
height-adjustable central column, compact rectangular base, tidy rear cable
channel, and a soft abstract maroon-to-sand gradient on the screen
COMPOSITION: front three-quarter view on pale oak desk; warm daylight; muted
ocean plaster wall
SAVE AS: ho-productivity-monitors-p415136-catalog-3x2.png
```

```text
PRODUCT ID: 415193
PRODUCT: ModuWorks PM-C273X Ultra Productivity Monitor
SUBJECT: substantial flat 32-inch productivity monitor in stone, thin bezel,
height-adjustable brushed-metal stand, broad low base, discreet USB-C connection,
and an abstract forest-and-amber gradient on the screen
COMPOSITION: almost frontal view on a burgundy desk surface; soft overhead light;
bone wall
SAVE AS: ho-productivity-monitors-p415193-catalog-3x2.png
```

```text
PRODUCT ID: 420496
PRODUCT: FocusStudio UM-C406X Studio Ultrawide Monitor
SUBJECT: slate 32-inch wide-format monitor with an ultra-thin IPS panel, crisp
angular rear housing, fixed low T-shaped stand, narrow bezels, and an abstract
coral-to-graphite gradient on the screen
COMPOSITION: side three-quarter view on travertine desk; directional window
light; pale sand background
SAVE AS: ho-ultrawide-monitors-p420496-catalog-3x2.png
```

```text
PRODUCT ID: 420607
PRODUCT: WorkErgonomics UM-P525S Studio Ultrawide Monitor
SUBJECT: forest-green 32-inch wide-format monitor with a clean IPS panel,
height-adjustable central column, rounded rectangular base, subtly textured rear
shell, and an abstract warm sand-and-burgundy screen gradient
COMPOSITION: straight-on front view on pale oak; soft symmetrical daylight;
cream plaster wall
SAVE AS: ho-ultrawide-monitors-p420607-catalog-3x2.png
```

```text
PRODUCT ID: 421678
PRODUCT: ModuDesk UM-V272X Prime Ultrawide Monitor
SUBJECT: graphite 32-inch wide-format monitor with an exceptionally thin
high-refresh panel, fixed minimalist pedestal, low-profile V-shaped base, sharp
bezel geometry, and an abstract ocean-to-maroon gradient on the screen
COMPOSITION: low front three-quarter angle on dark forest stone; warm rim light;
pale bone backdrop
SAVE AS: ho-ultrawide-monitors-p421678-catalog-3x2.png
```

```text
PRODUCT ID: 421833
PRODUCT: ModuWorks UM-C025 Prime Ultrawide Monitor
SUBJECT: forest-finish 32-inch wide-format monitor with a practical IPS panel,
substantial height-adjustable column, broad stable foot, discreet rear cable
management, and an abstract coral-and-sand gradient on the screen
COMPOSITION: side profile turned slightly toward camera on a cream desk; soft
late-afternoon light; plum wall
SAVE AS: ho-ultrawide-monitors-p421833-catalog-3x2.png
```

```text
PRODUCT ID: 422221
PRODUCT: WorkLab UM-M423S Core Ultrawide Monitor
SUBJECT: charcoal 32-inch wide-format monitor with a restrained flat IPS panel,
fixed compact stand, nearly invisible top and side bezels, a clean matte rear,
and an abstract amber-to-forest gradient on the screen
COMPOSITION: centered frontal view on a coral-toned stone desk; diffuse daylight;
warm sand backdrop
SAVE AS: ho-ultrawide-monitors-p422221-catalog-3x2.png
```

```text
PRODUCT ID: 422310
PRODUCT: AxisOffice UM-M725 Studio Ultrawide Monitor
SUBJECT: sand-finish super-ultrawide 32-inch Mini-LED workspace display, very wide
cinematic panel, height-adjustable brushed-metal column, elegant arc-shaped base,
thin bezels, and an abstract maroon-and-gold gradient on the screen
COMPOSITION: low front three-quarter view on graphite stone; controlled side
light; pale oak wall
SAVE AS: ho-ultrawide-monitors-p422310-catalog-3x2.png
```

```text
PRODUCT ID: 422329
PRODUCT: WorkSystems UM-P431S Edge Ultrawide Monitor
SUBJECT: plum 32-inch wide-format Mini-LED monitor with a thin flat panel, fixed
asymmetrical metal stand, faceted rear shell, restrained dark bezels, and an
abstract forest-to-sand gradient on the screen
COMPOSITION: front three-quarter view from the right on pale limestone; narrow
shaft of daylight; muted burgundy background
SAVE AS: ho-ultrawide-monitors-p422329-catalog-3x2.png
```

## Running and fitness Search/Discover extension - 16 images

```text
PRODUCT ID: 290496
PRODUCT: PeakOne GRW-K406 Essential GPS Running Watch
SUBJECT: compact plum GPS running watch with a sealed 10-ATM round case, plum
sport band, optical heart-rate sensor, and an abstract sand-to-burgundy display;
the product supports GPS, sleep tracking, and a 24-day battery
COMPOSITION: upright three-quarter view on pale limestone; soft side light
catching the case edge; muted forest backdrop
SAVE AS: rf-gps-running-watches-p290496-catalog-3x2.png
```

```text
PRODUCT ID: 219652
PRODUCT: AtlasRun RRS-M198S Flex Road Running Shoe
SUBJECT: one extra-wide midnight road running shoe with a five-millimetre drop,
moderate cushioning, neutral support, breathable technical upper, and no carbon
plate or waterproof membrane
COMPOSITION: clean lateral profile on a coral stone block; low directional
daylight; warm bone plaster background
SAVE AS: rf-road-running-shoes-p219652-catalog-3x2.png
```

```text
PRODUCT ID: 230754
PRODUCT: PeakFit TRS-M648 Core Trail Running Shoe
SUBJECT: one slate waterproof trail running shoe with an eight-millimetre drop,
low cushioning, neutral support, a broad mixed-width forefoot, reinforced toe,
and deeply lugged trail outsole
COMPOSITION: front three-quarter view on dark forest stone; raking light across
the outsole; pale sand wall
SAVE AS: rf-trail-running-shoes-p230754-catalog-3x2.png
```

```text
PRODUCT ID: 339413
PRODUCT: AtlasLab T-F437X Flex Treadmill
SUBJECT: compact plum folding treadmill with a mechanically plausible hinged
deck, 13.1-square-foot footprint, sturdy rails, a centered abstract-gradient
console, and controls suggesting 27 resistance levels without text or numbers
COMPOSITION: side three-quarter view on pale oak flooring; warm window light;
graphite plaster background
SAVE AS: rf-treadmills-p339413-catalog-3x2.png
```

```text
PRODUCT ID: 359560
PRODUCT: RiseLab RB-N337P Prime Recovery Boot
SUBJECT: one full-length midnight recovery boot in washable natural-rubber
material, medium firmness, portable construction, articulated compression
chambers, and a clean closed toe with no lettering
COMPOSITION: gently curved diagonal arrangement on honed travertine; soft
overhead light; muted coral backdrop
SAVE AS: rf-recovery-boots-p359560-catalog-3x2.png
```

```text
PRODUCT ID: 269854
PRODUCT: TempoDynamics RS-A913 Prime Running Short
SUBJECT: one coral relaxed-fit running short in moisture-wicking recycled
polyester, clean unbranded waistband, lightweight drape, and no reflective trim
or weatherproof coating
COMPOSITION: precise flat lay on deep burgundy paper with the complete garment
visible; diffuse daylight; narrow bone border
SAVE AS: rf-running-shorts-p269854-catalog-3x2.png
```

```text
PRODUCT ID: 349236
PRODUCT: RiseTrail HV-K867S Flex Hydration Vest
SUBJECT: sand-finish running hydration vest with a close bounce-free profile,
integrated insulated and leakproof 750-millilitre hydration capacity, slim
shoulder straps, and practical front-access storage with no labels
COMPOSITION: centered frontal view on a graphite plinth; soft side light defining
the webbing; muted ocean wall
SAVE AS: rf-hydration-vests-p349236-catalog-3x2.png
```

```text
PRODUCT ID: 331992
PRODUCT: AeroRun FR-S480P Essential Foam Roller
SUBJECT: one portable 40-centimetre cork foam roller with a natural cork body,
washable surface, restrained silver end caps, and a consistent fine-grain
texture
COMPOSITION: low diagonal view on a plum stone surface; narrow warm rim light;
pale oak backdrop
SAVE AS: rf-foam-rollers-p331992-catalog-3x2.png
```

```text
PRODUCT ID: 341048
PRODUCT: PeakWorks EB-A779P Flex Exercise Bike
SUBJECT: charcoal folding exercise bike with a compact 11.5-square-foot stance,
reinforced frame for a 400-pound user, quiet enclosed resistance housing, an
18-level adjustment dial, and no connected display
COMPOSITION: side profile on cream plaster flooring; soft late-afternoon light;
deep forest background
SAVE AS: rf-exercise-bikes-p341048-catalog-3x2.png
```

```text
PRODUCT ID: 244572
PRODUCT: VeloEndurance SRS-K449P Pro Stability Running Shoe
SUBJECT: one stone road stability shoe with a six-millimetre drop, high
cushioning, wide supportive platform, subtle medial guidance geometry,
lightweight mesh upper, and an integrated carbon plate
COMPOSITION: medial three-quarter view on burgundy stone; crisp side light;
warm sand plaster wall
SAVE AS: rf-stability-running-shoes-p244572-catalog-3x2.png
```

```text
PRODUCT ID: 300820
PRODUCT: AeroTrail RP-E430 Flex Running Pod
SUBJECT: compact sage clip-on running pod with a sealed 5-ATM shell, small
optical sensor window, mechanically plausible shoe clip, and no screen; the
device supports GPS, heart-rate, sleep, and training-readiness data
COMPOSITION: elevated macro view on pale limestone; soft focused light; muted
plum background
SAVE AS: rf-running-pods-p300820-catalog-3x2.png
```

```text
PRODUCT ID: 282664
PRODUCT: TempoDynamics WJ-X973S Plus Weatherproof Jacket
SUBJECT: one slim slate running jacket in a moisture-wicking merino blend,
clean high collar, articulated sleeves, minimal seam structure, and no reflective
trim or visible weatherproof coating
COMPOSITION: complete garment arranged in a natural folded-open pose on pale
oak; soft leafy shadow play; coral plaster backdrop
SAVE AS: rf-weatherproof-jackets-p282664-catalog-3x2.png
```

```text
PRODUCT ID: 312212
PRODUCT: TempoEndurance K-F865P Core Kettlebell
SUBJECT: one fixed, non-adjustable midnight kettlebell from a 10-to-90-pound
range, with a broad cast handle, stable flat base, compact body, and matte
unbranded finish
COMPOSITION: low front three-quarter view on warm limestone; controlled rim
light defining the handle; muted ocean wall
SAVE AS: rf-kettlebells-p312212-catalog-3x2.png
```

```text
PRODUCT ID: 336420
PRODUCT: TempoFit BT-R142P Edge Balance Trainer
SUBJECT: one charcoal 134-centimetre balance trainer in soft high-density foam,
with an elongated stable profile, subtly textured top, firm flat underside, and
non-portable studio construction
COMPOSITION: shallow side angle on a coral floor plane; diffuse overhead light;
pale bone backdrop
SAVE AS: rf-balance-trainers-p336420-catalog-3x2.png
```

```text
PRODUCT ID: 309364
PRODUCT: TerrainMotion AD-N618X Core Adjustable Dumbbell
SUBJECT: one graphite commercial-grade adjustable dumbbell spanning a
10-to-50-pound range, with compact nested plates, a mechanically plausible
selector mechanism, sturdy central grip, and foldable storage geometry
COMPOSITION: front three-quarter view on dark forest stone; warm side light
across the plate edges; sand plaster background
SAVE AS: rf-adjustable-dumbbells-p309364-catalog-3x2.png
```

```text
PRODUCT ID: 329300
PRODUCT: FlexPeak YM-Z466X Pro Yoga Mat
SUBJECT: one ocean-blue 182-centimetre EVA yoga mat with variable-density
cushioning, finely textured grip surface, clean unbranded edges, and a portable
partially rolled form that keeps the entire mat visible
COMPOSITION: diagonal top-down view on cream plaster; narrow burgundy edge in the
background; soft natural contact shadows
SAVE AS: rf-yoga-mats-p329300-catalog-3x2.png
```

## Home office Search/Discover extension - 15 images

```text
PRODUCT ID: 431298
PRODUCT: WorkOffice QK-X281P Plus Quiet Keyboard
SUBJECT: coral split wireless keyboard with low-profile scissor switches,
meeting-friendly quiet key action, restrained abstract backlighting, and clean
unprinted keycaps in a macOS, Windows, and Linux-compatible layout
COMPOSITION: precise top-down view on pale oak; soft window light; deep burgundy
paper entering one corner
SAVE AS: ho-quiet-keyboards-p431298-catalog-3x2.png
```

```text
PRODUCT ID: 438991
PRODUCT: ModuCollective T-E221P Edge Trackball
SUBJECT: sage right-handed wired trackball with a large central ball, seven
mechanically distinct unlabelled buttons, low zero-degree wrist angle, compact
131-gram body, and a clean precision-focused silhouette
COMPOSITION: eye-level three-quarter view on cream stone; soft side light; muted
coral plaster backdrop
SAVE AS: ho-trackballs-p438991-catalog-3x2.png
```

```text
PRODUCT ID: 396896
PRODUCT: FocusStudio ESD-C473S Max Electric Standing Desk
SUBJECT: compact graphite electric standing desk with a 42-by-27-inch top,
24-to-50-inch lift range, integrated cable channel, strong twin-leg frame, and a
simple unlabelled rocker control with no memory-preset buttons
COMPOSITION: front three-quarter view on pale oak flooring; warm daylight;
forest-green wall
SAVE AS: ho-electric-standing-desks-p396896-catalog-3x2.png
```

```text
PRODUCT ID: 495346
PRODUCT: FormLab SMD-R838S Plus Sound Masking Device
SUBJECT: plum freestanding sound-masking device with a compact acoustic enclosure,
finely perforated face, recycled-material texture, stable low base, and a form
suited to roughly 78 square feet of focused coverage
COMPOSITION: centered side three-quarter view on honed travertine; controlled
overhead light; warm bone background
SAVE AS: ho-sound-masking-devices-p495346-catalog-3x2.png
```

```text
PRODUCT ID: 427431
PRODUCT: StudioForm MA-E217 Studio Monitor Arm
SUBJECT: one sand-finish fixed-height monitor arm sized for a 34-inch display,
with a robust desk clamp, articulated but mechanically constrained joints,
integrated cable path, and an empty unbranded VESA mounting plate
COMPOSITION: side profile clamped to a narrow graphite desk edge; raking light
showing the joints; muted plum wall
SAVE AS: ho-monitor-arms-p427431-catalog-3x2.png
```

```text
PRODUCT ID: 483208
PRODUCT: SpaceLiving DS-F828X Air Docking Station
SUBJECT: compact forest-green docking station with four display outputs, one
clearly distinct Ethernet port, a low ventilated enclosure, restrained metal
edge detail, and no port labels or lettering
COMPOSITION: elevated front three-quarter view on pale limestone; warm side
light; coral plaster backdrop
SAVE AS: ho-docking-stations-p483208-catalog-3x2.png
```

```text
PRODUCT ID: 419917
PRODUCT: BalanceSystems PM-X586S Tour Productivity Monitor
SUBJECT: sage 34-inch Mini-LED productivity monitor with a 3440x1440 wide panel,
120-hertz proportions, fixed non-height-adjustable stand, clean rear housing,
45-watt USB-C connection, and an abstract maroon-to-sand screen gradient
COMPOSITION: nearly frontal view on a burgundy desk surface; diffuse daylight;
pale bone wall
SAVE AS: ho-productivity-monitors-p419917-catalog-3x2.png
```

```text
PRODUCT ID: 467602
PRODUCT: WorkLiving CM-R414X Tour Cable Management — Forest
SUBJECT: forest-green travel-ready cable-management power hub with a compact GaN
enclosure, six recessed ports, high-capacity 240-watt USB-C power delivery,
integrated cable routing grooves, and no labels or status text
COMPOSITION: top-down diagonal arrangement on warm sandstone; one attached cable
coiled within the built-in routing path; muted ocean background
SAVE AS: ho-cable-management-p467602-catalog-3x2.png
```

```text
PRODUCT ID: 493034
PRODUCT: StudioLiving AP-E372X Elite Acoustic Panel
SUBJECT: one large stone-finish acoustic panel with a deep sound-absorbing core,
crisp wrapped edges, subtle woven texture, and a restrained architectural form
designed for broad workspace coverage
COMPOSITION: upright three-quarter view resting on pale oak; side light revealing
the textile depth; deep forest backdrop
SAVE AS: ho-acoustic-panels-p493034-catalog-3x2.png
```

```text
PRODUCT ID: 451129
PRODUCT: NestHome CL-M785S Max Circadian Lighting
SUBJECT: stone-finish circadian task light with a broad glare-controlled head,
slim adjustable stem, stable compact base, automatic-dimming sensor, cool
6500-kelvin output, and no USB port or visible controls
COMPOSITION: low side three-quarter view on coral stone; soft pool of neutral
light; warm sand plaster background
SAVE AS: ho-circadian-lighting-p451129-catalog-3x2.png
```

```text
PRODUCT ID: 462111
PRODUCT: StudioForm DU-X119X Air Drawer Unit
SUBJECT: charcoal 24-inch wall-mounted drawer unit in recycled plastic, with a
single clean modular body, tool-free mounting geometry, flush drawer fronts, and
small unlabelled recessed pulls
COMPOSITION: front three-quarter view mounted against muted plum plaster; soft
side light; pale limestone floor plane
SAVE AS: ho-drawer-units-p462111-catalog-3x2.png
```

```text
PRODUCT ID: 408935
PRODUCT: FormLiving SDC-S697 Ultra Standing Desk Converter
SUBJECT: graphite 55-by-20-inch standing desk converter with a 24-to-50-inch
height range, two unlabelled memory controls, high 355-pound load capacity,
stable lifting arms, and no integrated cable-management channel
COMPOSITION: side three-quarter view on a pale oak work surface; directional
window light; muted coral wall
SAVE AS: ho-standing-desk-converters-p408935-catalog-3x2.png
```

```text
PRODUCT ID: 453684
PRODUCT: QuietSpace CW-P494S Ultra Conference Webcam
SUBJECT: graphite 4K conference webcam with a compact 78-degree lens housing,
six-microphone array expressed as small symmetric acoustic openings,
noise-reduction hardware, a sturdy monitor clip, and no USB-C port
COMPOSITION: eye-level macro view on cream stone; soft rim light; deep burgundy
background
SAVE AS: ho-conference-webcams-p453684-catalog-3x2.png
```

```text
PRODUCT ID: 459799
PRODUCT: ArcCollective CH-M650P Essential Conference Headset
SUBJECT: coral foldable over-ear conference headset with soft oval cushions,
slim boom microphone, multipoint Bluetooth and wireless-USB construction,
40-hour battery proportions, and a sealed IPX4 shell without ANC controls
COMPOSITION: front three-quarter view on graphite stone; warm side light;
pale sand plaster backdrop
SAVE AS: ho-conference-headsets-p459799-catalog-3x2.png
```

```text
PRODUCT ID: 473960
PRODUCT: AxisLiving F-S736S Air Footrest
SUBJECT: one sage adjustable memory-foam footrest with a four-to-eight-inch
height range, gently angled support surface, removable textured cover, and a
stable base rated for 50 pounds
COMPOSITION: low side view on warm oak flooring; diffuse daylight; muted ocean
wall
SAVE AS: ho-footrests-p473960-catalog-3x2.png
```

## Delivery

Keep the 80 PNGs in one folder. Before integration, verify:

1. There are exactly 80 files and every filename matches a `SAVE AS` line.
2. Every image is 1536x1024 landscape.
3. No image contains readable text, a logo, a watermark, a UI, or a contact
   sheet.
4. Products in the same category remain visibly distinct at thumbnail size.
5. The product finish and structural description match the corresponding SHOT.

`data/media/asset_labels_200.json` owns these 80 bindings together with the
original premium 120. The importer accepts only names in that single manifest;
the generator marks a row installed and records its runtime SHA-256 only after
the corresponding WebP exists.
