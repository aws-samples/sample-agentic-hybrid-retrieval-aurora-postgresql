import { useEffect, useState } from "react";
import { api } from "../../api";
import type { RetrievalRunResponse, SearchResponse } from "../../types";

/** Inspect positions outside the served window without expanding citation scope. */
export function CandidatePoolOrder({ response }: { response?: SearchResponse }) {
  const [saved, setSaved] = useState<RetrievalRunResponse | null>(null);
  const [error, setError] = useState("");
  const [order, setOrder] = useState<"combined" | "final">("combined");
  const eventId = response?.search_event_id;
  useEffect(() => {
    let active = true;
    setSaved(null);
    setError("");
    if (eventId) void api.retrievalEvent(eventId).then((record) => {
      if (active) setSaved(record);
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not read the candidate pool.");
    });
    return () => { active = false; };
  }, [eventId]);
  if (!eventId) return <p>Run a search to compare its saved combined and final positions.</p>;
  if (error) return <p role="alert">Full candidate pool unavailable: {error}</p>;
  if (!saved) return <p role="status">Reading the saved candidate pool…</p>;
  const rows = [...saved.candidates].sort((a, b) => order === "combined"
    ? (a.fused_rank ?? Infinity) - (b.fused_rank ?? Infinity)
    : a.result_rank - b.result_rank);
  const served = new Map(response.results.map((product) => [product.product_id, product.title]));
  const position = (value: number | null) => value == null ? "—" : `#${value}`;
  return <div className="pg-candidate-pool">
    <p>{rows.length} saved candidates. This includes products outside the displayed results.</p>
    <div className="pg-seg" role="group" aria-label="Full candidate pool order">
      <button type="button" aria-pressed={order === "combined"} onClick={() => setOrder("combined")}>Combined order</button>
      <button type="button" aria-pressed={order === "final"} onClick={() => setOrder("final")}>Final order</button>
    </div>
    <div className="pg-pool-scroll" tabIndex={0} role="region" aria-label="Complete saved candidate pool">
      <table className="pg-arm-table">
        <thead><tr><th>Product</th><th>Combined</th><th>Final</th><th>Displayed</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.product_id}>
          <th scope="row">{served.get(row.product_id) ?? `Product ${row.product_id}`}</th>
          <td>{position(row.fused_rank)}</td><td>{position(row.result_rank)}</td><td>{served.has(row.product_id) ? "Yes" : "No"}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p>Search record <code>{eventId}</code>. Re-rank: {response.diagnostics?.rerank_status ?? "not recorded"}.</p>
  </div>;
}
