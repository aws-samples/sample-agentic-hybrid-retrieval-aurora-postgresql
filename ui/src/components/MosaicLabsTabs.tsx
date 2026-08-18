import { Link } from "wouter";

type MosaicLabsTab = "explore" | "hnsw" | "studio";

const sourceRepositoryUrl =
  "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql";

/**
 * Keeps the optional inspection surfaces separate from participant authoring.
 */
export function MosaicLabsTabs({ active }: { active: MosaicLabsTab }) {
  return (
    <nav className="mosaic-labs-tabs" aria-label="Mosaic Labs views">
      <div>
        <Link
          aria-current={active === "explore" ? "page" : undefined}
          className={active === "explore" ? "active" : ""}
          href="/mosaic-labs"
        >
          Explore
        </Link>
        <Link
          aria-current={active === "hnsw" ? "page" : undefined}
          className={active === "hnsw" ? "active" : ""}
          href="/mosaic-labs/hnsw"
        >
          HNSW at scale
        </Link>
        <Link
          aria-current={active === "studio" ? "page" : undefined}
          className={active === "studio" ? "active" : ""}
          href="/mosaic-labs/studio"
        >
          Studio
        </Link>
      </div>
      <small>
        <strong>Optional read-only views.</strong> Build in Code Editor, then validate in Shop.
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
