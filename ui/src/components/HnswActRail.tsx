import { useEffect, useState } from "react";
import type { ReactNode } from "react";

/**
 * The three acts the HNSW lens moves through, and the rail that names them.
 *
 * This surface ran eight sibling sections, all open, with no anchors and no
 * rail: nearly seven screens where the only way to reach the filter cliff was
 * to scroll past everything before it, and nothing on screen said the eight had
 * an order. They do -- what the index costs, how it is tuned, and where it goes
 * at scale -- and the required Playground beside it has said its own order out
 * loud in four numbered stages since it shipped.
 *
 * Three acts rather than eight rail entries. Eight is a table of contents, which
 * is a second thing to read; three is a spine, which is what the reader is
 * missing. Each act always has at least one section that renders unconditionally
 * -- the live index cost, the Pareto curve, and the production verdict -- so the
 * rail never offers a destination that is not on the page.
 */

export const HNSW_ACTS = [
  {
    slug: "cost",
    label: "Cost",
    title: "Index & storage",
    summary: "The index on the connected cluster, and the ways those vectors could be stored instead.",
  },
  {
    slug: "tuning",
    label: "Tuning",
    title: "Recall & filters",
    summary: "Compare search effort with exact neighbors, then explore selective filters and the memory budget.",
  },
  {
    slug: "scale",
    label: "Scale",
    title: "Scale experiments",
    summary: "Separate projections from controlled hardware comparisons, and trace each operating decision to its evidence.",
  },
] as const;

export type HnswActSlug = (typeof HNSW_ACTS)[number]["slug"];

/**
 * The act a `#hnsw-act-<slug>` hash names, or null for any other hash.
 *
 * Exported so the rule is testable on its own: the rail must not mark an act for
 * a hash that belongs to something else on the page.
 */
export function actFromHash(hash: string): string | null {
  const match = /^#hnsw-act-([a-z]+)$/.exec(hash);
  return match ? match[1] : null;
}

/**
 * Hash-driven, exactly as `LabRail` is, and for the same reason recorded there:
 * a scroll-spy answers a question nobody asked, and the hash is already the
 * record of the jump the reader just made. `hashchange` covers repeat clicks,
 * which do not re-render on their own.
 */
export function HnswActRail() {
  const [viewing, setViewing] = useState<string | null>(
    () => actFromHash(typeof window === "undefined" ? "" : window.location.hash),
  );

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const sync = () => setViewing(actFromHash(window.location.hash));
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  return (
    <nav aria-label="Vector index acts" className="hnsw-rail">
      <ol className="hnsw-rail-acts">
        {HNSW_ACTS.map((act, index) => (
          <li key={act.slug}>
            <a
              data-viewing={act.slug === viewing ? "true" : undefined}
              href={`#hnsw-act-${act.slug}`}
            >
              <b aria-hidden="true">{String(index + 1).padStart(2, "0")}</b>
              {act.label}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/**
 * One act, wrapping the sections that belong to it.
 *
 * The heading is a real `h2` and the sections inside keep the `h2`s they already
 * had, which would nest two levels of the same rank. Their headings are the
 * measured assertions a reader quotes ("The neighbours sit in a band 0.03
 * wide."), so they keep their weight; the act heading is set quieter and marked
 * as the group label, and the sections are addressed by the act's id rather than
 * being re-ranked.
 */
export function HnswAct({
  slug,
  children,
}: {
  slug: HnswActSlug;
  children: ReactNode;
}) {
  const act = HNSW_ACTS.find((entry) => entry.slug === slug);
  if (!act) throw new Error(`unknown HNSW act: ${slug}`);
  return (
    <section
      aria-labelledby={`hnsw-act-${slug}-title`}
      className="hnsw-act"
      id={`hnsw-act-${slug}`}
    >
      <header className="hnsw-act-head">
        <h2 id={`hnsw-act-${slug}-title`}>{act.title}</h2>
        <p className="hnsw-act-summary">{act.summary}</p>
      </header>
      {children}
    </section>
  );
}
