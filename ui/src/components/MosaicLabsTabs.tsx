import { Github } from "lucide-react";
import { Link } from "wouter";

type MosaicLabsTab = "explore" | "studio";

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
          aria-current={active === "studio" ? "page" : undefined}
          className={active === "studio" ? "active" : ""}
          href="/mosaic-labs/studio"
        >
          Studio
        </Link>
      </div>
      <small>Read-only views. Build in Code Editor, then validate in Shop.</small>
      <a
        aria-label="View Mosaic source on GitHub (opens in a new tab)"
        className="mosaic-labs-source"
        href={sourceRepositoryUrl}
        rel="noreferrer"
        target="_blank"
      >
        <Github aria-hidden="true" size={16} />
        GitHub
      </a>
    </nav>
  );
}
