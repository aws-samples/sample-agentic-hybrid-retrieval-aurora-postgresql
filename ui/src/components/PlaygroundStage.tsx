import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

/**
 * The Playground's three numbered stages, and the one disclosure primitive
 * everything deep hides behind.
 *
 * `Retrieve -> Rank -> Reason` is the workshop's model, so the numbers carry
 * information rather than decorating a list: a participant reads them as the
 * order the pipeline runs in and as the order the three labs run in. That is the
 * only place on any surface where numbered sections are used.
 *
 * Everything a participant needs to answer "what happened" is in the open. SQL,
 * candidate rows, the fusion arithmetic, EXPLAIN output, the persisted event, the
 * evidence records and the tool contracts are one click below it, because all
 * seven at once is a wall rather than a proof.
 */

export function PlaygroundStage({
  number,
  title,
  summary,
  status,
  stale = false,
  children,
}: {
  number: string;
  title: string;
  summary: string;
  /** A measured one-line verdict, rendered beside the heading. */
  status?: ReactNode;
  /**
   * A newer run is in flight and everything below is the previous one.
   *
   * Pressing Run a second time does not clear the response — deliberately, because
   * blanking a populated page on every re-run loses the comparison the surface
   * exists to support. But an unmarked page then presents last run's numbers as
   * this run's, which is the same class of error as a mid-flight "authorization
   * failed": the figures are real and the tense is wrong.
   */
  stale?: boolean;
  children: ReactNode;
}) {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <section
      className={stale ? "labs-stage is-stale" : "labs-stage"}
      aria-labelledby={`labs-stage-${slug}`}
    >
      <header className="labs-stage-head">
        <span className="labs-stage-number" aria-hidden="true">{number}</span>
        <div className="labs-stage-copy">
          <h2 id={`labs-stage-${slug}`}>{title}</h2>
          <p>{summary}</p>
        </div>
        {status ? <div className="labs-stage-status">{status}</div> : null}
      </header>
      {stale ? (
        <p className="labs-stage-stale" role="status">
          A new run is in flight. Everything below is the previous run until it
          lands.
        </p>
      ) : null}
      <div className="labs-stage-body" aria-busy={stale || undefined}>
        {children}
      </div>
    </section>
  );
}

/**
 * One collapsed detail.
 *
 * `<details>` rather than a controlled panel: it keeps keyboard behavior, works
 * before hydration, and prints expanded. `hint` is what the reader gets before
 * opening it, which is what stops seven identical "View ..." rows from being a
 * guessing game.
 */
export function PlaygroundDisclosure({
  label,
  hint,
  children,
  onOpen,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  /** Fired the first time the reader opens it, for a lazy fetch. */
  onOpen?: () => void;
}) {
  return (
    <details
      className="labs-disclosure"
      onToggle={(event) => {
        if (event.currentTarget.open) onOpen?.();
      }}
    >
      <summary>
        <span>{label}</span>
        {hint ? <small>{hint}</small> : null}
        <ChevronDown aria-hidden="true" size={15} />
      </summary>
      <div className="labs-disclosure-body">{children}</div>
    </details>
  );
}

/** A row of disclosures under a stage, so the seven of them read as one shelf. */
export function PlaygroundDisclosureShelf({ children }: { children: ReactNode }) {
  return <div className="labs-disclosure-shelf">{children}</div>;
}

/**
 * What a stage is about to show, before it has anything to show.
 *
 * A stage with no run behind it printed one grey sentence in a lot of empty canvas,
 * which reads as broken rather than as waiting. This draws the shape instead: the
 * steps in order, in the same words the populated stage will use, with no numbers,
 * no zeroes and no dashes anywhere. A participant learns what they are about to
 * inspect, and nothing on screen can be mistaken for a measurement.
 *
 * Deliberately not a skeleton loader. Shimmering grey blocks imply data is arriving;
 * nothing is arriving until the participant presses Run.
 */
export function PlaygroundDormant({
  steps,
  hint,
}: {
  steps: string[];
  hint: string;
}) {
  return (
    <div className="labs-dormant" role="status">
      <ol aria-label="What this stage will show">
        {steps.map((step) => <li key={step}>{step}</li>)}
      </ol>
      <p>{hint}</p>
    </div>
  );
}

/**
 * One measured figure. `value` is always something the run reported; there is no
 * placeholder branch, because a dash that looks like a measurement is worse than
 * an absent panel.
 */
export function PlaygroundFigure({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: "plain" | "good" | "warn";
}) {
  return (
    <div className={tone && tone !== "plain" ? `labs-figure is-${tone}` : "labs-figure"}>
      <dt>{label}</dt>
      <dd>{value}</dd>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

export function PlaygroundFigures({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <dl className="labs-figures" aria-label={label}>
      {children}
    </dl>
  );
}
