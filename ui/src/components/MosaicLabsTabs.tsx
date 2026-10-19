import { Link } from "wouter";
import { PLAYGROUND_TABS, SOURCE_REPOSITORY_URL } from "../navigation";

type MosaicLabsTab = (typeof PLAYGROUND_TABS)[number]["id"];

/** Shared navigation for how Mosaic searches and remembers. */
export function MosaicLabsTabs({
  active,
}: {
  /** Which entry is current, omitted by a surface that is not one of them. */
  active?: MosaicLabsTab;
}) {
  return (
    <nav className="mosaic-labs-tabs" aria-label="Playground sections">
      <div>
        {PLAYGROUND_TABS.map((tab) => (
          <Link
            key={tab.id}
            aria-current={active === tab.id ? "page" : undefined}
            className={active === tab.id ? "active" : ""}
            href={tab.path}
          >
            {tab.label}
          </Link>
        ))}
      </div>
      <small>
        Behind the results
      </small>
      <a
        aria-label="View Mosaic source on GitHub (opens in a new tab)"
        className="mosaic-labs-source"
        href={SOURCE_REPOSITORY_URL}
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
