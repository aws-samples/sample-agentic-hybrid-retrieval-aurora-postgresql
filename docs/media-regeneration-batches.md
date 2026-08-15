# Replacement cohort photography

Runtime files that are installed but show the **wrong product**. Every one came
from the `chatgpt-2026-08-08` batch, whose manifest recorded only
`Pixel-verified source` — the bytes were checked, the subject never was. The
later `chatgpt-2026-08-09-*` batches recorded a per-image content check and
audited clean, so the defect is confined to that one batch.

Both batches are **done**. `REGEN-B01` imported 2026-08-09
(`import_batch_2026-08-09-regen-b01.csv`); `REGEN-B02` imported 2026-08-10
(`import_batch_2026-08-10-regen-b02.csv`), covering four further mismatches
found when all 38 images of the Aug-8 batch were re-audited at 2.2x zoom rather
than trusting the first pass.

**All 13 wrong-subject images from the `chatgpt-2026-08-08` batch are now
replaced.** The cohort stands at 120 of 120 catalog images and 6 of 6 detail
images, every one content-verified against its intended product.

B02 generated six candidates for four slots — two duplicate pairs. Both
rejections are recorded in the manifest with `status: rejected` and no
`output_filename`, because the reason a candidate lost is the useful part:

- the air-quality variant rendered a **legible on-screen readout**
  (`AQI 23 Good / PM2.5 12 / CO2 680`), violating the no-text direction;
- the chest-strap variant's sensor pod carried **embossed chevron marks** that
  read as a brand device mark.

Rejected candidates keep their original ChatGPT filenames, so the importer
refuses them by name. That is the intended workflow: never rename a candidate
you have not chosen.

Regenerating replaces the file in place. Keep the **exact** output filename: the
importer refuses any name that is not a cohort asset key, and the runtime reads
these paths from `data/media/asset_labels_120.json`.

All nine are `catalog-3x2` (**1536x1024**). None is a retrieval anchor, so none
is on screen during a scripted query — but all nine sit on a shop page a
participant browses.

## What each one currently shows

| Output filename | Should show | Actually shows |
|---|---|---|
| `ce-device-stands-catalog-3x2.webp` | Device stand | fabric cylinder Bluetooth speaker |
| `ce-smart-lighting-catalog-3x2.webp` | Smart lighting | fabric cylinder Bluetooth speaker |
| `ho-floor-lamps-catalog-3x2.webp` | Floor lamp | fabric cylinder Bluetooth speaker |
| `ce-gaming-headsets-catalog-3x2.webp` | Over-ear gaming headset | earbuds in a pebble case |
| `ce-protective-sleeves-catalog-3x2.webp` | Laptop sleeve | duffel / weekender bag |
| `ce-charging-docks-catalog-3x2.webp` | Charging dock | laptop sleeve + charging puck |
| `ho-desktop-organizers-catalog-3x2.webp` | Desktop organizer | laptop sleeve + charging pad |
| `ho-docking-stations-catalog-3x2.webp` | Docking station | laptop sleeve + charging pad |
| `ho-acoustic-headphones-catalog-3x2.webp` | Acoustic headphones | office chair |

Three separate assets render the same fabric cylinder speaker, and three more
render the same laptop-sleeve-plus-charging-pad scene. The prompt below states
what each subject is **not**, because that collapse is what the original prompt
failed to prevent.

---

## Batch `REGEN-B01` — Replacements · 9 images · DONE

```
Generate 9 product photographs as one consistent catalog set.

SET DIRECTION (identical for every image):
Warm travertine and cream plaster set, soft directional daylight with leafy shadow play, muted sand and bone palette with a single deep maroon accent, product centred and sharp, shallow depth of field, no text or logos.

FORMAT: 3:2 landscape, 1536x1024, one product per image, no text, no logos,
no watermarks, no human hands.

CRITICAL: these nine replace images that showed the wrong product. Each subject
below states what it must NOT be. Three must not be a fabric cylinder speaker;
three must not be a laptop sleeve with a charging pad. Make the nine visually
distinct from one another.

SUBJECTS:
 1. EchoTech DS-M977X Edge Device Stand
    category: Accessories > Device Stands
    SHOW: an angled desktop cradle holding a phone or tablet upright, empty or
    with a blank slab device in it, cable channel visible at the back
    NOT: a speaker, not a cylinder, not a laptop stand

 2. AuriCore PS-F772S Pro Protective Sleeve
    category: Accessories > Protective Sleeves
    SHOW: a flat padded laptop sleeve, zip closed, lying alone on stone
    NOT: a duffel bag, not a weekender, no handles, no shoulder strap

 3. PrismForge GH-N004X Edge Gaming Headset
    category: Audio > Gaming Headsets
    SHOW: a full over-ear headset with a boom microphone arm on the left cup
    NOT: earbuds, not a charging case, not headphones without a mic

 4. AxionTech CD-R797P Prime Charging Dock
    category: Mobile & Power > Charging Docks
    SHOW: an upright multi-device charging dock — a weighted base with one or
    two angled charging shelves, one short captive cable
    NOT: a flat wireless pad on its own, not a laptop sleeve, no sleeve in frame

 5. AuriForge SL-K531 Pro Smart Lighting
    category: Smart Home > Smart Lighting
    SHOW: a smart light — a frosted glowing panel or bulb-and-diffuser emitting
    warm light, clearly a light source
    NOT: a speaker, not a fabric cylinder, not a lamp with a shade

 6. ContourLab FL-N505X Flex Floor Lamp
    category: Lighting > Floor Lamps
    SHOW: a tall standing floor lamp, full height in frame, slim stem rising
    from a floor base to a shade well above the surface
    NOT: a speaker, not a fabric cylinder, not a table lamp, not desk-height

 7. DeskSpace DO-X349P Pro Desktop Organizer
    category: Organization > Desktop Organizers
    SHOW: a compartmented desk caddy or tray with divided slots holding pens
    and small items
    NOT: a laptop sleeve, not a charging pad, no sleeve in frame

 8. HavenCraft DS-N476P Ultra Docking Station
    category: Power & Connectivity > Docking Stations
    SHOW: a small metal hub block with a visible row of ports along one edge —
    USB, HDMI, card slot — and one trailing cable
    NOT: a laptop sleeve, not a charging pad, no sleeve in frame

 9. DeskStudio AH-A267P Core Acoustic Headphone
    category: Video & Audio > Acoustic Headphones
    SHOW: over-ear headphones resting on a stone plinth or a slim stand,
    earcups clearly visible
    NOT: an office chair, not a desk, no furniture as the subject

Save each file with the EXACT name below, in order:
 1. ce-device-stands-catalog-3x2.webp
 2. ce-protective-sleeves-catalog-3x2.webp
 3. ce-gaming-headsets-catalog-3x2.webp
 4. ce-charging-docks-catalog-3x2.webp
 5. ce-smart-lighting-catalog-3x2.webp
 6. ho-floor-lamps-catalog-3x2.webp
 7. ho-desktop-organizers-catalog-3x2.webp
 8. ho-docking-stations-catalog-3x2.webp
 9. ho-acoustic-headphones-catalog-3x2.webp
```

---

## Batch `REGEN-B02` — Second-pass replacements · 4 images · DONE

Found by re-auditing all 38 Aug-8 images at 2.2x zoom. `rf-gps-running-watches`
is a **retrieval anchor** — it appears on screen during a scripted query — so it
is listed here as context even though it is itself correct: its render was
reused for the heart-rate monitor, and the replacement must not look like it.

| Output filename | Should show | Actually shows |
|---|---|---|
| `ce-sleep-trackers-catalog-3x2.webp` | Sleep tracker | earbuds with an oval charging case |
| `ho-air-quality-monitors-catalog-3x2.webp` | Air quality monitor | a computer display on a stand |
| `rf-compression-sleeves-catalog-3x2.webp` | Compression sleeve | tan trail running shoes |
| `rf-heart-rate-monitors-catalog-3x2.webp` | Heart rate monitor | a square smartwatch, near-duplicate of the GPS watch anchor |

```
Generate 4 product photographs as one consistent catalog set.

SET DIRECTION (identical for every image):
Warm travertine and cream plaster set, soft directional daylight with leafy shadow play, muted sand and bone palette with a single deep maroon accent, product centred and sharp, shallow depth of field, no text or logos.

FORMAT: 3:2 landscape, 1536x1024, one product per image, no text, no logos,
no watermarks, no human hands.

CRITICAL: these four replace images that showed the wrong product. Each subject
states what it must NOT be. None of the four may be a wrist smartwatch, and none
may be a shoe.

SUBJECTS:
 1. NexaCore ST-V696S Air Sleep Tracker
    category: Wearables > Sleep Trackers
    SHOW: a bedside sleep-tracking unit — a small soft-edged dome or puck with a
    fabric top and a single status light, resting on a nightstand-style slab
    NOT: earbuds, not a charging case, not a wrist smartwatch

 2. NestHome AQM-M661S Plus Air Quality Monitor
    category: Air & Environment > Air Quality Monitors
    SHOW: a small freestanding air sensor — a compact upright block with a
    perforated intake grille on one face and a tiny dark readout panel
    NOT: a computer display, not a desktop monitor, not a screen on a stand

 3. PeakSport CS-E110X Pro Compression Sleeve
    category: Recovery > Compression Sleeves
    SHOW: a fabric calf compression sleeve, a single tube of ribbed knit fabric
    lying flat or lightly rolled on stone
    NOT: a shoe, not footwear of any kind, not a full legging

 4. FlexMotion HRM-M126X Studio Heart Rate Monitor
    category: Wearables > Heart Rate Monitors
    SHOW: a chest-strap heart rate monitor — an elastic band laid in a loose
    curve with a small oval sensor pod clipped at its centre
    NOT: a wrist smartwatch, not a watch on a strap, not a screen

Save each file with the EXACT name below, in order:
 1. ce-sleep-trackers-catalog-3x2.webp
 2. ho-air-quality-monitors-catalog-3x2.webp
 3. rf-compression-sleeves-catalog-3x2.webp
 4. rf-heart-rate-monitors-catalog-3x2.webp
```

---

## Importing the replacements

Save the nine downloads as `.png` under the names above (the importer converts
to WebP), then:

```sh
SOURCE=~/Downloads/batch make media-import   # overwrites the nine runtime files
make media-shot-list                         # refreshes labels + sha256
```

Record provenance in `data/media/import_batch_<date>-regen-b01.csv` with a
per-image `note` stating what was verified in the picture, not that the bytes
arrived. `status` is `replaced` for these, not `installed`.

---

## Cohort status: CLOSED

120 of 120 catalog images and 6 of 6 detail images, every one content-verified
against its intended product. Machine-checked: 126 files, correct dimensions,
all WebP, no byte-identical duplicates. No real-world brand marks, legible text,
or watermarks found at 2.2–2.4x zoom. No further cohort photography is planned.

## Backlog (parked, unfunded)

- **Expand the per-category fallback pool, assign by subcategory hash.** The
  499,880 non-cohort products currently share a handful of `category_fallback`
  images (`scripts/materialize_image_urls.py`), so a browse surface past the
  cohort's 10 shop pages shows visible repetition. Revisit only if rehearsal
  puts a browse surface on stage. No cohort budget is spent on this now.
