import { SearchCheck, SearchX } from "lucide-react";
import { forwardRef, useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import type { MosaicLabMission } from "../labMissions";
import { productImage } from "../media";
import type { ProductDetail } from "../types";

/**
 * The mistyped ID beside the listing's own, with the characters that differ
 * marked. Lab 1's fault is exactly this gap: close spelling is the only method
 * that can bridge it, so showing it says why the product went missing.
 */
function IdComparison({ typed, listing }: { typed: string; listing: string }) {
  if (typed.length !== listing.length || typed === listing) return null;
  const mark = (text: string) =>
    [...text].map((character, index) =>
      character === (text === typed ? listing : typed)[index]
        ? <span key={index}>{character}</span>
        : <mark key={index}>{character}</mark>);
  return (
    <dl className="shop-fault-ids">
      <dt>Alex typed</dt>
      <dd>{mark(typed)}</dd>
      <dt>Listing ID</dt>
      <dd>{mark(listing)}</dd>
    </dl>
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
        // Missing media must not hide the product identity or observation.
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
      <figure className="shop-fault-plate">
        <div className="shop-fault-photo">
          <span className="shop-fault-status">
            {missing
              ? <><SearchX size={14} aria-hidden="true" /> Not in these results</>
              : <><SearchCheck size={14} aria-hidden="true" /> {fixed ? "Back in the results" : "In the results"}</>}
          </span>
          {product ? <img src={productImage(product)} alt="" decoding="async" /> : null}
        </div>
        <figcaption>
          <strong className="shop-fault-name">{name}</strong>
          {product?.sku ? <IdComparison typed={mission.query} listing={product.sku} /> : null}
        </figcaption>
      </figure>

      <div className="shop-fault-body">
        <span className="shop-lab-status">{fixed ? "Verified in this search" : `Lab ${labNumber} / Observe`}</span>
        <h2>{heading}</h2>
        {fixed ? <p className="shop-fault-verdict">
          {finalRank ? `Found by close spelling and back at #${finalRank}.` : "Found by close spelling again."}
        </p> : null}
        <p className="shop-fault-detail">
          {fixed ? detail : "Inspect the search details and predict why. Keep the same request and filters as you investigate."}
        </p>
        <div className="shop-fault-actions">
          {!fixed ? <button type="button" className="shop-fault-search" onClick={onSearchAgain}>Search again</button> : null}
          <Link className="shop-fault-inspect" href={playgroundHref}>
            {fixed ? "See how this was retrieved in the Playground" : "Inspect this run in the Playground"}
          </Link>
        </div>
      </div>
    </section>
  );
});
