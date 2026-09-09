import type { AgentResponse, EvidenceRecord } from "../types";

const isReview = (record: EvidenceRecord) => record.evidence_type.includes("review");

/** Compare the snapshots read in this run, without fetching different sources afterward. */
export function SourceComparison({ answer }: { answer: AgentResponse }) {
  if (answer.retrieved_evidence === undefined) return <p className="inspector-note">This saved response contains citations only. Start a new run to compare all the sources the agent reads.</p>;
  return <div className="inspector-source-comparison">
    <p>Specifications describe the product. Reviews describe an experience. Check whether each source supports the benefit Alex needs.</p>
    <p className="inspector-note">Mosaic’s catalog and reviews are sample data. “Cited” means the answer refers to that record; it does not prove every claim.</p>
    {answer.recommendations.map((product, index) => {
      const records = answer.retrieved_evidence!.filter((record) => record.product_id === product.product_id);
      const specs = records.filter((record) => record.evidence_type === "product_spec");
      const reviews = records.filter(isReview);
      const other = records.filter((record) => record.evidence_type !== "product_spec" && !isReview(record));
      const queries = [...new Set(answer.trace.filter((step) => step.tool === "get_product_evidence" && step.outcome === "success" && step.arguments.product_id === product.product_id).map((step) => step.arguments.evidence_query).filter((query): query is string => typeof query === "string"))];
      return <details className="inspector-source-product" key={product.product_id} open={index === 0}>
        <summary>{product.title}</summary>
        {queries.length ? <p className="inspector-note">Evidence {queries.length === 1 ? "question" : "questions"}: {queries.join("; ")}</p> : null}
        {[{ label: "Specification", sources: specs }, { label: "Review", sources: reviews }, { label: "Other source", sources: other }].map(({ label, sources }) => {
          if (label === "Other source" && !sources.length) return null;
          return <section key={label} aria-label={`${product.title}: ${label}`}>
            <h4>{label}</h4>
            {sources.length ? sources.map((record) => {
              const citations = answer.citations.filter((citation) => citation.evidence_id === record.evidence_id && citation.product_id === record.product_id);
              return <article className="inspector-source-record" key={record.evidence_id}>
                <p className="inspector-source-use">{citations.length ? `Cited ${citations.map((citation) => `[${citation.number}]`).join(" ")}` : "Read, not cited"}</p>
                <strong>{record.title}</strong>
                <blockquote>{record.text}</blockquote>
                <small>{record.source_name} · Revision {record.revision}</small>
                <a href={`/api/evidence/${record.evidence_id}`} target="_blank" rel="noreferrer">Open source record {record.evidence_id}</a>
              </article>;
            }) : <p className="inspector-source-missing">No {label.toLowerCase()} was retrieved for this product. This run cannot establish what that source would say.</p>}
          </section>;
        })}
      </details>;
    })}
  </div>;
}
