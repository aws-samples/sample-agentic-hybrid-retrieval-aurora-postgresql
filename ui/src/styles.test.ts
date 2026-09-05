// @vitest-environment node
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

/**
 * The stylesheets speak one color vocabulary, and this holds them to it.
 *
 * Before the 2026-09-05 pass, the two sheets drew the same hairline in
 * thirteen hex values, the same paper in five, and carried a second `:root`
 * of `--mosaic-*` tokens that shadowed the palette with values a few units
 * off. Two ink tokens shared one value, and one referenced token was defined
 * nowhere. None of that is visible in a diff, so the checks live here, as
 * functions over the sheet text with a fixture that proves each one can fail.
 */
const SHEETS = ["styles.css", "surfaces.css"] as const;

/** Custom properties components set with inline style; the sheets only read them. */
const SET_FROM_COMPONENTS = new Set(["--labs-rail-height", "--low", "--high", "--sweep"]);

/**
 * Raw hex literals still standing outside the palette block, after the pass
 * mapped 437 onto tokens. A ratchet: lower it when a pass retires more, never
 * raise it. A new literal fails with the line it landed on, and the fix is a
 * token from `:root`, or a new role there when none fits.
 */
const HEX_LITERAL_CEILING = 252;

const HEX = /#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/g;
const TOKEN_DEFINITION = /^\s*(--[a-z0-9-]+):\s*(.+?);/;

type Sheet = { name: string; text: string };

async function readSheets(): Promise<Sheet[]> {
  return Promise.all(
    SHEETS.map(async (name) => ({
      name,
      text: await readFile(new URL(name, import.meta.url), "utf8"),
    })),
  );
}

/** The palette block: the first `:root { ... }` of the first sheet. */
function paletteBlock(sheets: Sheet[]): string {
  const match = /^:root \{[^]*?^\}/m.exec(sheets[0].text);
  if (!match) throw new Error(`${sheets[0].name} has no :root block`);
  return match[0];
}

function definitions(text: string): Array<{ name: string; value: string; line: number }> {
  return text.split("\n").flatMap((line, index) => {
    const match = TOKEN_DEFINITION.exec(line);
    return match ? [{ name: match[1], value: match[2].trim(), line: index + 1 }] : [];
  });
}

export function undefinedReferences(sheets: Sheet[], allowed = SET_FROM_COMPONENTS): string[] {
  const all = sheets.map((sheet) => sheet.text).join("\n");
  const defined = new Set(definitions(all).map((definition) => definition.name));
  const referenced = new Set([...all.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]));
  return [...referenced].filter((name) => !defined.has(name) && !allowed.has(name)).sort();
}

export function duplicatePaletteValues(sheets: Sheet[]): Record<string, string[]> {
  const byValue = new Map<string, string[]>();
  for (const { name, value } of definitions(paletteBlock(sheets))) {
    if (!/^#[0-9a-fA-F]{3,8}$/.test(value)) continue;
    const names = byValue.get(value.toLowerCase()) ?? [];
    names.push(name);
    byValue.set(value.toLowerCase(), names);
  }
  return Object.fromEntries([...byValue].filter(([, names]) => names.length > 1));
}

/** Hex-valued definitions outside the palette block that are not overrides of a palette token. */
export function strayPalettes(sheets: Sheet[]): string[] {
  const palette = new Set(definitions(paletteBlock(sheets)).map((definition) => definition.name));
  const block = paletteBlock(sheets);
  return sheets.flatMap(({ name, text }) =>
    definitions(name === sheets[0].name ? text.replace(block, "") : text)
      .filter((definition) => /^#/.test(definition.value) && !palette.has(definition.name))
      .map((definition) => `${name}:${definition.line} ${definition.name}: ${definition.value}`),
  );
}

export function hexLiterals(sheets: Sheet[]): string[] {
  return sheets.flatMap(({ name, text }) =>
    text.split("\n").flatMap((line, index) => {
      // Token definitions are where hex belongs; masks and data URLs are not colors.
      if (TOKEN_DEFINITION.test(line) && /:\s*#/.test(line)) return [];
      if (line.includes("mask") || line.includes("url(")) return [];
      return [...line.matchAll(HEX)].map((m) => `${name}:${index + 1} ${m[0]} in ${line.trim()}`);
    }),
  );
}

describe("stylesheet vocabulary", () => {
  it("references only custom properties that something defines", async () => {
    expect(undefinedReferences(await readSheets())).toEqual([]);
  });

  it("gives every palette token a distinct value, aliasing through var() instead", async () => {
    expect(duplicatePaletteValues(await readSheets())).toEqual({});
  });

  it("declares the palette once; other sheets may only override a palette token", async () => {
    expect(strayPalettes(await readSheets())).toEqual([]);
  });

  it("holds the ratchet on raw hex literals outside the palette block", async () => {
    const literals = hexLiterals(await readSheets());
    expect(
      literals.length,
      `raw hex literals rose past ${HEX_LITERAL_CEILING}; the newest look like:\n` +
        literals.slice(-5).join("\n"),
    ).toBeLessThanOrEqual(HEX_LITERAL_CEILING);
  });

  it("can fail: each check reports the defect it exists for", () => {
    // The falsifier. A guard that cannot go red is a comment, not a gate.
    const sheets: Sheet[] = [
      {
        name: "styles.css",
        text: [
          ":root {",
          "  --ink: #171514;",
          "  --ink-soft: #5f5955;",
          "  --ink-faint: #5f5955;",
          "  --focus: var(--ink);",
          "}",
          ".a { color: var(--ink-muted); border: 1px solid #ded6ca; }",
          ".b { mask-image: linear-gradient(#000, transparent); }",
        ].join("\n"),
      },
      {
        name: "surfaces.css",
        text: [":root {", "  --mosaic-line: #ddd8cf;", "  --ink: #000000;", "}"].join("\n"),
      },
    ];
    expect(undefinedReferences(sheets)).toEqual(["--ink-muted"]);
    expect(duplicatePaletteValues(sheets)).toEqual({ "#5f5955": ["--ink-soft", "--ink-faint"] });
    expect(strayPalettes(sheets)).toEqual(["surfaces.css:2 --mosaic-line: #ddd8cf"]);
    // The mask line is exempt; the hairline literal is the one caught.
    expect(hexLiterals(sheets)).toEqual([
      "styles.css:7 #ded6ca in .a { color: var(--ink-muted); border: 1px solid #ded6ca; }",
    ]);
  });
});
