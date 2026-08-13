# Category plate prompts

Copy a block, paste it into ChatGPT, save each returned image under the filename
its `SHOT` line names. Nothing to run until the images are on disk.

- **18 messages**, 115 product plates, plus one outstanding still-life at the end.
- **Generate at 1536x1024 landscape.** ChatGPT offers 1024x1024, 1536x1024 and
  1024x1536; the card frame is 3:2 landscape, so a portrait source gets cropped
  down the middle.
- Why the plates exist, how many each category needs, and what the code does with
  them: `docs/image-prompts-category-plates.md`.

## Check every batch before importing

1. **Separate files, not a contact sheet.** A 2x2 sheet sliced into four plates
   leaves each at 512px, under what the card needs at device pixel ratio 2. Each
   block says so explicitly; verify it was obeyed.
2. **No invented wordmarks.** Zoom the keycaps, the earcups, the shoe heel, the
   monitor bezel. Generators composite plausible-looking brand marks onto
   fictional products, and this is a public `aws-samples` repository. Regenerate
   rather than accept. That defect is why the per-category constraint lines in
   each block exist.
3. **No legible screen UI.** Displays must show a soft abstract warm gradient.

## Import

Rename the downloads to the `SHOT` filenames, put them in one folder, then:

```bash
uv run python scripts/import_generated_images.py --source ~/Downloads/batch --dry-run
uv run python scripts/import_generated_images.py --source ~/Downloads/batch
```

The importer crops to 3:2, resizes to 1200x800, writes WebP at quality 88, and
records `installed: true` plus the file's sha256 in
`data/media/category_plates.json`. A filename it does not recognise is refused,
not guessed at. **The runtime serves only installed plates**, so a plate that is
generated and converted but not recorded never reaches a card.

Order within a category is the cheap kind of mistake: plates are not bound to
products, so swapping plate-04 and plate-05 changes no card, only the accuracy of
that plate's subject line here. Crossing categories is the expensive kind, and
every block covers one category, so it cannot happen inside a block.

## Progress

Tick as each plate is installed. `data/media/category_plates.json` is the
authority — the importer writes `installed: true` there, and the runtime reads
that field, not this list.

**quiet-keyboards** — 10 of 10 installed

- [x] `ho-quiet-keyboards-plate-01-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-02-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-03-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-04-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-05-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-06-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-07-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-08-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-09-catalog-3x2.png`
- [x] `ho-quiet-keyboards-plate-10-catalog-3x2.png`

**road-running-shoes** — 10 of 10 installed

- [x] `rf-road-running-shoes-plate-01-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-02-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-03-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-04-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-05-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-06-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-07-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-08-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-09-catalog-3x2.png`
- [x] `rf-road-running-shoes-plate-10-catalog-3x2.png`

**over-ear-headphones** — 6 of 6 installed

- [x] `ce-over-ear-headphones-plate-01-catalog-3x2.png`
- [x] `ce-over-ear-headphones-plate-02-catalog-3x2.png`
- [x] `ce-over-ear-headphones-plate-03-catalog-3x2.png`
- [x] `ce-over-ear-headphones-plate-04-catalog-3x2.png`
- [x] `ce-over-ear-headphones-plate-05-catalog-3x2.png`
- [x] `ce-over-ear-headphones-plate-06-catalog-3x2.png`

**ergonomic-office-chairs** — 9 of 9 installed

- [x] `ho-ergonomic-office-chairs-plate-01-catalog-3x2.png`
- [x] `ho-ergonomic-office-chairs-plate-02-catalog-3x2.png`
- [x] `ho-ergonomic-office-chairs-plate-03-catalog-3x2.png`
- [x] `ho-ergonomic-office-chairs-plate-04-catalog-3x2.png`
- [x] `ho-ergonomic-office-chairs-plate-05-catalog-3x2.png`
- [x] `ho-ergonomic-office-chairs-plate-06-catalog-3x2.png`
- [x] `ho-ergonomic-office-chairs-plate-07-catalog-3x2.png`
- [x] `ho-ergonomic-office-chairs-plate-08-catalog-3x2.png`
- [x] `ho-ergonomic-office-chairs-plate-09-catalog-3x2.png`

**charging-docks** — 11 of 11 installed

- [x] `ce-charging-docks-plate-01-catalog-3x2.png`
- [x] `ce-charging-docks-plate-02-catalog-3x2.png`
- [x] `ce-charging-docks-plate-03-catalog-3x2.png`
- [x] `ce-charging-docks-plate-04-catalog-3x2.png`
- [x] `ce-charging-docks-plate-05-catalog-3x2.png`
- [x] `ce-charging-docks-plate-06-catalog-3x2.png`
- [x] `ce-charging-docks-plate-07-catalog-3x2.png`
- [x] `ce-charging-docks-plate-08-catalog-3x2.png`
- [x] `ce-charging-docks-plate-09-catalog-3x2.png`
- [x] `ce-charging-docks-plate-10-catalog-3x2.png`
- [x] `ce-charging-docks-plate-11-catalog-3x2.png`

**mesh-wi-fi-systems** — 11 of 11 installed

- [x] `ce-mesh-wi-fi-systems-plate-01-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-02-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-03-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-04-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-05-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-06-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-07-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-08-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-09-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-10-catalog-3x2.png`
- [x] `ce-mesh-wi-fi-systems-plate-11-catalog-3x2.png`

**treadmills** — 11 of 12 installed

- [x] `rf-treadmills-plate-01-catalog-3x2.png`
- [x] `rf-treadmills-plate-02-catalog-3x2.png`
- [x] `rf-treadmills-plate-03-catalog-3x2.png`
- [x] `rf-treadmills-plate-04-catalog-3x2.png`
- [x] `rf-treadmills-plate-05-catalog-3x2.png`
- [x] `rf-treadmills-plate-06-catalog-3x2.png`
- [x] `rf-treadmills-plate-07-catalog-3x2.png`
- [ ] `rf-treadmills-plate-08-catalog-3x2.png`
- [x] `rf-treadmills-plate-09-catalog-3x2.png`
- [x] `rf-treadmills-plate-10-catalog-3x2.png`
- [x] `rf-treadmills-plate-11-catalog-3x2.png`
- [x] `rf-treadmills-plate-12-catalog-3x2.png`

**mobility-tools** — 11 of 11 installed

- [x] `rf-mobility-tools-plate-01-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-02-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-03-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-04-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-05-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-06-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-07-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-08-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-09-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-10-catalog-3x2.png`
- [x] `rf-mobility-tools-plate-11-catalog-3x2.png`

**electric-standing-desks** — 10 of 11 installed

- [x] `ho-electric-standing-desks-plate-01-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-02-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-03-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-04-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-05-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-06-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-07-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-08-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-09-catalog-3x2.png`
- [ ] `ho-electric-standing-desks-plate-10-catalog-3x2.png`
- [x] `ho-electric-standing-desks-plate-11-catalog-3x2.png`

**sound-masking-devices** — 12 of 12 installed

- [x] `ho-sound-masking-devices-plate-01-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-02-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-03-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-04-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-05-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-06-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-07-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-08-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-09-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-10-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-11-catalog-3x2.png`
- [x] `ho-sound-masking-devices-plate-12-catalog-3x2.png`

**lumbar-supports** — 12 of 12 installed

- [x] `ho-lumbar-supports-plate-01-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-02-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-03-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-04-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-05-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-06-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-07-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-08-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-09-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-10-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-11-catalog-3x2.png`
- [x] `ho-lumbar-supports-plate-12-catalog-3x2.png`

**domain-neutral still-lifes** — 3 of 3 installed

- [x] `ce-domain-neutral-catalog-3x2.png`
- [x] `rf-domain-neutral-catalog-3x2.png`
- [x] `ho-domain-neutral-catalog-3x2.png`

## The prompts


### Message 1 of 18 — quiet-keyboards, 10 shots

`plate-01` is already installed. Either drop SHOT 1 and ask for nine, or keep it
and discard the new one; the importer overwrites, so do not import a worse copy.

```text
Generate 10 separate photographs, one per SHOT below.

Return 10 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- Keycaps are completely blank. No printed legends, letters, numbers, symbols or icons of any kind on any key
- No badge, nameplate or brand mark anywhere on the case, base or cable

SHOT 1 - save as ho-quiet-keyboards-plate-01-catalog-3x2.png
SUBJECT: a 65% compact quiet wireless mechanical keyboard in warm bone, cream blank keycaps, one deep maroon escape keycap, on a thin aluminium base
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ho-quiet-keyboards-plate-02-catalog-3x2.png
SUBJECT: a full-size quiet wireless keyboard with a separate number pad section, soft taupe case, warm grey blank keycaps, slim wedge profile
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ho-quiet-keyboards-plate-03-catalog-3x2.png
SUBJECT: a tenkeyless low-profile quiet keyboard in cream with a brushed champagne top plate and flat blank chiclet keys
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ho-quiet-keyboards-plate-04-catalog-3x2.png
SUBJECT: a split ergonomic quiet wireless keyboard in two separate halves, warm sand plastic, sculpted blank keys, the halves set about ten centimetres apart
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ho-quiet-keyboards-plate-05-catalog-3x2.png
SUBJECT: a compact quiet keyboard machined from graphite anodised aluminium with warm bone blank keycaps in a high sculpted profile
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ho-quiet-keyboards-plate-06-catalog-3x2.png
SUBJECT: a 75% quiet keyboard in bone with an integrated cream leather wrist rest along its front edge
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 7 - save as ho-quiet-keyboards-plate-07-catalog-3x2.png
SUBJECT: a slim charcoal quiet keyboard with soft grey blank keycaps and a thin brass accent strip along the top edge
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 8 - save as ho-quiet-keyboards-plate-08-catalog-3x2.png
SUBJECT: a compact quiet wireless keyboard in warm white with a knurled aluminium rotary dial set into the top right corner
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 9 - save as ho-quiet-keyboards-plate-09-catalog-3x2.png
SUBJECT: a full-size quiet keyboard in warm greige with deep taupe blank keycaps, its plain rear case edge and two folding feet toward the camera, resting on a folded cream felt desk mat
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 10 - save as ho-quiet-keyboards-plate-10-catalog-3x2.png
SUBJECT: a low-profile quiet wireless keyboard in sand with cream blank keycaps, tilted up on two small folding feet at the rear
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 2 of 18 — road-running-shoes, 10 shots

```text
Generate 10 separate photographs, one per SHOT below.

Return 10 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- No side logo, swoosh, stripe device, wordmark or heel badge. The upper and midsole are plain
- No printed text on the tongue, heel tab, insole or outsole

SHOT 1 - save as rf-road-running-shoes-plate-01-catalog-3x2.png
SUBJECT: a single high-stack max-cushion road running trainer with a cream engineered knit upper, a thick bone foam midsole and a deep maroon outsole
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as rf-road-running-shoes-plate-02-catalog-3x2.png
SUBJECT: a lightweight daily road running trainer in warm sand mesh with a taupe midsole and a moulded heel counter
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as rf-road-running-shoes-plate-03-catalog-3x2.png
SUBJECT: a stability road running shoe in bone knit with a wide taupe midsole and a deep maroon medial support wedge
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as rf-road-running-shoes-plate-04-catalog-3x2.png
SUBJECT: a thin-midsole tempo road shoe in cream mesh on a sand midsole, laces tied and the bow tucked under the crossings
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as rf-road-running-shoes-plate-05-catalog-3x2.png
SUBJECT: a laceless knit-collar slip-on road running shoe in warm greige with a wide heel pull tab
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as rf-road-running-shoes-plate-06-catalog-3x2.png
SUBJECT: a pair of road running shoes in charcoal knit on cream midsoles, one shoe standing upright and the second lying on its side just behind it
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 7 - save as rf-road-running-shoes-plate-07-catalog-3x2.png
SUBJECT: a road running trainer in warm white with a rocker-shaped bone midsole, its heel counter and plain outer wall toward the camera
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 8 - save as rf-road-running-shoes-plate-08-catalog-3x2.png
SUBJECT: a pair of breathable summer road running shoes in open sand mesh with cream laces, set side by side
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 9 - save as rf-road-running-shoes-plate-09-catalog-3x2.png
SUBJECT: a plush recovery-leaning road trainer with taupe suede-look overlays over cream mesh on a bone midsole
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 10 - save as rf-road-running-shoes-plate-10-catalog-3x2.png
SUBJECT: a cream road running shoe with a deep maroon heel clip, standing on a small travertine block with the toe raised
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 3 of 18 — over-ear-headphones, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- The outer face of each earcup is a plain smooth surface: no logo, no badge, no engraved wordmark, no maker's mark
- No lettering on the headband, sliders, buttons or ports

SHOT 1 - save as ce-over-ear-headphones-plate-01-catalog-3x2.png
SUBJECT: over-ear headphones in warm bone with cream memory-foam earpads and a matte champagne yoke, standing upright on the surface
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ce-over-ear-headphones-plate-02-catalog-3x2.png
SUBJECT: over-ear headphones in graphite with warm taupe leather earpads, folded flat and lying on the surface
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ce-over-ear-headphones-plate-03-catalog-3x2.png
SUBJECT: over-ear headphones in cream with a woven sand fabric headband and exposed brushed brass height sliders
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ce-over-ear-headphones-plate-04-catalog-3x2.png
SUBJECT: over-ear headphones in soft taupe with deep maroon inner earcup padding, one earcup rotated flat toward the camera
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ce-over-ear-headphones-plate-05-catalog-3x2.png
SUBJECT: over-ear headphones in bone with a slim sculpted headband and matte sand earcups, resting on a low travertine block
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ce-over-ear-headphones-plate-06-catalog-3x2.png
SUBJECT: over-ear headphones in warm greige with visible cream saddle stitching along the headband
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 4 of 18 — ergonomic-office-chairs, 9 shots

```text
Generate 9 separate photographs, one per SHOT below.

Return 9 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- No brand plate on the base, backrest or gas lift, and no printed labels or care tags on the mesh or upholstery
- The chair is empty: no person, no jacket, no bag on it

SHOT 1 - save as ho-ergonomic-office-chairs-plate-01-catalog-3x2.png
SUBJECT: a mesh-back ergonomic office chair with a warm bone frame, sand mesh back, cream seat cushion and a five-star base on castors
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ho-ergonomic-office-chairs-plate-02-catalog-3x2.png
SUBJECT: an ergonomic office chair with a deep taupe mesh back, an adjustable headrest and a matte champagne aluminium base
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ho-ergonomic-office-chairs-plate-03-catalog-3x2.png
SUBJECT: a high-back ergonomic office chair in cream with a deep maroon lumbar pad and bone armrests
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ho-ergonomic-office-chairs-plate-04-catalog-3x2.png
SUBJECT: a compact armless mesh task chair in warm sand with the gas lift and castors clearly visible
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ho-ergonomic-office-chairs-plate-05-catalog-3x2.png
SUBJECT: an ergonomic office chair with a sculpted bone outer shell, warm grey mesh and a waterfall seat edge
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ho-ergonomic-office-chairs-plate-06-catalog-3x2.png
SUBJECT: an executive ergonomic office chair in taupe woven fabric with a wide headrest and cream piping along the seams
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 7 - save as ho-ergonomic-office-chairs-plate-07-catalog-3x2.png
SUBJECT: an ergonomic office chair in bone with a translucent sand mesh back through which the frame is visible
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 8 - save as ho-ergonomic-office-chairs-plate-08-catalog-3x2.png
SUBJECT: a mesh ergonomic office chair in charcoal with cream mesh, a deep maroon seat trim and the armrests folded up
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 9 - save as ho-ergonomic-office-chairs-plate-09-catalog-3x2.png
SUBJECT: a wide-seat ergonomic office chair in warm greige with a separately adjustable lumbar panel at the base of the backrest
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 5 of 18 — charging-docks, batch 1 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- Every port is an unlabelled opening. No port legends, no icons, no letters beside any socket
- No badge or nameplate on the top, front or base, and no lit indicator text

SHOT 1 - save as ce-charging-docks-plate-01-catalog-3x2.png
SUBJECT: a compact aluminium USB-C desktop dock in warm champagne with a row of unlabelled ports along its rear edge and a short braided cream tail cable
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ce-charging-docks-plate-02-catalog-3x2.png
SUBJECT: a slim bone-white USB-C hub the size of a playing card with four unmarked ports along one long side, lying flat
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ce-charging-docks-plate-03-catalog-3x2.png
SUBJECT: a vertical laptop docking station in brushed graphite standing upright, a wide empty slot along its top face
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ce-charging-docks-plate-04-catalog-3x2.png
SUBJECT: a wedge-shaped taupe dock with a circular recessed wireless charging pad moulded into its upper surface
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ce-charging-docks-plate-05-catalog-3x2.png
SUBJECT: a cylindrical charging dock in warm sand aluminium with a single deep maroon anodised ring around its base
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ce-charging-docks-plate-06-catalog-3x2.png
SUBJECT: a clamp-on under-desk dock in cream painted steel with a braided cable looping up from its rear edge
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 6 of 18 — charging-docks, batch 2 of 2, 5 shots

```text
Generate 5 separate photographs, one per SHOT below.

Return 5 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- Every port is an unlabelled opening. No port legends, no icons, no letters beside any socket
- No badge or nameplate on the top, front or base, and no lit indicator text

SHOT 1 - save as ce-charging-docks-plate-07-catalog-3x2.png
SUBJECT: a stacked two-tier dock in bone plastic with a smooth blank front face and fine cooling vents across the rear
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ce-charging-docks-plate-08-catalog-3x2.png
SUBJECT: a folding travel dock in soft taupe with a hinged flip-out stand leg extended behind it
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ce-charging-docks-plate-09-catalog-3x2.png
SUBJECT: a flat rectangular dock in warm greige with a textured cream fabric top panel and no visible markings
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ce-charging-docks-plate-10-catalog-3x2.png
SUBJECT: a dock with an integrated angled phone cradle in champagne aluminium and a bone silicone insert
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ce-charging-docks-plate-11-catalog-3x2.png
SUBJECT: a chunky desktop dock in matte charcoal with a machined bevel edge and one small unlit indicator dot
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 7 of 18 — mesh-wi-fi-systems, batch 1 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- The front face is completely plain: no logo, no wordmark, no model number, no status text
- No illuminated display and no lit ring showing characters

SHOT 1 - save as ce-mesh-wi-fi-systems-plate-01-catalog-3x2.png
SUBJECT: a pair of rounded cylindrical mesh Wi-Fi nodes in bone with woven cream fabric side panels, one set slightly behind the other
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ce-mesh-wi-fi-systems-plate-02-catalog-3x2.png
SUBJECT: a single tall tapered mesh node in warm sand plastic with a smooth blank front face and one subtle vertical seam
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ce-mesh-wi-fi-systems-plate-03-catalog-3x2.png
SUBJECT: a low dome-shaped mesh node in cream on a champagne metal base ring
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ce-mesh-wi-fi-systems-plate-04-catalog-3x2.png
SUBJECT: three small square mesh nodes in warm greige arranged in a loose diagonal line
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ce-mesh-wi-fi-systems-plate-05-catalog-3x2.png
SUBJECT: a slender flat-panel mesh node standing on a small weighted bone base, seen edge-on
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ce-mesh-wi-fi-systems-plate-06-catalog-3x2.png
SUBJECT: a cube-shaped mesh node in soft taupe with rounded corners and a recessed unmarked port bay at the rear
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 8 of 18 — mesh-wi-fi-systems, batch 2 of 2, 5 shots

```text
Generate 5 separate photographs, one per SHOT below.

Return 5 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- The front face is completely plain: no logo, no wordmark, no model number, no status text
- No illuminated display and no lit ring showing characters

SHOT 1 - save as ce-mesh-wi-fi-systems-plate-07-catalog-3x2.png
SUBJECT: two mesh nodes in bone seen from behind, plain rear faces and a short cream cable between them
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ce-mesh-wi-fi-systems-plate-08-catalog-3x2.png
SUBJECT: a wall-plug mesh extender in cream with its prongs folded flat, resting on its side
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ce-mesh-wi-fi-systems-plate-09-catalog-3x2.png
SUBJECT: a tall hexagonal mesh node in warm white with a deep maroon fabric band around its middle
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ce-mesh-wi-fi-systems-plate-10-catalog-3x2.png
SUBJECT: a single disc-shaped mesh node in bone with a concentric ring texture across its top face
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ce-mesh-wi-fi-systems-plate-11-catalog-3x2.png
SUBJECT: a mesh node in matte charcoal with a champagne top cap, in profile
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 9 of 18 — treadmills, batch 1 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- Where a console would sit there is a blank matte panel. No numbers, no readout, no speed or distance figures anywhere
- No decal, stripe or wordmark on the side rails, the belt, the uprights or the deck, and no printed safety label

SHOT 1 - save as rf-treadmills-plate-01-catalog-3x2.png
SUBJECT: a folding treadmill in bone with a slim upright handrail, a low running deck and a deep charcoal belt, in profile
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as rf-treadmills-plate-02-catalog-3x2.png
SUBJECT: an under-desk walking pad in warm greige with no handrail at all and one flat continuous top surface
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as rf-treadmills-plate-03-catalog-3x2.png
SUBJECT: a compact treadmill with the deck folded fully upright against its frame, in cream painted steel
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as rf-treadmills-plate-04-catalog-3x2.png
SUBJECT: a slat-belt treadmill showing individual cream rubber slats and a brushed champagne side frame
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as rf-treadmills-plate-05-catalog-3x2.png
SUBJECT: a low walking pad in bone seen from overhead, the full belt surface and plain side rails visible
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as rf-treadmills-plate-06-catalog-3x2.png
SUBJECT: a curved manual treadmill with a concave slatted running surface between tall bone-painted side frames, in profile
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 10 of 18 — treadmills, batch 2 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- Where a console would sit there is a blank matte panel. No numbers, no readout, no speed or distance figures anywhere
- No decal, stripe or wordmark on the side rails, the belt, the uprights or the deck, and no printed safety label

SHOT 1 - save as rf-treadmills-plate-07-catalog-3x2.png
SUBJECT: a treadmill with a blank matte panel where a console would be, warm sand uprights and a taupe belt
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as rf-treadmills-plate-08-catalog-3x2.png
SUBJECT: a treadmill seen from behind and above, showing the rear roller housing and the plain deck underside
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as rf-treadmills-plate-09-catalog-3x2.png
SUBJECT: an incline treadmill with the deck raised at a steep angle on a cream frame
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as rf-treadmills-plate-10-catalog-3x2.png
SUBJECT: a wide-deck treadmill in soft taupe from just above the surface, the belt receding toward the frame
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as rf-treadmills-plate-11-catalog-3x2.png
SUBJECT: a compact treadmill on two small transport wheels with a folded bone handrail lying flat
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as rf-treadmills-plate-12-catalog-3x2.png
SUBJECT: a folded walking pad in warm white beside a rolled cream mat
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 11 of 18 — mobility-tools, batch 1 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- No density markings, size numbers or printed text on the foam, rubber or fabric
- No end-cap badge, moulded wordmark or embossed logo

SHOT 1 - save as rf-mobility-tools-plate-01-catalog-3x2.png
SUBJECT: a textured cream foam roller with a deep maroon end cap, seen from overhead
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as rf-mobility-tools-plate-02-catalog-3x2.png
SUBJECT: a cordless percussive massage gun in bone with a soft taupe silicone head and a plain blank body
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as rf-mobility-tools-plate-03-catalog-3x2.png
SUBJECT: a champagne-anodised metal roller stick with two rotating cream grips
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as rf-mobility-tools-plate-04-catalog-3x2.png
SUBJECT: a pair of small firm massage balls in deep maroon rubber resting on a travertine ledge
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as rf-mobility-tools-plate-05-catalog-3x2.png
SUBJECT: a long cream cotton stretching strap loosely coiled, sand-coloured woven loops along its length
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as rf-mobility-tools-plate-06-catalog-3x2.png
SUBJECT: a small arch-shaped foot roller in bone plastic with a ridged upper surface
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 12 of 18 — mobility-tools, batch 2 of 2, 5 shots

```text
Generate 5 separate photographs, one per SHOT below.

Return 5 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- No density markings, size numbers or printed text on the foam, rubber or fabric
- No end-cap badge, moulded wordmark or embossed logo

SHOT 1 - save as rf-mobility-tools-plate-07-catalog-3x2.png
SUBJECT: a vibrating massage ball in soft taupe silicone with a shallow dimpled texture
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as rf-mobility-tools-plate-08-catalog-3x2.png
SUBJECT: three graduated silicone cupping domes in warm sand, seen from behind and above
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as rf-mobility-tools-plate-09-catalog-3x2.png
SUBJECT: a curved trigger-point cane in cream moulded plastic with rounded nodes along its inner edge
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as rf-mobility-tools-plate-10-catalog-3x2.png
SUBJECT: a travel foam roller in two nesting halves, bone with a maroon core, one half set beside the other
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as rf-mobility-tools-plate-11-catalog-3x2.png
SUBJECT: a flat brushed champagne muscle-scraping tool seen edge-on against the surface
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 13 of 18 — electric-standing-desks, batch 1 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- The height keypad is blank: no digits, no arrows, no memory-preset numbers
- No brand plate on the frame, legs or desktop edge, and nothing resting on the desktop

SHOT 1 - save as ho-electric-standing-desks-plate-01-catalog-3x2.png
SUBJECT: a two-leg electric standing desk with a warm oak veneer top raised to standing height on a cream painted steel frame
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ho-electric-standing-desks-plate-02-catalog-3x2.png
SUBJECT: a narrow electric standing desk in bone laminate at seated height with a slim rectangular cable tray under its rear edge
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ho-electric-standing-desks-plate-03-catalog-3x2.png
SUBJECT: an electric standing desk from just above the surface, a taupe top cantilevered over a single champagne column
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ho-electric-standing-desks-plate-04-catalog-3x2.png
SUBJECT: an electric standing desk in profile at full height, showing a two-stage telescopic leg in warm greige
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ho-electric-standing-desks-plate-05-catalog-3x2.png
SUBJECT: an empty cream desktop seen from overhead with two grommet holes and a folded braided cable behind it
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ho-electric-standing-desks-plate-06-catalog-3x2.png
SUBJECT: an electric standing desk from behind, showing a vertical cable spine and a blank keypad under the front edge
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 14 of 18 — electric-standing-desks, batch 2 of 2, 5 shots

```text
Generate 5 separate photographs, one per SHOT below.

Return 5 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- The height keypad is blank: no digits, no arrows, no memory-preset numbers
- No brand plate on the frame, legs or desktop edge, and nothing resting on the desktop

SHOT 1 - save as ho-electric-standing-desks-plate-07-catalog-3x2.png
SUBJECT: a corner electric standing desk with an L-shaped warm oak top on three cream legs
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ho-electric-standing-desks-plate-08-catalog-3x2.png
SUBJECT: a compact electric standing desk in soft taupe with a rounded front edge and a bone felt-lined under-desk tray
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ho-electric-standing-desks-plate-09-catalog-3x2.png
SUBJECT: an electric standing desk with a bevelled travertine-toned top and slim charcoal legs, low camera
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ho-electric-standing-desks-plate-10-catalog-3x2.png
SUBJECT: an electric standing desk at seated height in profile, warm sand top on a champagne single column
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ho-electric-standing-desks-plate-11-catalog-3x2.png
SUBJECT: an empty bone desktop seen from overhead with a snap-open cream cable sleeve along its rear edge
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 15 of 18 — sound-masking-devices, batch 1 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- No logo on the fabric, the grille or the base, and no printed control labels around any dial
- No illuminated display and no visible speaker brand mark

SHOT 1 - save as ho-sound-masking-devices-plate-01-catalog-3x2.png
SUBJECT: a small cylindrical sound-masking device in bone with a woven cream fabric wrap and a smooth champagne top disc
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ho-sound-masking-devices-plate-02-catalog-3x2.png
SUBJECT: a low dome-shaped white-noise device in warm sand plastic with a fine perforated grille across its upper half
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ho-sound-masking-devices-plate-03-catalog-3x2.png
SUBJECT: a fabric-wrapped cube sound-masking device in soft taupe with rounded corners
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ho-sound-masking-devices-plate-04-catalog-3x2.png
SUBJECT: a flat disc sound-masking device in cream seen from overhead, a concentric perforated top face
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ho-sound-masking-devices-plate-05-catalog-3x2.png
SUBJECT: a tall slim sound-masking column in warm greige seen edge-on, a maroon fabric band at its base
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ho-sound-masking-devices-plate-06-catalog-3x2.png
SUBJECT: a pebble-shaped tabletop sound-masking device in bone ceramic with one unmarked recessed dial
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 16 of 18 — sound-masking-devices, batch 2 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- No logo on the fabric, the grille or the base, and no printed control labels around any dial
- No illuminated display and no visible speaker brand mark

SHOT 1 - save as ho-sound-masking-devices-plate-07-catalog-3x2.png
SUBJECT: a sound-masking device from behind and above, showing a plain rear shell and one small unmarked port
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ho-sound-masking-devices-plate-08-catalog-3x2.png
SUBJECT: a wall-mount sound-masking plate in cream with a subtly textured fabric front, resting flat
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ho-sound-masking-devices-plate-09-catalog-3x2.png
SUBJECT: a compact travel sound-masking device in champagne aluminium with a folded cream fabric loop
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ho-sound-masking-devices-plate-10-catalog-3x2.png
SUBJECT: two small sound-masking devices in bone and taupe set apart on a travertine surface, from overhead
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ho-sound-masking-devices-plate-11-catalog-3x2.png
SUBJECT: a rounded-triangle sound-masking device in matte charcoal with a cream perforated face, in profile
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ho-sound-masking-devices-plate-12-catalog-3x2.png
SUBJECT: a sound-masking device in a moulded bone shell with a deep maroon silicone base ring and no visible controls
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 17 of 18 — lumbar-supports, batch 1 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- No brand tag, care label or size label sewn into the fabric, and no printed text on any strap or buckle
- The support stands alone: no chair, no seat back and no person in the frame

SHOT 1 - save as ho-lumbar-supports-plate-01-catalog-3x2.png
SUBJECT: a contoured memory-foam lumbar cushion in cream knit fabric, a cream elastic strap coiled behind it
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ho-lumbar-supports-plate-02-catalog-3x2.png
SUBJECT: a curved mesh lumbar panel on a champagne wire frame, angled across the surface
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ho-lumbar-supports-plate-03-catalog-3x2.png
SUBJECT: a cylindrical lumbar roll in soft taupe velour, low camera
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ho-lumbar-supports-plate-04-catalog-3x2.png
SUBJECT: a wedge-shaped lumbar cushion in bone woven fabric, seen from overhead
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ho-lumbar-supports-plate-05-catalog-3x2.png
SUBJECT: a slim inflatable lumbar support in warm sand coated fabric seen edge-on, flat at one end
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ho-lumbar-supports-plate-06-catalog-3x2.png
SUBJECT: a lumbar cushion from behind, showing plain grey-taupe backing fabric and two unmarked strap loops
CAMERA: shown three-quarter from behind and to the left, so the back of the product faces the camera, filling roughly 60% of the frame. The product is the single hero, centred and in sharp focus.
```

### Message 18 of 18 — lumbar-supports, batch 2 of 2, 6 shots

```text
Generate 6 separate photographs, one per SHOT below.

Return 6 individual landscape images at 1536x1024. Do not combine them into a
contact sheet, grid or collage: a sliced 2x2 sheet leaves each plate at 512px,
under what the card needs at device pixel ratio 2. Every shot shares the set,
palette, style and constraints below, and differs only in its SUBJECT and CAMERA
lines. They must read as one catalog photographed in one session.

Premium e-commerce product photograph for a high-end catalog.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS, every shot:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- The whole product must be inside the frame with clear margin on all sides
- No brand tag, care label or size label sewn into the fabric, and no printed text on any strap or buckle
- The support stands alone: no chair, no seat back and no person in the frame

SHOT 1 - save as ho-lumbar-supports-plate-07-catalog-3x2.png
SUBJECT: a two-piece lumbar support in cream with a firm foam core and a deep maroon knit cover half-drawn back
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 2 - save as ho-lumbar-supports-plate-08-catalog-3x2.png
SUBJECT: a broad flat lumbar pad in warm greige quilted fabric with a soft channel down its centre
CAMERA: shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 3 - save as ho-lumbar-supports-plate-09-catalog-3x2.png
SUBJECT: an adjustable lumbar support on a small height-slider track in bone plastic, low camera
CAMERA: shown from a low camera just above the surface, slightly foreshortened toward the viewer, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 4 - save as ho-lumbar-supports-plate-10-catalog-3x2.png
SUBJECT: a horseshoe-shaped lumbar cushion in cream boucle beside a folded taupe strap, from overhead
CAMERA: shown from almost directly overhead as a flat lay, filling roughly 75% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 5 - save as ho-lumbar-supports-plate-11-catalog-3x2.png
SUBJECT: a moulded ventilated lumbar shell in bone plastic with an open lattice back, in profile
CAMERA: shown in straight profile from the right, parallel to the frame, filling roughly 70% of the frame. The product is the single hero, centred and in sharp focus.

SHOT 6 - save as ho-lumbar-supports-plate-12-catalog-3x2.png
SUBJECT: a lumbar cushion in deep maroon corduroy with piped cream edges and a plain front face
CAMERA: shown three-quarter front at eye level, filling roughly 65% of the frame. The product is the single hero, centred and in sharp focus.
```

## Outstanding still-life

Four generations of this one came back with cool veined marble or a
chopping board, breaking the palette rule. Until it lands,
`sound-masking-devices` and `lumbar-supports` fall back to a photograph of
the Forma chair. The other two domain still-lifes are installed.


### ho-domain-neutral

```text
Premium editorial still-life photograph of an empty surface, for a high-end
catalog. No merchandise appears in this shot.

SUBJECT: a folded cream wool felt mat resting on a warm oak surface, the oak grain filling the lower half of the frame and warm cream plaster rising behind it

The surface and its props are the whole subject, in sharp focus,
shown from an elevated forty-degree view looking down, angled diagonally across the frame, filling roughly 70% of the frame.

SET: a warm minimalist interior surface - travertine stone or cream plaster -
with soft directional late-afternoon daylight raking from the left and gentle
leafy shadow play on the back wall. Shallow depth of field so the background
falls away softly. One or two restrained props at most, well behind the subject.

PALETTE: the set is warm sand, bone, cream, and soft taupe, with a single deep
maroon accent. No cool tones in the light, no white seamless studio backdrop.
Where the subject line names a dark finish, render it warm and neutral, never
blue-grey.

STYLE: editorial commercial product photography, 50mm lens look, natural soft
shadows, subtle material detail in fabric and metal, calm and expensive.

CRITICAL CONSTRAINTS:
- No text, no lettering, no numbers, no logos, no brand marks, no watermarks
- No people, no hands, no faces
- No UI, no screens showing interfaces, no packaging with writing
- Photorealistic, not an illustration or 3D render
- There is no product in the frame. Do not add a device, a shoe, a chair or any merchandise
- The composition must still be a photograph of a real surface, not a flat colour field

Generate at 1536x1024 (landscape).
Save as: ho-domain-neutral-catalog-3x2.png
```
