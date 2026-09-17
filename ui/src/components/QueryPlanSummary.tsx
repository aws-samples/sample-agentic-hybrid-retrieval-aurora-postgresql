import type { RetrievalPlanResponse } from "../types";
import "../retrieval-readout.css";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function number(value: unknown, unit = ""): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toLocaleString("en-US", { maximumFractionDigits: 3 })}${unit}`
    : "Not reported";
}

/** Summarize reported nodes without inferring plans hidden inside SQL functions. */
export function QueryPlanSummary({ plan }: { plan: RetrievalPlanResponse["plan"] }) {
  const statement = plan[0];
  const root = record(statement?.Plan);
  if (!root) return <p>PostgreSQL did not report a plan tree. Inspect the raw response below.</p>;

  const indexes = new Set<string>();
  let hasFunctionScan = false;
  function visit(node: Record<string, unknown>) {
    if (typeof node["Index Name"] === "string") indexes.add(node["Index Name"]);
    if (node["Node Type"] === "Function Scan") hasFunctionScan = true;
    if (Array.isArray(node.Plans)) {
      node.Plans.forEach((child) => {
        const entry = record(child);
        if (entry) visit(entry);
      });
    }
  }
  visit(root);

  return <section className="retrieval-readout" aria-label="Plan capture summary">
    <p><strong>New SQL execution</strong> · {typeof root["Node Type"] === "string" ? root["Node Type"] : "Node type not reported"}</p>
    <dl>
      <div><dt>Planning time</dt><dd>{number(statement["Planning Time"], " ms")}</dd></div>
      <div><dt>Execution time</dt><dd>{number(statement["Execution Time"], " ms")}</dd></div>
      <div><dt>Estimated rows per loop</dt><dd>{number(root["Plan Rows"])}</dd></div>
      <div><dt>Actual rows per loop</dt><dd>{number(root["Actual Rows"])}</dd></div>
      <div><dt>Loops</dt><dd>{number(root["Actual Loops"])}</dd></div>
      <div><dt>Shared buffer hits</dt><dd>{number(root["Shared Hit Blocks"])}</dd></div>
      <div><dt>Shared blocks read</dt><dd>{number(root["Shared Read Blocks"])}</dd></div>
      <div><dt>Temp blocks read / written</dt><dd>{number(root["Temp Read Blocks"])} / {number(root["Temp Written Blocks"])}</dd></div>
    </dl>
    <p>Rows and buffers describe the top node. Buffer counts include its children;
      adding child counts would count the same work twice. A shared block read can
      come from another cache; it does not establish a storage read.</p>
    <p><strong>Index names visible in this plan</strong><br />{indexes.size
      ? [...indexes].map((name, index) => <span key={name}>{index ? ", " : ""}<code>{name}</code></span>)
      : "No index name reported."}</p>
    {hasFunctionScan ? <p>A Function Scan does not expose the queries inside that function.
      This plan alone cannot establish which indexes those queries used.</p> : null}
  </section>;
}
