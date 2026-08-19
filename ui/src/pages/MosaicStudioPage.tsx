import { ArrowRight, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { formatPrice } from "../format";
import { productImage } from "../media";
import { STUDIO_BRIEFS, studioCandidates } from "../studioFixtures";

const TOUR_DWELL_MS = 3200;

/**
 * An optional, fixture-backed visual composition study.
 *
 * Studio intentionally does not execute or emulate a search. It is a fast way
 * to explore real catalog objects as a composition after attendees have
 * experienced the live retrieval system in Shop.
 */
export function MosaicStudioPage() {
  const [activeBriefId, setActiveBriefId] = useState(STUDIO_BRIEFS[0].id);
  const [assembled, setAssembled] = useState(false);
  const [candidateIndexes, setCandidateIndexes] = useState<number[]>(
    STUDIO_BRIEFS[0].zones.map(() => 0),
  );
  const [isTouring, setIsTouring] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(
    () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
  );
  const [tourStep, setTourStep] = useState(0);
  const [tourCycle, setTourCycle] = useState(0);
  const tourTimer = useRef<number | null>(null);
  const activeBrief = useMemo(
    () => STUDIO_BRIEFS.find((brief) => brief.id === activeBriefId) ?? STUDIO_BRIEFS[0],
    [activeBriefId],
  );
  const candidateSets = activeBrief.zones.map(studioCandidates);
  const pieces = candidateSets.map(
    (candidates, index) => candidates[candidateIndexes[index] ?? 0] ?? candidates[0],
  );

  useEffect(() => () => {
    if (tourTimer.current !== null) window.clearTimeout(tourTimer.current);
  }, []);

  useEffect(() => {
    const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!preference) return;
    const handleChange = (event: MediaQueryListEvent) => {
      setReduceMotion(event.matches);
      if (event.matches) setIsTouring(false);
    };
    preference.addEventListener("change", handleChange);
    return () => preference.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (tourTimer.current !== null) {
      window.clearTimeout(tourTimer.current);
      tourTimer.current = null;
    }
    if (!isTouring) return;

    setAssembled(true);
    tourTimer.current = window.setTimeout(() => {
      const nextStep = (tourStep + 1) % STUDIO_BRIEFS.length;
      const nextBrief = STUDIO_BRIEFS[nextStep];
      setTourStep(nextStep);
      setActiveBriefId(nextBrief.id);
      setCandidateIndexes(nextBrief.zones.map(() => 0));
      setTourCycle((current) => current + 1);
    }, TOUR_DWELL_MS);

    return () => {
      if (tourTimer.current !== null) {
        window.clearTimeout(tourTimer.current);
        tourTimer.current = null;
      }
    };
  }, [isTouring, tourStep]);

  const chooseBrief = (briefId: string) => {
    const nextBrief = STUDIO_BRIEFS.find((brief) => brief.id === briefId) ?? STUDIO_BRIEFS[0];
    setIsTouring(false);
    setAssembled(false);
    setTourStep(STUDIO_BRIEFS.indexOf(nextBrief));
    setActiveBriefId(nextBrief.id);
    setCandidateIndexes(nextBrief.zones.map(() => 0));
  };

  const startTour = () => {
    if (reduceMotion) return;
    setTourStep(0);
    setActiveBriefId(STUDIO_BRIEFS[0].id);
    setCandidateIndexes(STUDIO_BRIEFS[0].zones.map(() => 0));
    setTourCycle((current) => current + 1);
    setIsTouring(true);
  };

  const toggleAssembly = () => {
    setIsTouring(false);
    setAssembled((current) => !current);
  };

  const cycleCandidate = (zoneIndex: number) => {
    const candidates = candidateSets[zoneIndex];
    if (candidates.length < 2) return;
    setIsTouring(false);
    setCandidateIndexes((current) =>
      current.map((candidateIndex, index) =>
        index === zoneIndex ? (candidateIndex + 1) % candidates.length : candidateIndex,
      ),
    );
  };

  return (
    <div className="page mosaic-labs-page labs-premium mosaic-studio-page">
      <MosaicLabsTabs active="studio" />

      <MosaicLabsMasthead
        deck="Explore a fast visual study made from real Mosaic catalog products. The language below is a creative brief, not an executed search."
        supportingText="A visual fixture, not a recommendation. Live hybrid retrieval remains in Shop."
        title="Compose a creative workspace."
      />

      <section className="mosaic-studio-briefs" aria-labelledby="studio-briefs-title">
        <div>
          <h2 id="studio-briefs-title">Set a direction</h2>
          <span>Every brief has preselected catalog alternatives, ready to compose instantly.</span>
        </div>
        <div aria-label="Studio brief options" role="group">
          {STUDIO_BRIEFS.map((brief) => (
            <button
              aria-pressed={brief.id === activeBrief.id}
              key={brief.id}
              onClick={() => chooseBrief(brief.id)}
              type="button"
            >
              {brief.label}
            </button>
          ))}
        </div>
      </section>

      <section className="discover-studio" aria-labelledby="mosaic-studio-title">
        <div className="discover-studio-copy">
          <p>Mosaic Studio</p>
          <h2 id="mosaic-studio-title">{activeBrief.title}</h2>
          <span>{activeBrief.description}</span>
          <p className="discover-studio-brief">
            Real catalog objects, curated as a composition study rather than a recommendation.
          </p>
          <div className="discover-studio-actions">
            <button type="button" onClick={toggleAssembly}>
              <Sparkles size={15} aria-hidden="true" />
              {assembled ? "Reset the studio" : "Assemble the studio"}
            </button>
            {!reduceMotion ? (
              <button
                className="discover-studio-tour"
                onClick={isTouring ? () => setIsTouring(false) : startTour}
                type="button"
              >
                <RefreshCw size={15} aria-hidden="true" />
                {isTouring ? "Stop studio tour" : "Play studio tour"}
              </button>
            ) : null}
          </div>
        </div>

        <div
          className={
            assembled
              ? `discover-studio-canvas assembled${isTouring ? " touring" : ""}`
              : "discover-studio-canvas"
          }
          aria-live={isTouring ? "off" : "polite"}
        >
          <span className="discover-studio-grid" aria-hidden="true" />
          <span className="discover-studio-orbit discover-studio-orbit-one" aria-hidden="true" />
          <span className="discover-studio-orbit discover-studio-orbit-two" aria-hidden="true" />
          <span className="discover-studio-route discover-studio-route-one" aria-hidden="true" />
          <span className="discover-studio-route discover-studio-route-two" aria-hidden="true" />
          {activeBrief.zones.map((zoneSpec, index) => {
            const candidates = candidateSets[index];
            const candidateIndex = candidateIndexes[index] ?? 0;
            const product = pieces[index];
            return assembled ? (
              <article
                className={`discover-studio-piece ${zoneSpec.className}`}
                key={`${activeBrief.id}-${product.product_id}-${tourCycle}`}
              >
                <Link
                  aria-label={`Open ${product.title}`}
                  href={`/products/${product.product_id}`}
                >
                  <span className="discover-studio-piece-image">
                    <img
                      src={productImage(product)}
                      alt={product.title}
                      width={1200}
                      height={800}
                      loading="lazy"
                      decoding="async"
                    />
                  </span>
                  <span>
                    <small>{zoneSpec.zone}</small>
                    <strong>{product.model}</strong>
                    <em>{formatPrice(product.price_cents, product.currency)}</em>
                  </span>
                </Link>
                <span className="discover-studio-candidate-count">
                  Curated piece {candidateIndex + 1} of {candidates.length}
                </span>
                <button
                  aria-label={`Try another ${zoneSpec.zone}`}
                  disabled={candidates.length < 2}
                  onClick={() => cycleCandidate(index)}
                  type="button"
                >
                  <RefreshCw size={13} aria-hidden="true" />
                  <span>Try another</span>
                </button>
              </article>
            ) : (
              <span className={`discover-studio-placeholder ${zoneSpec.className}`} key={zoneSpec.zone} />
            );
          })}
          <span className="discover-studio-state">
            {assembled ? "Studio assembled" : "Three curated sets ready"}
          </span>
        </div>
      </section>

      <section className="mosaic-studio-queries" aria-label="Creative composition briefs">
        <p>
          {assembled
            ? "Rotate a zone to view another curated catalog piece:"
            : "The current fixture uses these creative briefs:"}
        </p>
        <ul>
          {activeBrief.zones.map((zoneSpec, index) => (
            <li key={zoneSpec.zone}>
              <small>{zoneSpec.zone}</small>
              <code>{zoneSpec.brief}</code>
              {assembled ? (
                <span>
                  {(candidateIndexes[index] ?? 0) + 1} / {candidateSets[index].length}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <section className="mosaic-studio-boundary" aria-label="Studio scope">
        <div>
          <span>What this shows</span>
          <strong>Real catalog objects arranged from a fixed, inspectable fixture.</strong>
        </div>
        <div>
          <span>What it does not claim</span>
          <strong>Live retrieval, cross-item compatibility, bundle ranking, or agent-composed reasoning.</strong>
        </div>
        <Link href="/labs/retrieval">
          Inspect the retrieval system <ArrowRight size={15} />
        </Link>
      </section>
    </div>
  );
}
