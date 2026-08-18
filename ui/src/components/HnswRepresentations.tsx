import { Info, Layers } from "lucide-react";
import { formatBytes } from "../hnsw";
import type { HnswRepresentations as Representations } from "../types";

const LABELS: Record<string, string> = {
  fp32: "vector(1024)",
  halfvec: "halfvec(1024)",
  binary_two_pass: "bit(1024) two-pass",
};

type HnswRepresentationsProps = {
  representations: Representations;
  fp32SizeBytes: number;
};

/**
 * The same 500,000 vectors in three index representations.
 *
 * Sits directly after the storage anatomy because it answers the question that panel
 * provokes: the index costs 3,905 MB, so can it cost less. halfvec and bit are casts of the
 * existing fp32 column, so nothing is re-embedded.
 */
export function HnswRepresentations({
  representations,
  fp32SizeBytes,
}: HnswRepresentationsProps) {
  const { rows, payload_bytes, quantization_distribution, blog_operating_point } =
    representations;
  const distribution = quantization_distribution;
  const headline = rows.filter(
    (row) => row.representation !== "binary_two_pass" || row.overfetch === 200,
  );

  return (
    <section className="hnsw-repr" aria-labelledby="hnsw-repr-title">
      <header>
        <div>
          <h2 id="hnsw-repr-title">The same vectors, three ways to store them.</h2>
          <p>
            halfvec and bit are casts of the fp32 column, not new embeddings. Recall for every
            representation is measured against the exact fp32 answer, so none of them is
            graded against itself.
          </p>
        </div>
        <span className="hnsw-evidence-badge measured">MEASURED</span>
      </header>

      <div
        aria-label="Vector representation benchmark"
        className="hnsw-table-scroll"
        role="region"
        tabIndex={0}
      >
        <table className="hnsw-repr-table">
          <thead>
            <tr>
              <th scope="col">Representation</th>
              <th scope="col">Payload</th>
              <th scope="col">Index</th>
              <th scope="col">Per vector</th>
              <th scope="col">Recall@{representations.k}</th>
              <th scope="col">Server</th>
              <th scope="col">Build</th>
            </tr>
          </thead>
          <tbody>
            {headline.map((row) => {
              const payload =
                row.representation === "fp32"
                  ? payload_bytes.fp32
                  : row.representation === "halfvec"
                    ? payload_bytes.halfvec
                    : payload_bytes.binary;
              return (
                <tr
                  className={row.representation === "halfvec" ? "recommended" : undefined}
                  key={`${row.representation}-${row.overfetch ?? "none"}`}
                >
                  <th scope="row">
                    <code>{LABELS[row.representation] ?? row.representation}</code>
                    {row.representation === "halfvec" ? <em>recommended</em> : null}
                  </th>
                  <td>{payload.toLocaleString()} B</td>
                  <td>
                    {formatBytes(row.index_size_bytes)}
                    <small>
                      {(fp32SizeBytes / row.index_size_bytes).toFixed(1)}x smaller
                    </small>
                  </td>
                  <td>{row.bytes_per_vector.toLocaleString()} B</td>
                  <td>{(row.recall_at_k * 100).toFixed(2)}%</td>
                  <td>{row.server_ms} ms</td>
                  <td>
                    {row.build_seconds !== null
                      ? `${Math.round(row.build_seconds)} s`
                      : row.representation === "fp32"
                        ? "Existing index"
                        : "Not captured"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="hnsw-repr-notes">
        <div className="hnsw-repr-note">
          <Layers aria-hidden="true" size={16} />
          <div>
            <strong>Halving the element cut the index by 3x, not 2x.</strong>
            <p>
              An 8 kB page holds exactly one {payload_bytes.fp32.toLocaleString()}-byte fp32
              element, so fp32 pays a whole page per vector. A{" "}
              {payload_bytes.halfvec.toLocaleString()}-byte halfvec element packs three to a
              page, which is why per-vector cost falls from{" "}
              {rows[0]?.bytes_per_vector.toLocaleString()} to{" "}
              {rows[1]?.bytes_per_vector.toLocaleString()} bytes. Crossing a packing threshold,
              not compressing a vector.
            </p>
          </div>
        </div>

        <div className="hnsw-repr-note">
          <Info aria-hidden="true" size={16} />
          <div>
            <strong>Binary needs depth on this distribution, and then it wins.</strong>
            <p>
              {distribution.dimensions_over_80pct_one_sided} of{" "}
              {distribution.dimensions_total} dimensions are more than 80% one-sided, so
              roughly {Math.round(
                (distribution.dimensions_over_80pct_one_sided /
                  distribution.dimensions_total) *
                  100,
              )}
              % of the bits carry no discriminative information, and hamming ordering agrees
              with cosine on only {Math.round(distribution.top50_hamming_cosine_overlap * 100)}%
              of the top 50. Reranking is what recovers it.
            </p>
          </div>
        </div>
      </div>

      <details className="hnsw-repr-operating-point">
        <summary>Operating point where binary overtakes fp32</summary>
        <div
          aria-label="Binary operating point"
          className="hnsw-table-scroll"
          role="region"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th scope="col">Configuration</th>
                <th scope="col">Recall@{blog_operating_point.k}</th>
                <th scope="col">Server</th>
                <th scope="col">Buffers</th>
              </tr>
            </thead>
            <tbody>
              {blog_operating_point.rows.map((row) => (
                <tr key={row.config}>
                  <th scope="row">{row.config}</th>
                  <td>{(row.recall_at_k * 100).toFixed(2)}%</td>
                  <td>{row.server_ms} ms</td>
                  <td>{row.shared_hit_blocks.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>{blog_operating_point.tradeoff}</p>
        <p className="hnsw-repr-reference">
          Reference: <cite>{blog_operating_point.reference}</cite>.
        </p>
      </details>
    </section>
  );
}
