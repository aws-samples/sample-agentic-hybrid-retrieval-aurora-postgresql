import type { AgentResponse, ProductSummary } from "../../types";
import type { PipelineReceipt } from "../../usePipelineRun";
import { pickName } from "../ask-mosaic/comparison";

function traceName(product: ProductSummary) {
  const name = pickName(product).replace(/\s+(with|and|for)$/i, "");
  return product.brand && !name.toLowerCase().includes(product.brand.toLowerCase()) ? `${product.brand} ${name}` : name;
}

export function RunSummary({ answer, receipts, onInspect }: {
  answer: AgentResponse;
  receipts: PipelineReceipt[];
  onInspect: (searchId: string, productId: number) => void;
}) {
  const products = new Map<number, ProductSummary>();
  for (const receipt of receipts) {
    for (const product of receipt.response?.results ?? []) products.set(product.product_id, product);
  }
  const positions = (productId: number) => receipts.flatMap((receipt, index) => {
    const product = receipt.response?.results.find((item) => item.product_id === productId);
    return product ? [{ id: receipt.id, search: index + 1, rank: product.signals?.final_rank }] : [];
  });
  const compared = new Set(answer.trace.filter((step) => step.tool === "compare_products" && step.outcome === "success")
    .flatMap((step) => Array.isArray(step.arguments?.product_ids) ? step.arguments.product_ids : []));
  const unavailable = receipts.some((receipt) => !receipt.response);
  return <section className="pg-summary" aria-labelledby="pg-summary-title">
    <header>
      <h2 id="pg-summary-title">{answer.outcome === "declined" ? "No supported recommendation" : "Mosaic’s final answer"}</h2>
      <a href="#inspect-reason">Read the answer</a>
    </header>
    <p>{receipts.length} {receipts.length === 1 ? "search" : "searches"} · {answer.recommendations.length} {answer.recommendations.length === 1 ? "product" : "products"} in the answer · {answer.citations.length} cited {answer.citations.length === 1 ? "source" : "sources"}</p>
    {answer.recommendations.length ? <ul className="pg-summary-picks" aria-label="Products in the final answer">{answer.recommendations.map((product) => {
      const match = positions(product.product_id)[0];
      return <li key={product.product_id}>{match
        ? <button type="button" aria-label={`Trace ${product.title}`} onClick={() => onInspect(match.id, product.product_id)}>{traceName(product)}<span>Search {match.search}{match.rank == null ? "" : ` · #${match.rank}`}</span></button>
        : <span>{traceName(product)}<small>{unavailable ? "Search details unavailable" : "Not in the recorded search results"}</small></span>}</li>;
    })}</ul> : null}
    <p className="pg-summary-note">Retrieve and Rank inspect one search at a time. The final answer can draw on all searches.</p>
    {products.size ? <details className="pg-product-trace">
      <summary>Trace all returned products</summary>
      <div className="pg-trace-scroll" role="region" aria-label="Product trace across searches" tabIndex={0}>
        <table>
          <caption>Only recorded actions are shown. Omission alone does not explain why a product was left out.</caption>
          <thead><tr><th scope="col">Product</th><th scope="col">Search position</th><th scope="col">Compared</th><th scope="col">Evidence read</th><th scope="col">Final answer</th></tr></thead>
          <tbody>{[...products.values()].map((product) => {
            const position = answer.recommendations.findIndex((pick) => pick.product_id === product.product_id);
            const evidence = answer.retrieved_evidence ? new Set(answer.retrieved_evidence.filter((record) => record.product_id === product.product_id).map((record) => record.evidence_id)).size : null;
            const citations = new Set(answer.citations.filter((citation) => citation.product_id === product.product_id).map((citation) => citation.evidence_id)).size;
            return <tr key={product.product_id}>
              <th scope="row"><a href={`/products/${product.product_id}`} title={product.title}>{traceName(product)}</a><small>Listing {product.sku}</small></th>
              <td>{positions(product.product_id).map((match) => <button key={match.id} type="button" aria-label={`Inspect ${product.title} in Search ${match.search}`} onClick={() => onInspect(match.id, product.product_id)}>Search {match.search}{match.rank == null ? "" : ` · #${match.rank}`}</button>)}</td>
              <td>{compared.has(product.product_id) ? "Yes" : "No"}</td>
              <td>{evidence == null ? "Not recorded" : evidence ? `${evidence} ${evidence === 1 ? "record" : "records"}` : "None"}</td>
              <td>{position < 0 ? "Not included" : `Pick ${position + 1} · ${citations} ${citations === 1 ? "source" : "sources"}`}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
      {unavailable ? <p className="inspector-note">Some search records are still loading or unavailable. This trace contains only the records loaded so far.</p> : null}
    </details> : null}
  </section>;
}
