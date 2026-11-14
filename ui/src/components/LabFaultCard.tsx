import { forwardRef, useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import type { MosaicLabMission } from "../labMissions";
import type { ProductDetail } from "../types";

/**
 * pg_trgm's three-letter pieces of a text: each word lower-cased, with two spaces
 * before it and one after, as `show_trgm` lists them.
 */
export function trigrams(text: string): Set<string> {
  const pieces = new Set<string>();
  for (const word of text.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)) {
    const padded = `  ${word} `;
    for (let index = 0; index + 3 <= padded.length; index += 1) pieces.add(padded.slice(index, index + 3));
  }
  return pieces;
}

/** What separates the two IDs, and what fuzzy matching still finds in common. */
export function idDifference(typed: string, listing: string): string {
  const differ = [...typed].flatMap((character, index) => (character === listing[index] ? [] : [index]));
  const [first, second] = differ;
  const swapped = differ.length === 2 && second === first + 1
    && typed[first] === listing[second] && typed[second] === listing[first];
  const pieces = trigrams(listing);
  const shared = [...trigrams(typed)].filter((piece) => pieces.has(piece)).length;
  const what = swapped ? "Two adjacent letters are swapped." : `${differ.length} characters differ.`;
  return `${what} Full-text search matches whole words, so it cannot find this ID. `
    + `Fuzzy matching compares three-letter pieces, and ${shared} of ${pieces.size} still match.`;
}

/**
 * The mistyped ID beside the listing's own, with the characters that differ
 * marked. Lab 1's fault is exactly this gap: fuzzy matching is the only search
 * that can bridge it, so showing it says why the product went missing. Once the
 * repair is verified it opens on the card, as letters, with why fuzzy matching
 * could bridge it.
 */
function IdComparison({ typed, listing, open = false }: { typed: string; listing: string; open?: boolean }) {
  if (typed.length !== listing.length || typed === listing) return null;
  const mark = (text: string) =>
    [...text].map((character, index) =>
      character === (text === typed ? listing : typed)[index]
        ? <span key={index}>{character}</span>
        : <mark key={index}>{character}</mark>);
  const ids = (
    <dl className="shop-fault-ids">
      <dt>Alex typed</dt>
      <dd aria-label={typed}>{mark(typed)}</dd>
      <dt>Listing ID</dt>
      <dd aria-label={listing}>{mark(listing)}</dd>
    </dl>
  );
  if (!open) return ids;
  return (
    <div className="shop-fault-ids-open">
      {ids}
      <p>{idDifference(typed, listing)}</p>
    </div>
  );
}

/** The intended product and observed result, without revealing the repair. */
export const LabFaultCard = forwardRef<HTMLElement, {
  mission: MosaicLabMission;
  labNumber: number;
  state: "broken" | "fixed";
  /** Whether the target came back at all; a broken run can still return it. */
  targetPresent: boolean;
  /** The graded outcome's explanation, from `labOutcome`. */
  detail: string;
  /** The target's final position when it came back. */
  finalRank: number | null;
  playgroundHref: string;
  onSearchAgain: () => void;
}>(function LabFaultCard(
  {
    mission, labNumber, state, targetPresent, detail, finalRank,
    playgroundHref, onSearchAgain,
  },
  ref,
) {
  const targetId = mission.target_product_ids[0];
  const [product, setProduct] = useState<ProductDetail | null>(null);
  useEffect(() => {
    let current = true;
    api.product(targetId)
      .then((detail) => {
        if (current) setProduct(detail);
      })
      .catch(() => {
        // The request and observed result remain usable without listing metadata.
      });
    return () => {
      current = false;
    };
  }, [targetId]);

  const name = mission.target_display_name ?? product?.title ?? "intended product";
  const fixed = state === "fixed";
  const missing = !fixed && !targetPresent;
  let heading = `Check how the ${name} was found`;
  if (fixed) heading = "Repair verified";
  else if (missing) heading = `The ${name} is missing from these results`;
  return (
    <section
      ref={ref}
      className="shop-fault-card"
      data-state={state}
      data-missing={missing || undefined}
      aria-label={`Lab ${labNumber} outcome`}
    >
      <div className="shop-fault-body">
        <h2>{heading}</h2>
        {fixed ? <p className="shop-fault-verdict">
          {finalRank ? `${name} was found by fuzzy matching and is back at #${finalRank}.` : `${name} was found by fuzzy matching again.`}
        </p> : null}
        {fixed && product?.sku ? <IdComparison typed={mission.query} listing={product.sku} open /> : null}
        <p className="shop-fault-detail">
          {fixed ? detail : missing
            ? "The products below are other matches. None is the listing Alex requested."
            : "The requested listing is present, but this search has not verified the repair."}
        </p>
        {!fixed ? <div className="shop-fault-actions">
          <button type="button" className="shop-fault-search" onClick={onSearchAgain}>Search again</button>
          <span className="shop-fault-repeat-hint">After applying your SQL, repeat this search.</span>
        </div> : null}
        <details className="shop-fault-evidence">
          <summary>Lab {labNumber}: request and evidence</summary>
          {!fixed && product?.sku ? <IdComparison typed={mission.query} listing={product.sku} /> : null}
          {!fixed ? <p>Inspect the search details to see why. Keep the same request and filters as you investigate.</p> : null}
          <Link className="shop-fault-inspect" href={playgroundHref}>
            {fixed ? "See how this was retrieved in the Playground" : "Inspect this run in the Playground"}
          </Link>
        </details>
      </div>
    </section>
  );
});
