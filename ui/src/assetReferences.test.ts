import { execFileSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcDir = fileURLToPath(new URL(".", import.meta.url));
const publicDir = fileURLToPath(new URL("../public", import.meta.url));
const gitDir = fileURLToPath(new URL("../../.git", import.meta.url));

function sourceFiles(): string[] {
  return readdirSync(srcDir, { recursive: true, encoding: "utf8" })
    .filter((entry) => /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry));
}

/**
 * Every `/assets/` path a source file names, not only `/assets/images/`.
 *
 * Icons were outside this: `assets/icons/github-mark.svg` is referenced by a bare
 * string in the Playground's lens strip and by the footer, and a rename or a
 * never-committed file there fails exactly the way a photograph does. The footer
 * is about to carry payment marks from the same directory, which is what makes
 * the gap worth closing before the files arrive rather than after.
 *
 * The extension is required because a path is only checkable if it names a file.
 * `media.ts` holds `/assets/images` as the prefix it builds filenames from, and a
 * directory is not a git-tracked path, so matching it reported the one reference
 * that cannot be missing as missing.
 */
async function hardcodedImagePaths(): Promise<Map<string, string[]>> {
  const byFile = new Map<string, string[]>();
  for (const file of sourceFiles()) {
    const source = await readFile(srcDir + file, "utf8");
    const paths = [...source.matchAll(/"(\/assets\/[^"]+\.[a-z0-9]+)"/gi)]
      .map((match) => match[1]);
    if (paths.length) byFile.set(file, paths);
  }
  return byFile;
}

function gitTrackedImages(): Set<string> | null {
  // A source export has no .git, and there the on-disk check is all we can make.
  if (!existsSync(gitDir)) return null;
  const listed = execFileSync("git", ["ls-files", "-z", "--", "assets"], {
    cwd: publicDir,
    encoding: "utf8",
  });
  return new Set(listed.split("\0").filter(Boolean).map((name) => `/${name}`));
}

describe("hardcoded asset references", () => {
  it("point at images that exist in public/", async () => {
    // Vite answers a missing asset with the SPA index.html and a 200, so a
    // renamed or never-committed photograph renders as an empty box instead of
    // failing the build. Every surface that names an asset inline is covered,
    // not just the one where that first bit us.
    const byFile = await hardcodedImagePaths();
    expect(byFile.size).toBeGreaterThan(0);

    const missing = [...byFile].flatMap(([file, paths]) => paths
      .filter((path) => !existsSync(publicDir + path))
      .map((path) => `${file}: ${path}`));
    expect(missing).toEqual([]);
  });

  it("point at images the repository actually carries", async () => {
    // The check above passes for a photograph that was generated locally and
    // never added, which is the shape this breaks in: the surface looks right
    // here and ships with an empty hero for everyone who clones.
    const tracked = gitTrackedImages();
    if (!tracked) return;

    const byFile = await hardcodedImagePaths();
    const untracked = [...byFile].flatMap(([file, paths]) => paths
      .filter((path) => !tracked.has(path))
      .map((path) => `${file}: ${path}`));
    expect(untracked).toEqual([]);
  });
});
