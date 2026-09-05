import { Menu, ShoppingBag, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "wouter";
import { api } from "../api";
import { useCommerce } from "../commerce";
import { coreMosaicLabs } from "../labMissions";
import {
  RETRIEVAL_SURFACE,
  forwardedSearchEvent,
  forwardedSearchFilters,
  playgroundQueryHref,
  useSearchParams,
} from "../navigation";
import type { LabDatabaseState, LabStateRecord } from "../types";
import { CodeEditorLink } from "./CodeEditorLink";
import { MosaicMark } from "./MosaicMark";

/**
 * `not_applicable` is a sentence, not an enum member, once it reaches a chip.
 *
 * Lab 3's seam lives in the API process, so there is no schema to re-apply and
 * no stale cluster to warn about. Printing the wire value would read as a fourth
 * verdict on the repair.
 */
const databaseLabels: Record<LabDatabaseState, string> = {
  applied: "applied",
  stale: "stale",
  not_applicable: "not applicable",
};

/**
 * What the header says when it does not know.
 *
 * A failed `/api/labs/state` read says nothing about the participant's work, and
 * printing `broken` on the strength of one would send someone to edit SQL that
 * was never the problem.
 */
const NOT_CHECKED = "not checked";

/**
 * Which lab the header is reporting on.
 *
 * `mission` is what Shop and Ask Mosaic carry; `example` is what the Playground
 * carries. Both name a scenario id, and only the three core labs have a lab
 * number, so a supporting check or an unknown id falls back to Lab 1 rather than
 * blanking the readout. Lab 1 is also the honest cold-start default: it is where
 * the session begins.
 */
function activeLabNumber(params: URLSearchParams): number {
  const named = params.get("mission") ?? params.get("example") ?? "";
  const index = coreMosaicLabs.findIndex((mission) => mission.id === named);
  return index >= 0 ? index + 1 : 1;
}

/**
 * The one storefront header.
 *
 * Discover used to draw its own copy of this, and the two drifted: the landing
 * showed a serif title-case wordmark at 74px tall, every other surface showed an
 * uppercase sans wordmark at 72px. The reference boards carry one header across
 * all three panels, so there is one component and one rule block.
 */
/**
 * Discover, Shop, Playground. Desire, decide, understand.
 *
 * Three entries and nothing else: the third used to print "Observatory" with an
 * "Optional" badge clipped to it, which spent the only spare line in the header
 * telling participants the surface did not matter.
 */
const navLinks = [
  { to: "/", label: "Discover" },
  { to: "/catalog", label: "Shop" },
  { to: RETRIEVAL_SURFACE.path, label: RETRIEVAL_SURFACE.label },
];

function isActive(pathname: string, to: string) {
  if (to === "/") return pathname === "/" || pathname === "/discover";
  if (to === "/catalog") {
    return (
      pathname.startsWith("/catalog")
      || pathname.startsWith("/search")
      || pathname.startsWith("/products/")
    );
  }
  // The Playground's other two lenses still live under their own paths, and the
  // nav entry has to stay lit on them or the header would report the participant
  // is nowhere.
  if (to === RETRIEVAL_SURFACE.path) {
    return pathname.startsWith(to) || pathname.startsWith("/mosaic-labs");
  }
  return pathname.startsWith(to);
}

export function SiteHeader({ inert = false }: { inert?: boolean }) {
  const [open, setOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const navigationRef = useRef<HTMLElement | null>(null);
  const { itemCount, openCart } = useCommerce();
  const [location] = useLocation();
  const [searchParams] = useSearchParams();
  const [codeEditorUrl, setCodeEditorUrl] = useState<string | null>(null);
  /** `null` until the first read settles, so the header never flashes a verdict
   * it has not read. */
  const [labs, setLabs] = useState<LabStateRecord[] | null>(null);
  const pathname = location.split("?")[0];
  const labNumber = activeLabNumber(searchParams);
  /**
   * Null covers both "the read failed" and "the service does not know this lab".
   * Both mean the header has not read a verdict, and both print `not checked`.
   */
  const activeLab = labs?.find((lab) => lab.lab_id === labNumber) ?? null;
  const close = () => setOpen(false);
  /**
   * The Playground entry carries the shopper's current Shop request with it.
   *
   * The only other way to hand a query over is a link inside Shop's collapsed
   * "Why these results" disclosure, so a participant who searched and then reached
   * for the header arrived at a Playground about a different query — three separate
   * demonstrations rather than one request travelling through the product. Nothing
   * is carried when Shop has no active search, and the Playground says out loud when
   * something was.
   *
   * The run Shop actually served travels too, on the `event` Shop records on its
   * own URL. Without it this path would re-run the query and mint a second
   * event, which is the one thing the hand-off exists to avoid.
   */
  const playgroundHref = useMemo(() => {
    // wouter's useLocation returns the path without the query string, so the search
    // has to come from its own hook.
    if (!pathname.startsWith("/catalog")) return RETRIEVAL_SURFACE.path;
    const query = searchParams.get("q")?.trim();
    if (!query) return RETRIEVAL_SURFACE.path;
    return playgroundQueryHref(
      query,
      forwardedSearchFilters(searchParams),
      forwardedSearchEvent(searchParams),
    );
  }, [pathname, searchParams]);

  /**
   * The Code Editor origin, read from `/api/health` rather than from readiness.
   *
   * Health answers from process configuration and never touches Aurora, so the
   * button is there on a workshop machine whose database is still seeding, which
   * is exactly when a participant needs to open a file.
   */
  useEffect(() => {
    let active = true;
    api.health().then(
      (health) => {
        if (active) setCodeEditorUrl(health.code_editor_url ?? null);
      },
      () => {
        if (active) setCodeEditorUrl(null);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  /**
   * Re-read when the participant moves between labs.
   *
   * `/api/labs/state` runs no retrieval: it reads the marker blocks in the file
   * the participant edits and asks Aurora what two functions currently contain.
   * Navigating to another lab is also the moment a repair made in between
   * becomes worth re-reporting, so that navigation is the refresh.
   */
  useEffect(() => {
    let active = true;
    api.labsState().then(
      (state) => {
        if (active) setLabs(state.labs);
      },
      () => {
        if (active) setLabs([]);
      },
    );
    return () => {
      active = false;
    };
  }, [labNumber]);

  useEffect(() => {
    if (!open) return undefined;
    const frame = window.requestAnimationFrame(() => {
      navigationRef.current?.querySelector<HTMLElement>("a")?.focus();
    });
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      menuButtonRef.current?.focus();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <header
      className="site-header"
      inert={inert || undefined}
      aria-hidden={inert || undefined}
    >
      <Link className="site-brand" href="/" onClick={close} aria-label="Mosaic home">
        <MosaicMark />
        <strong>Mosaic</strong>
      </Link>

      <nav
        ref={navigationRef}
        id="storefront-navigation"
        className={open ? "site-nav open" : "site-nav"}
        aria-label="Storefront"
      >
        {navLinks.map(({ to, label }) => (
          <Link
            key={to}
            href={to === RETRIEVAL_SURFACE.path ? playgroundHref : to}
            className={isActive(pathname, to) ? "active" : ""}
            aria-current={isActive(pathname, to) ? "page" : undefined}
            onClick={close}
          >
            <span>{label}</span>
          </Link>
        ))}
      </nav>

      <div className="site-actions">
        {labs ? (
          <div
            className="site-lab-state"
            role="status"
            aria-label={`Lab ${labNumber} state`}
          >
            <span className="site-lab-chip" data-state={activeLab?.source_state ?? "unchecked"}>
              source: {activeLab ? activeLab.source_state : NOT_CHECKED}
            </span>
            <span
              className="site-lab-chip"
              data-state={activeLab?.database_state ?? "unchecked"}
            >
              database: {activeLab ? databaseLabels[activeLab.database_state] : NOT_CHECKED}
            </span>
          </div>
        ) : null}
        <CodeEditorLink href={codeEditorUrl} className="site-code-editor" />
        <button
          className="site-icon site-bag"
          type="button"
          aria-label={`Bag, ${itemCount} ${itemCount === 1 ? "item" : "items"}`}
          data-cart-target
          onClick={openCart}
        >
          <ShoppingBag size={17} />
          {itemCount ? (
            <span className="bag-count">{itemCount > 99 ? "99+" : itemCount}</span>
          ) : null}
        </button>
        <button
          ref={menuButtonRef}
          className="site-icon site-menu"
          type="button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          aria-controls="storefront-navigation"
          onClick={() => setOpen((current) => !current)}
        >
          {open ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>
    </header>
  );
}
