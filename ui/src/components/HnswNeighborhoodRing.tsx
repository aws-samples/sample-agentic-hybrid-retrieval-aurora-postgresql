import { Images, Target } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { neighborhoodPhotographs, ringPoints } from "../hnsw";
import type { HnswNeighborhood, HnswProbe, HnswProduct } from "../types";

const RADIUS = 150;
const VIEW = RADIUS * 2 + 80;
const EASE_OUT = [0.16, 1, 0.3, 1] as const;

type HnswNeighborhoodRingProps = {
  neighborhood: HnswNeighborhood;
  anchors: HnswProduct[];
  onAnchorChange: (productId: number) => void;
  probe: HnswProbe | null;
  efSearch: number;
};

/**
 * The anchor's true neighbours, placed at their real cosine distances.
 *
 * The tight band makes this a useful recall stress test: on the measured corpus ranks 2
 * through 10 span about 0.03 in cosine distance, so small ordering changes stay visible.
 * Radius is scaled across that band rather than from zero, or every neighbour would land
 * on top of every other; the real distances print alongside so the spread is not read as
 * wider than it is.
 *
 * Every neighbour renders with catalog photography. Product-bound imagery remains
 * distinguishable from same-category representation, so adding visual identity does
 * not turn the graph into a false product-to-image claim.
 */
export function HnswNeighborhoodRing({
  neighborhood,
  anchors,
  onAnchorChange,
  probe,
  efSearch,
}: HnswNeighborhoodRingProps) {
  const { anchor, neighbors, band } = neighborhood;
  const placed = ringPoints(neighbors, band, RADIUS);
  const missed = new Set(probe?.missed ?? []);
  const byId = new Map(neighbors.map((neighbor) => [neighbor.product_id, neighbor]));
  const photographs = neighborhoodPhotographs([anchor, ...neighbors]);
  const anchorImage = photographs.get(anchor.product_id)!;
  const reduceMotion = useReducedMotion() ?? false;
  const anchorClipId = `hnsw-anchor-clip-${anchor.product_id}`;

  return (
    <section className="hnsw-ring" aria-labelledby="hnsw-ring-title">
      <header>
        <div>
          <h2 id="hnsw-ring-title">The neighbours sit in a band 0.03 wide.</h2>
          <p>
            Exact top-{neighborhood.k} for one real product, plotted at measured cosine
            distance. The tight distance band makes this a useful recall stress test:
            small ordering changes stay visible, and the plateau helps identify a
            defensible operating point.
          </p>
        </div>
        <label className="hnsw-ring-picker">
          <span>Query anchor</span>
          <select
            onChange={(event) => onAnchorChange(Number(event.target.value))}
            value={anchor.product_id}
          >
            {anchors.map((option) => (
              <option key={option.product_id} value={option.product_id}>
                {option.title}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="hnsw-ring-layout">
        <figure className="hnsw-ring-plot">
          <svg
            aria-label={
              band === null
                ? `No neighbours stored for ${anchor.title}`
                : `${placed.length} neighbours of ${anchor.title}, from cosine distance ` +
                  `${band.nearest.toFixed(4)} to ${band.kth.toFixed(4)}` +
                  (missed.size > 0
                    ? `. ${missed.size} missed at ef_search ${efSearch}.`
                    : "")
            }
            role="img"
            viewBox={`0 0 ${VIEW} ${VIEW}`}
          >
            <AnimatePresence initial mode="wait">
              <motion.g
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                initial={{ opacity: 0 }}
                key={anchor.product_id}
                transform={`translate(${VIEW / 2} ${VIEW / 2})`}
                transition={{ duration: reduceMotion ? 0.16 : 0.12, ease: EASE_OUT }}
              >
                {[RADIUS * 0.55, RADIUS].map((radius, index) => (
                  <motion.circle
                    animate={{ opacity: 1 }}
                    className="ring-guide"
                    cx="0"
                    cy="0"
                    initial={{ opacity: 0 }}
                    key={radius}
                    r={radius}
                    transition={{
                      delay: reduceMotion ? 0 : 0.08 + index * 0.03,
                      duration: 0.2,
                      ease: EASE_OUT,
                    }}
                  />
                ))}
                {placed.map((point, index) => (
                  <motion.line
                    animate={{ opacity: 1 }}
                    className="ring-spoke"
                    initial={{ opacity: 0 }}
                    key={`spoke-${point.product_id}`}
                    transition={{
                      delay: reduceMotion ? 0 : 0.14 + index * 0.035,
                      duration: 0.18,
                      ease: EASE_OUT,
                    }}
                    x1="0"
                    y1="0"
                    x2={point.x}
                    y2={point.y}
                  />
                ))}
                <clipPath id={anchorClipId}>
                  <circle cx="0" cy="0" r="46" />
                </clipPath>
                <motion.g
                  animate={{ opacity: 1, transform: "scale(1)" }}
                  initial={{
                    opacity: 0,
                    transform: reduceMotion ? "scale(1)" : "scale(0.94)",
                  }}
                  style={{ transformBox: "fill-box", transformOrigin: "center" }}
                  transition={{ duration: reduceMotion ? 0.16 : 0.24, ease: EASE_OUT }}
                >
                  <image
                    className={`ring-product-image ${anchorImage.kind}`}
                    clipPath={`url(#${anchorClipId})`}
                    height="92"
                    href={anchorImage.src}
                    preserveAspectRatio="xMidYMid slice"
                    width="92"
                    x="-46"
                    y="-46"
                  />
                  <circle className="ring-anchor-frame" cx="0" cy="0" r="46" />
                </motion.g>
                {placed.map((point, index) => {
                  const neighbor = byId.get(point.product_id);
                  const isMissed = missed.has(point.product_id);
                  if (!neighbor) return null;
                  const image = photographs.get(neighbor.product_id)!;
                  const clipId = `clip-${anchor.product_id}-${point.product_id}`;
                  return (
                    <motion.g
                      animate={{
                        opacity: 1,
                        transform: `translate(${point.x}px, ${point.y}px) scale(1)`,
                      }}
                      aria-label={
                        isMissed
                          ? `${neighbor.title} missed at ef_search ${efSearch}`
                          : undefined
                      }
                      className={[
                        "ring-node",
                        image.kind === "category" ? "representative" : "product-bound",
                        isMissed ? "missed" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      initial={{
                        opacity: 0,
                        transform: reduceMotion
                          ? `translate(${point.x}px, ${point.y}px) scale(1)`
                          : "translate(0px, 0px) scale(0.94)",
                      }}
                      key={point.product_id}
                      style={{ transformOrigin: "0px 0px" }}
                      transition={{
                        delay: reduceMotion ? 0 : 0.18 + index * 0.04,
                        duration: reduceMotion ? 0.16 : 0.28,
                        ease: EASE_OUT,
                      }}
                    >
                      <clipPath id={clipId}>
                        <circle cx="0" cy="0" r="19" />
                      </clipPath>
                      <motion.image
                        animate={{ opacity: isMissed ? 0.35 : 1 }}
                        className={`ring-product-image ${image.kind}`}
                        clipPath={`url(#${clipId})`}
                        height="38"
                        href={image.src}
                        initial={false}
                        preserveAspectRatio="xMidYMid slice"
                        transition={{ duration: 0.18, ease: EASE_OUT }}
                        width="38"
                        x="-19"
                        y="-19"
                      />
                      <circle className="ring-node-frame" cx="0" cy="0" r="19" />
                      <circle className="ring-node-rank-backdrop" cx="0" cy="0" r="8" />
                      <text className="ring-node-rank" y="4">
                        {neighbor.neighbor_rank}
                      </text>
                      <title>
                        #{neighbor.neighbor_rank} {neighbor.title}, cosine distance{" "}
                        {point.distance.toFixed(4)}
                        {image.kind === "category"
                          ? " (same-category representative image)"
                          : " (product-bound image)"}
                        {isMissed ? ` (missed at ef_search ${efSearch})` : ""}
                      </title>
                    </motion.g>
                  );
                })}
              </motion.g>
            </AnimatePresence>
          </svg>
          <figcaption>
            <Images aria-hidden="true" size={13} />
            Every circle shows catalog photography. Bound images are exact; the rest use
            verified same-category photography. Titles, ranks, and distances remain
            exact.
          </figcaption>
        </figure>

        <div className="hnsw-ring-detail">
          {band ? (
            <dl className="hnsw-ring-band">
              <div>
                <dt>Nearest neighbour</dt>
                <dd>{band.nearest.toFixed(4)}</dd>
              </div>
              <div>
                <dt>Rank {neighborhood.k}</dt>
                <dd>{band.kth.toFixed(4)}</dd>
              </div>
              <div>
                <dt>Band width</dt>
                <dd>{band.width.toFixed(4)}</dd>
              </div>
            </dl>
          ) : null}

          <p className="hnsw-ring-note">
            <Target aria-hidden="true" size={15} />
            <span>
              Ranks 2 to {neighborhood.k} span{" "}
              <strong>{band ? band.width.toFixed(3) : "no stored band"}</strong> in cosine
              distance.
              Radius is stretched across that band so the ring is readable; the numbers
              above are the real distances.
            </span>
          </p>

          <ol className="hnsw-ring-list">
            {neighbors
              .filter((neighbor) => neighbor.cosine_distance > 0)
              .map((neighbor) => (
                <li
                  className={missed.has(neighbor.product_id) ? "missed" : undefined}
                  key={neighbor.product_id}
                >
                  <span className="rank">{neighbor.neighbor_rank}</span>
                  <span className="identity">
                    <strong>{neighbor.title}</strong>
                    <small>
                      {neighbor.brand_name} · {neighbor.domain.replace(/_/g, " ")}
                    </small>
                  </span>
                  <code>{neighbor.cosine_distance.toFixed(4)}</code>
                  {missed.has(neighbor.product_id) ? (
                    <em>missed at ef_search {efSearch}</em>
                  ) : null}
                </li>
              ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
