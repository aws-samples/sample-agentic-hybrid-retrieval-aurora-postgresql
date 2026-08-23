import { Link } from "wouter";
import { RETRIEVAL_SURFACE } from "../navigation";

type MosaicLabsTab = "retrieval" | "hnsw" | "studio";

const sourceRepositoryUrl =
  "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql";

/**
 * The Playground's own lens strip, secondary to `Discover | Shop | Playground`.
 *
 * It used to read "Retrieval Observatory / HNSW at scale / Studio" over the line
 * "Optional read-only views", which put a second name for the surface and a
 * second information architecture on the same screen as the header. The three
 * entries are lenses on one surface now, and the note says what they are for
 * rather than how little they matter.
 */
export function MosaicLabsTabs({ active }: { active: MosaicLabsTab }) {
  return (
    <nav className="mosaic-labs-tabs" aria-label="Playground lenses">
      <div>
        <Link
          aria-current={active === "retrieval" ? "page" : undefined}
          className={active === "retrieval" ? "active" : ""}
          href={RETRIEVAL_SURFACE.path}
        >
          Retrieve, rank, reason
        </Link>
        <Link
          aria-current={active === "hnsw" ? "page" : undefined}
          className={active === "hnsw" ? "active" : ""}
          href="/mosaic-labs/hnsw"
        >
          Vector index at scale
        </Link>
        <Link
          aria-current={active === "studio" ? "page" : undefined}
          className={active === "studio" ? "active" : ""}
          href="/mosaic-labs/studio"
        >
          Catalog studio
        </Link>
      </div>
      <small>
        <strong>Read-only.</strong> Build in Code Editor, then prove it here.
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
