import { CircleCheck, HardDrive, ShieldAlert } from "lucide-react";
import type { HnswLocalNvme } from "../types";
import { HnswMeasuredBadge } from "./HnswMeasuredBadge";

type HnswControlledAbProps = {
  nvme: HnswLocalNvme;
  /** Whether the artifact these numbers live in describes the connected cluster. */
  attributed: boolean;
};

/**
 * The controlled scale A/B, deliberately separate from the workshop baseline.
 *
 * Every other measured panel on this page reads the workshop cluster. This one does not: it
 * is a purpose-built pair with a non-default shared_buffers and Aurora I/O-Optimized enabled.
 * AWS documents I/O-Optimized as required for the tiered-cache behaviour, so that condition
 * is in the badge rather than in a footnote, and the boundary statement sits with the result
 * rather than below the fold.
 */
export function HnswControlledAb({ nvme, attributed }: HnswControlledAbProps) {
  const io = nvme.storage_configuration.aurora_io_optimized;
  const standard = nvme.storage_configuration.aurora_standard;
  const gib = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
  // Floor the low end, round the high end. The low end is truncated so the table never
  // claims a faster floor than was measured, and this is the rule that reproduces the
  // headline's stated intervals exactly: 893.50 and 994.96 read as 893-995, and 106.60
  // and 126.05 read as 106-126. Table and headline must not disagree by a millisecond.
  const range = (values: number[]) =>
    `${Math.floor(Math.min(...values))}-${Math.round(Math.max(...values))}`;

  return (
    <section className="hnsw-ab" aria-labelledby="hnsw-ab-title">
      <header>
        <div>
          <h2 id="hnsw-ab-title">Side-by-side test at scale</h2>
          <p>{nvme.claim_class}.</p>
        </div>
        <HnswMeasuredBadge
          attributed={attributed}
          className="ab"
          suffix={
            <>
              {" "}
              · PURPOSE-BUILT AURORA PAIR · {nvme.region.toUpperCase()} ·{" "}
              {gib(nvme.shared_buffers_bytes)} shared_buffers · I/O-OPTIMIZED
            </>
          }
        />
      </header>

      <div className="hnsw-ab-headline">
        <HardDrive aria-hidden="true" size={20} />
        <p>{nvme.headline}</p>
      </div>

      <div className="hnsw-ab-body">
        <div
          aria-label="Controlled Aurora A/B results"
          className="hnsw-table-scroll hnsw-ab-table-scroll"
          role="region"
          tabIndex={0}
        >
          <table className="hnsw-ab-table">
            <thead>
              <tr>
                <th scope="col">Typical cold-cache time (p50)</th>
                <th scope="col">{nvme.control_cluster.split(" / ")[1]}</th>
                <th scope="col">{nvme.test_cluster.split(" / ")[1]}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Latency</th>
                <td>{range(io.r8g_p50_ms)} ms</td>
                <td className="win">{range(io.r8gd_p50_ms_steady)} ms</td>
              </tr>
              <tr>
                <th scope="row">I/O read time</th>
                <td>{range(io.r8g_io_read_ms)} ms</td>
                <td className="win">{range(io.r8gd_io_read_ms_steady)} ms</td>
              </tr>
              <tr>
                <th scope="row">Pages read</th>
                <td>{range(io.read_blocks_r8g)}</td>
                <td>{range(io.read_blocks_r8gd)}</td>
              </tr>
              <tr className="observed">
                <th scope="row">Observed</th>
                <td colSpan={2}>
                  {io.p50_speedup}x speedup, {(io.io_reduction * 100).toFixed(1)}% less
                  I/O wait
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="hnsw-ab-controls">
          <h3>Controls</h3>
          <ul>
            {nvme.controls.map((control) => (
              <li key={control}>
                <CircleCheck aria-hidden="true" size={14} />
                <span>{control}</span>
              </li>
            ))}
          </ul>
          <p className="hnsw-ab-storage">
            On Aurora Standard the same pair measured only{" "}
            {Math.round(standard.mean_improvement * 100)}%. Local NVMe serves temporary objects
            only without I/O-Optimized, and this read path creates none.
          </p>
        </div>
      </div>

      <p className="hnsw-ab-boundary">
        <ShieldAlert aria-hidden="true" size={16} />
        <span>{nvme.boundary}</span>
      </p>
    </section>
  );
}
