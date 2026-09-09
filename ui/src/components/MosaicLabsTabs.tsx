import { Link } from "wouter";
import { RETRIEVAL_SURFACE } from "../navigation";

type MosaicLabsTab = "retrieval" | "hnsw" | "memory";

const sourceRepositoryUrl =
  "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql";

/** Shared navigation for how Mosaic searches and remembers. */
export function MosaicLabsTabs({
  active,
}: {
  /**
   * Which entry is current, omitted by a surface that is not one of them.
   * Catalog studio carries the strip so a reader can leave it, and marks
   * nothing: it is no longer a Playground lens.
   */
  active?: MosaicLabsTab;
}) {
  return (
    <nav className="mosaic-labs-tabs" aria-label="Playground lenses">
      <div>
        <Link
          aria-current={active === "retrieval" ? "page" : undefined}
          className={active === "retrieval" ? "active" : ""}
          href={RETRIEVAL_SURFACE.path}
        >
          Hybrid retrieval
        </Link>
        <Link
          aria-current={active === "hnsw" ? "page" : undefined}
          className={active === "hnsw" ? "active" : ""}
          href="/mosaic-labs/hnsw"
        >
          Scale & HNSW
        </Link>
        <Link
          aria-current={active === "memory" ? "page" : undefined}
          className={active === "memory" ? "active" : ""}
          href="/mosaic-labs/memory"
        >
          Session & Memory
        </Link>
      </div>
      <small>
        Behind the results
      </small>
      <a
        aria-label="View Mosaic source on GitHub (opens in a new tab)"
        className="mosaic-labs-source"
        href={sourceRepositoryUrl}
        rel="noreferrer"
        target="_blank"
      >
        <img
          alt=""
          aria-hidden="true"
          height="16"
          src="/assets/icons/github-mark.svg"
          width="16"
        />
        GitHub
      </a>
    </nav>
  );
}
