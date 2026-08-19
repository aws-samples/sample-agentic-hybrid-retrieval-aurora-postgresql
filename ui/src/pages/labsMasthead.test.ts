import { readdirSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const pagesDir = fileURLToPath(new URL(".", import.meta.url));

/**
 * A surface is a Labs surface when it carries the Labs tab strip.
 *
 * Deriving the set that way rather than listing it means a new tab added to
 * MosaicLabsTabs comes under these rules automatically, instead of needing
 * somebody to remember to extend a list here.
 */
async function labsSurfaces(): Promise<Array<[string, string]>> {
  const surfaces: Array<[string, string]> = [];
  const files = readdirSync(pagesDir).filter(
    (entry) => /\.tsx$/.test(entry) && !/\.test\.tsx$/.test(entry),
  );
  for (const file of files) {
    const source = await readFile(pagesDir + file, "utf8");
    if (source.includes("<MosaicLabsTabs")) surfaces.push([file, source]);
  }
  return surfaces;
}

describe("Mosaic Labs surfaces", () => {
  it("all render the shared masthead", async () => {
    // The Labs type scale is enforced by scripts/labs_type_scale.py, which finds
    // rules by selector prefix (`labs-`, `lab-`, `hnsw-`, `mosaic-studio-`,
    // `mosaic-labs-`). A page that draws its own header with a generic class is
    // invisible to it: RetrievalLabPage used `.page-header`, whose h1 is 52px at
    // weight 500 against the masthead's 51.84px at 450, and no gate saw it.
    //
    // Going through MosaicLabsMasthead makes the scale follow from the component,
    // so a Labs surface cannot pick up a second type system by accident.
    const surfaces = await labsSurfaces();
    expect(surfaces.length).toBeGreaterThanOrEqual(3);

    const missing = surfaces
      .filter(([, source]) => !source.includes("<MosaicLabsMasthead"))
      .map(([file]) => file);
    expect(missing).toEqual([]);
  });

  it("none draws a bespoke page header", async () => {
    // `.page-header` belongs to the storefront surfaces, which have their own
    // scale. Inside Labs it is the exact drift the masthead exists to prevent.
    const surfaces = await labsSurfaces();
    const bespoke = surfaces
      .filter(([, source]) => /className="[^"]*\bpage-header\b/.test(source))
      .map(([file]) => file);
    expect(bespoke).toEqual([]);
  });

  it("none asks the masthead for a decorative variant", async () => {
    // Studio passed `showFlow` for a 194px particle canvas that measured nothing.
    // It pushed Studio's own masthead rule 234px below the last line of copy, so
    // that rule and the next section's read as two hairlines around an empty band
    // while the other three surfaces went copy, rule, gap, section.
    //
    // One masthead with no variants is what keeps that from being reintroduced for
    // one surface at a time. Asserted over the derived surface set, so a fourth
    // Labs view is covered without anybody remembering to add it here.
    const surfaces = await labsSurfaces();
    const decorated = surfaces
      .filter(([, source]) => /showFlow|LabsIntroFlow|labs-intro--/.test(source))
      .map(([file]) => file);
    expect(decorated).toEqual([]);
  });
});
