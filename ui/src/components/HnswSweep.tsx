import type { HnswEfPoint } from "../types";

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

/** One sentence read from the sweep itself: what the first and last settings return and cost. */
export function sweepTakeaway(sweep: HnswEfPoint[]): string {
  if (sweep.length < 2) return "";
  const first = sweep[0];
  const last = sweep[sweep.length - 1];
  const ratio = (last.server_ms / first.server_ms).toFixed(1);
  return (
    `From ef_search ${first.ef_search} to ${last.ef_search}, recall goes from ` +
    `${percent(first.recall_at_k)} to ${percent(last.recall_at_k)} and database time ` +
    `from ${first.server_ms} ms to ${last.server_ms} ms (${ratio}x).`
  );
}

/**
 * Recall against database time for each measured ef_search, the page's one picture.
 *
 * Recall bars share one 0-100% scale and time bars share the slowest row's scale, so rows
 * compare directly. The served setting is marked; nothing here is derived beyond those scales.
 */
export function HnswSweep({ sweep, served }: { sweep: HnswEfPoint[]; served: number | null }) {
  const slowest = Math.max(...sweep.map((point) => point.server_ms), 1);
  return (
    <div className="sweep-scroll" role="region" aria-label="Recall and database time by ef_search" tabIndex={0}>
      <table className="sweep">
        <thead>
          <tr>
            <th scope="col">ef_search</th>
            <th scope="col">Recall</th>
            <th scope="col">Database time</th>
          </tr>
        </thead>
        <tbody>
          {sweep.map((point) => (
            <tr key={point.ef_search} data-served={point.ef_search === served}>
              <th scope="row">
                {point.ef_search}
                {point.ef_search === served ? <em>served</em> : null}
              </th>
              <td>
                <span className="sweep-bar sweep-bar-recall" aria-hidden="true">
                  <i style={{ width: `${Math.min(point.recall_at_k, 1) * 100}%` }} />
                </span>
                <strong>{percent(point.recall_at_k)}</strong>
              </td>
              <td>
                <span className="sweep-bar sweep-bar-time" aria-hidden="true">
                  <i style={{ width: `${(point.server_ms / slowest) * 100}%` }} />
                </span>
                <strong>{point.server_ms} ms</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
