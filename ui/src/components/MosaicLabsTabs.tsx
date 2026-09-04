import { Projector } from "lucide-react";
import { Link } from "wouter";
import { RETRIEVAL_SURFACE } from "../navigation";

type MosaicLabsTab = "retrieval" | "hnsw";

const sourceRepositoryUrl =
  "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql";

/**
 * The Playground's own lens strip, secondary to `Discover | Shop | Playground`.
 *
 * It used to read "Retrieval Observatory / HNSW at scale / Studio" over the line
 * "Optional read-only views", which put a second name for the surface and a
 * second information architecture on the same screen as the header.
 *
 * Two entries now, not three. The strip's job is to say where the required work
 * happens and what is optional beyond it, and `Catalog studio` is neither: it
 * runs no retrieval, grades no lab, and reading it as a third peer of the
 * Playground implied a fourth thing to get through in a 45-minute budget. Its
 * route and its footer link both stay, so nothing is lost from a session that
 * wants it.
 */
export function MosaicLabsTabs({
  active,
  projector,
  onToggleProjector,
}: {
  /**
   * Which entry is current, omitted by a surface that is not one of them.
   * Catalog studio carries the strip so a reader can leave it, and marks
   * nothing: it is no longer a Playground lens.
   */
  active?: MosaicLabsTab;
  /** Whether projector mode is on. Only meaningful with a toggle handler. */
  projector?: boolean;
  /**
   * Turns projector mode on and off. Omitted by surfaces that do not offer it,
   * which is what keeps the control off the two lenses that cannot honour it.
   */
  onToggleProjector?: () => void;
}) {
  return (
    <nav className="mosaic-labs-tabs" aria-label="Playground lenses">
      <div>
        <Link
          aria-current={active === "retrieval" ? "page" : undefined}
          className={active === "retrieval" ? "active" : ""}
          href={RETRIEVAL_SURFACE.path}
        >
          {RETRIEVAL_SURFACE.label}
        </Link>
        <Link
          aria-current={active === "hnsw" ? "page" : undefined}
          className={active === "hnsw" ? "active" : ""}
          href="/mosaic-labs/hnsw"
        >
          Advanced: Vector index at scale
        </Link>
      </div>
      {onToggleProjector ? (
        <button
          aria-pressed={projector ?? false}
          className={
            projector ? "mosaic-labs-projector is-on" : "mosaic-labs-projector"
          }
          onClick={onToggleProjector}
          type="button"
        >
          <Projector aria-hidden="true" size={15} />
          Projector mode
        </button>
      ) : null}
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
