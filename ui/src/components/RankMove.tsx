import "../rank-move.css";

/**
 * How a product's position changed from one stage to the next: ▲ n in green
 * when it moved up, ▼ n in red when it moved down, a soft dash when it did not
 * move, and "new" when the earlier stage never ranked it. `from` and `to` are
 * positions, so a smaller number is higher.
 */
export function RankMove({ from, to }: { from: number | null; to: number }) {
  if (from === null) {
    return <span className="rank-move" data-move="new">new</span>;
  }
  const places = from - to;
  if (places === 0) {
    return <span className="rank-move" data-move="same" aria-label="unchanged">—</span>;
  }
  const up = places > 0;
  return (
    <span className="rank-move" data-move={up ? "up" : "down"}>
      <span aria-hidden="true">{up ? "▲" : "▼"} {Math.abs(places)}</span>
      <span className="sr-only">{up ? "up" : "down"} {Math.abs(places)}</span>
    </span>
  );
}
