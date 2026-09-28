import { ArrowUpRight, Check, Quote, ShoppingBag, Star, X } from "lucide-react";
import { Fragment, type MouseEvent, type ReactNode } from "react";
import { cartQuantityLimit, useCommerce } from "../../commerce";
import { specFacts } from "../../format";
import { productImage } from "../../media";
import type { AgentCitation, ProductSummary } from "../../types";
import {
  comparisonRows,
  isReview,
  pickName,
  retrievalPath,
  unknowns,
  type ComparisonCell,
  type ComparisonRow,
} from "./comparison";

/** The id of source `number` in this answer's source list. */
export const sourceAnchor = (answerId: string, number: number) => `${answerId}-source-${number}`;

function jumpToSource(event: MouseEvent<HTMLAnchorElement>, id: string) {
  const target = document.getElementById(id);
  if (!target) return;
  // The panel scrolls, not the page; a hash would also enter browser history.
  event.preventDefault();
  target.scrollIntoView({ block: "nearest" });
  target.focus({ preventScroll: true });
}

function Citations({ numbers, answerId }: { numbers: number[]; answerId: string }) {
  return (
    <>
      {numbers.map((number) => {
        const id = sourceAnchor(answerId, number);
        return (
          <a
            key={number}
            className="ask-answer-cite"
            href={`#${id}`}
            aria-label={`Source ${number}`}
            onClick={(event) => jumpToSource(event, id)}
          >
            {number}
          </a>
        );
      })}
    </>
  );
}

/**
 * The first pick, photographed first: what a shopper recognises before they
 * read. Its path through search sits under the name, so the recommendation
 * still shows where retrieval found it.
 */
export function BestPick({
  product,
  imageSrc,
  onSelectProduct,
}: {
  product: ProductSummary;
  imageSrc?: string;
  onSelectProduct: (productId: number) => void;
}) {
  const facts = specFacts(product.specs, 3).map((fact) => fact.value);
  const path = retrievalPath(product);
  return (
    <article className="ask-best-pick" aria-label={`Best fit: ${pickName(product)}`}>
      <button
        type="button"
        className="ask-best-pick-photo"
        onClick={() => onSelectProduct(product.product_id)}
        aria-label={`Open ${pickName(product)}`}
      >
        <img src={imageSrc ?? productImage(product)} alt="" loading="lazy" decoding="async" />
      </button>
      <div className="ask-best-pick-copy">
        <span className="ask-best-pick-badge">Best fit</span>
        <h4>{pickName(product)}</h4>
        <p className="ask-best-pick-facts">
          {facts.join(" · ")}
          {product.review_count && product.rating !== null ? (
            <span>
              <Star size={12} fill="currentColor" aria-hidden="true" />
              {product.rating.toFixed(1)} from {product.review_count.toLocaleString()} ratings
            </span>
          ) : null}
        </p>
        {path.length ? (
          <p className="ask-best-pick-path" aria-label="How search found it">
            {path.map((step, index) => (
              <span key={step}>
                {index ? <span aria-hidden="true">→</span> : null}
                {step}
              </span>
            ))}
          </p>
        ) : null}
        <p className="ask-best-pick-links">
          <button type="button" onClick={() => onSelectProduct(product.product_id)}>Why this pick</button>
          {product.listing_url ? (
            <a href={product.listing_url} target="_blank" rel="noreferrer">
              Original listing <ArrowUpRight size={13} aria-hidden="true" />
            </a>
          ) : null}
        </p>
      </div>
    </article>
  );
}

const SOURCE_NAME: Record<ComparisonCell["source"], string> = {
  listing: "from the listing",
  title: "from the listing title only",
  review: "from reviews",
  not_stated: "",
};

/**
 * The icon is the verdict, and only a requirement has one; where a figure came
 * from is said in words, so one mark never means two things.
 */
function Cell({ cell, answerId, headers }: { cell: ComparisonCell; answerId: string; headers?: string }) {
  const verdict = cell.status === "not_met" ? "Not met: " : cell.status === "met" ? "Meets: " : "";
  const icon = cell.status === "not_met"
    ? <X size={14} aria-hidden="true" />
    : cell.status === "met"
      ? <Check size={14} aria-hidden="true" />
      : cell.source === "review"
        ? <Quote size={13} aria-hidden="true" />
        : null;
  const state = cell.status === "not_met" ? "not-met" : cell.status === "met" ? "met" : cell.source;
  return (
    <td className={`ask-compare-cell is-${state}`} headers={headers}>
      <div>
        <span className="ask-compare-icon">{icon}</span>
        <span>
          <span className="ask-compare-figure">
            {verdict ? <span className="sr-only">{verdict}</span> : null}
            <span className="ask-compare-value">{cell.text}</span>
            {SOURCE_NAME[cell.source] ? <span className="sr-only">, {SOURCE_NAME[cell.source]}</span> : null}
            <Citations numbers={cell.citations} answerId={answerId} />
          </span>
          {cell.source === "title" ? <small aria-hidden="true">Title only</small> : null}
        </span>
      </div>
    </td>
  );
}

/** What the marks mean, for the marks this table actually uses. */
function CompareKey({ rows }: { rows: ComparisonRow[] }) {
  const cells = rows.flatMap((row) => row.cells);
  const entries: [string, ReactNode, string][] = [
    ["met", <Check size={13} aria-hidden="true" />, "Meets what you asked"],
    ["not-met", <X size={13} aria-hidden="true" />, "Short of what you asked"],
    ["title", <small>Title only</small>, "only the listing’s title states it"],
  ];
  const present = (key: string) => cells.some((cell) => (
    key === "met" ? cell.status === "met" : key === "not-met" ? cell.status === "not_met" : cell.source === "title"
  ));
  return (
    <p className="ask-compare-key" aria-hidden="true">
      {entries.filter(([key]) => present(key)).map(([key, mark, label]) => (
        <span key={key} className={`is-${key}`}>{mark}{label}</span>
      ))}
      <span>Other values come from the listing. Numbers open their sources.</span>
    </p>
  );
}

/** A demo-catalog pick goes in the bag; a real listing links to its source. */
function PickAction({ product }: { product: ProductSummary }) {
  const { addItem, itemQuantity } = useCommerce();
  if (product.listing_url) {
    return (
      <a className="ask-compare-action" href={product.listing_url} target="_blank" rel="noreferrer">
        Listing <ArrowUpRight size={13} aria-hidden="true" />
      </a>
    );
  }
  if (product.source_dataset) return null;
  const inBag = itemQuantity(product.product_id);
  const limit = cartQuantityLimit(product);
  return (
    <button
      className="ask-compare-action"
      type="button"
      disabled={!limit || inBag >= limit}
      title={limit ? undefined : "Out of stock"}
      onClick={() => addItem(product)}
    >
      <ShoppingBag size={13} aria-hidden="true" />
      {inBag ? `In bag (${inBag})` : "Add to bag"}
    </button>
  );
}

/**
 * Every pick against the same rows, each cell saying where its fact came from.
 * Two picks keep a label column; three give each row's label its own line, so
 * the picks share the panel's full width.
 */
export function PickComparison({
  picks,
  citations,
  questions,
  answerId,
  imageByProductId,
  onSelectProduct,
}: {
  picks: ProductSummary[];
  citations: AgentCitation[];
  questions: string[];
  answerId: string;
  imageByProductId: Map<number, string>;
  onSelectProduct: (productId: number) => void;
}) {
  const rows: ComparisonRow[] = comparisonRows(picks, citations, questions);
  const changed = rows.some((row) => row.changed);
  const stacked = picks.length > 2;
  const pickId = (pick: ProductSummary) => `${answerId}-pick-${pick.product_id}`;
  const rowLabel = (row: ComparisonRow) => (
    <>
      {row.label}
      {row.changed ? <small>Your new requirement</small> : null}
    </>
  );
  return (
    <div className="ask-compare" data-layout={stacked ? "stacked" : "columns"}>
      <table>
        <caption>{changed ? "Against your new requirement" : "Side by side"}</caption>
        <thead>
          <tr>
            {stacked ? null : <th scope="col"><span className="sr-only">Detail</span></th>}
            {picks.map((pick) => (
              <th scope="col" id={pickId(pick)} key={pick.product_id} data-product-id={pick.product_id}>
                <button type="button" onClick={() => onSelectProduct(pick.product_id)} aria-label={`Open ${pick.title}`}>
                  <img src={imageByProductId.get(pick.product_id) ?? productImage(pick)} alt="" loading="lazy" decoding="async" />
                  <span>{pickName(pick)}</span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const labelId = `${answerId}-row-${row.key}`;
            const cells = row.cells.map((cell, index) => (
              <Cell
                key={picks[index].product_id}
                cell={cell}
                answerId={answerId}
                headers={stacked ? `${labelId} ${pickId(picks[index])}` : undefined}
              />
            ));
            return stacked ? (
              <Fragment key={row.key}>
                <tr className={`ask-compare-label-row${row.changed ? " is-changed" : ""}`}>
                  <th id={labelId} colSpan={picks.length}>{rowLabel(row)}</th>
                </tr>
                <tr className={row.changed ? "is-changed" : undefined}>{cells}</tr>
              </Fragment>
            ) : (
              <tr key={row.key} className={row.changed ? "is-changed" : undefined}>
                <th scope="row">{rowLabel(row)}</th>
                {cells}
              </tr>
            );
          })}
          <tr className="ask-compare-actions">
            {stacked ? null : <th scope="row"><span className="sr-only">Buy or open</span></th>}
            {picks.map((pick) => <td key={pick.product_id}><PickAction product={pick} /></td>)}
          </tr>
        </tbody>
      </table>
      <CompareKey rows={rows} />
    </div>
  );
}

const EXCERPT_LENGTH = 150;

function excerpt(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > EXCERPT_LENGTH ? `${flat.slice(0, EXCERPT_LENGTH).replace(/\s\S*$/, "")}…` : flat;
}

/**
 * The answer's sources, numbered as the table and the prose cite them, then
 * what those sources leave open.
 */
export function AnswerSources({
  picks,
  citations,
  questions,
  answerId,
}: {
  picks: ProductSummary[];
  citations: AgentCitation[];
  questions: string[];
  answerId: string;
}) {
  const reviews = citations.filter(isReview).length;
  const listings = citations.length - reviews;
  const open = unknowns(picks, comparisonRows(picks, citations, questions));
  const nameFor = (productId: number) => {
    const pick = picks.find((item) => item.product_id === productId);
    return pick ? pickName(pick) : null;
  };
  return (
    <footer className="ask-answer-sources">
      <p>
        <strong>{citations.length} {citations.length === 1 ? "source" : "sources"}</strong>
        {" · "}
        {listings} from {listings === 1 ? "a listing" : "listings"} · {reviews} from {reviews === 1 ? "a review" : "reviews"}
      </p>
      <ol className="ask-answer-source-list">
        {citations.map((citation) => (
          <li key={citation.number} id={sourceAnchor(answerId, citation.number)} tabIndex={-1} value={citation.number}>
            <span className="ask-answer-source-kind">{isReview(citation) ? "Review" : "Listing"}</span>
            {nameFor(citation.product_id) ? <strong>{nameFor(citation.product_id)}</strong> : null}
            {isReview(citation) && citation.quote ? <q>{excerpt(citation.quote)}</q> : null}
            <a href={`/api/evidence/${citation.evidence_id}`} target="_blank" rel="noreferrer">
              Record {citation.evidence_id} <ArrowUpRight size={12} aria-hidden="true" />
            </a>
          </li>
        ))}
      </ol>
      <div>
        <strong>Still unknown</strong>
        <ul>
          {open.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
    </footer>
  );
}
