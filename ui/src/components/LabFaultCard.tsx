import { ArrowUpRight, Check, Copy, SearchCheck, SearchX } from "lucide-react";
import { forwardRef, useEffect, useState } from "react";
import { Link } from "wouter";
import { api } from "../api";
import type { MosaicLabMission } from "../labMissions";
import { productImage } from "../media";
import { APPLY_SQL } from "../participantCommands";
import type { ProductDetail } from "../types";
import { CodeEditorLink } from "./CodeEditorLink";

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

function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // The command stays on screen to select by hand.
      setCopied(false);
    }
  }

  return (
    <button
      type="button"
      className="shop-fault-copy"
      aria-label={copied ? "Command copied" : `Copy ${command}`}
      title={copied ? "Copied" : "Copy command"}
      onClick={() => void copy()}
    >
      {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
    </button>
  );
}

/**
 * Lab 1's outcome on Shop, drawn as the product Alex meant.
 *
 * While the fault is in, the tile is the missing listing, dimmed, with the ID
 * Alex typed beside the one the listing has and the four steps back to it. Once
 * the repair lands the same tile comes back in colour at its final position, so
 * the participant sees the product return rather than reading that it did.
 */
export const LabFaultCard = forwardRef<HTMLElement, {
  mission: MosaicLabMission;
  labNumber: number;
  state: "broken" | "fixed";
  /** Whether the target came back at all; a broken run can still return it. */
  targetPresent: boolean;
  /** The graded outcome's title, used when the target is present but unproven. */
  title: string;
  /** The graded outcome's explanation, from `labOutcome`. */
  detail: string;
  /** The target's final position when it came back. */
  finalRank: number | null;
  codeEditorUrl: string | null;
  playgroundHref: string;
  onSearchAgain: () => void;
}>(function LabFaultCard(
  {
    mission, labNumber, state, targetPresent, title, detail, finalRank,
    codeEditorUrl, playgroundHref, onSearchAgain,
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
        // The card still names the product and the steps without its photo.
      });
    return () => {
      current = false;
    };
  }, [targetId]);

  const name = mission.target_display_name ?? product?.title ?? "intended product";
  const edit = mission.participant_edit;
  const fixed = state === "fixed";
  const missing = !fixed && !targetPresent;
  let heading = title;
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
        <h2>{heading}</h2>
        <p className="shop-fault-verdict">
          {fixed
            ? finalRank ? `Found by close spelling and back at #${finalRank}.` : "Found by close spelling again."
            : `Issue reproduced: Lab ${labNumber}'s deliberate fault, not a gap in the catalog.`}
        </p>
        <p className="shop-fault-detail">{detail}</p>

        {!fixed && edit ? (
          <ol className="shop-fault-steps" aria-label="Next steps">
            <li>
              <strong>Open the lab file</strong>
              <p>
                <code>{edit.file}</code>
                <CodeEditorLink href={codeEditorUrl} className="shop-fault-editor" />
              </p>
            </li>
            <li>
              <strong>Repair the marked blocks</strong>
              <p>{edit.task} Each block holds a <code>TODO(Lab {labNumber})</code> note.</p>
            </li>
            <li>
              <strong>Apply it to Aurora</strong>
              <p>
                <code>{APPLY_SQL}</code>
                <CopyCommand command={APPLY_SQL} />
              </p>
            </li>
            <li>
              <strong>Search again</strong>
              <p>
                <button type="button" className="shop-fault-search" onClick={onSearchAgain}>
                  Search again
                </button>
                The same request, with the same filters.
              </p>
            </li>
          </ol>
        ) : null}

        <Link className="shop-fault-inspect" href={playgroundHref}>
          {fixed ? "See how this was retrieved in the Playground" : "Inspect this run in the Playground"}
          <ArrowUpRight size={14} aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
});
