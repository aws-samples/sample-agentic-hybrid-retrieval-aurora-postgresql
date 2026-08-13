import { Link } from "wouter";

type MosaicLabsTab = "workshop" | "studio";

/**
 * Keeps optional exploration separate from the three required workshop labs.
 */
export function MosaicLabsTabs({ active }: { active: MosaicLabsTab }) {
  return (
    <nav className="mosaic-labs-tabs" aria-label="Mosaic Labs views">
      <div>
        <Link
          aria-current={active === "workshop" ? "page" : undefined}
          className={active === "workshop" ? "active" : ""}
          href="/mosaic-labs"
        >
          Workshop
        </Link>
        <Link
          aria-current={active === "studio" ? "page" : undefined}
          className={active === "studio" ? "active" : ""}
          href="/mosaic-labs/studio"
        >
          Studio
        </Link>
      </div>
      <small>Studio is optional and outside the three-lab session path.</small>
    </nav>
  );
}
