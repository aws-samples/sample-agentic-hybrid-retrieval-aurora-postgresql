import { ArrowRight, Pause, Play, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "wouter";
import { editorialStories, storyHref } from "../discoverContent";
import "../workspace-walkthrough.css";

const STEP_DURATION_MS = 4_000;
const beforeImage = "/assets/images/mosaic/alex-workspace-before.jpg";
const visionImage = "/assets/images/mosaic/alex-workspace-after.jpg";

const guidance: Record<string, { title: string; detail: string; action: string; focus: string }> = {
  Headphones: {
    title: "Help him be heard.",
    detail: "Search for clearer calls, then check the microphone details in the results.",
    action: "Find headphones",
    focus: "headphones",
  },
  Chairs: {
    title: "Make long days comfortable.",
    detail: "Compare chairs for the support Alex needs. Open the details to see what makes one a better fit.",
    action: "Compare chairs",
    focus: "chair",
  },
  Monitors: {
    title: "Put code and docs side by side.",
    detail: "Find a monitor with room for both. Ask Mosaic to explain the options using specifications and reviews.",
    action: "Explore monitors",
    focus: "monitors",
  },
};

function prefersReducedMotion() {
  return typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** A single, interruptible introduction; the illustration never represents a purchase. */
export function WorkspaceWalkthrough({ real }: { real: boolean }) {
  const needs = editorialStories.map(story => ({
    label: story.topic,
    ...guidance[story.topic],
    href: storyHref(story, real),
  }));
  const steps = [
    {
      label: "Starting point", title: "Desk. Laptop. A place to start.",
      detail: "Alex has the basics. Help him choose the three pieces that make the room work for him.",
      focus: "", action: "", href: "",
    },
    ...needs,
    {
      label: "The vision", title: "Now, help Alex make it his.",
      detail: "Find a match, compare the details, then ask Mosaic to explain the choice. Start with his headphones.",
      focus: "", action: "Start with clearer calls", href: needs[0].href,
    },
  ];
  const [step, setStep] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);
  const [playing, setPlaying] = useState(() => !prefersReducedMotion());
  const [inView, setInView] = useState(false);
  const [imageInView, setImageInView] = useState(false);
  const [pageVisible, setPageVisible] = useState(() => !document.hidden);
  const [visionLoaded, setVisionLoaded] = useState(false);
  const captionRef = useRef<HTMLElement>(null);
  const imageRef = useRef<HTMLDivElement>(null);
  const visionRef = useRef<HTMLImageElement>(null);
  const lastStep = steps.length - 1;
  const current = steps[step];
  const advancing = playing && inView && imageInView && pageVisible && !reducedMotion && visionLoaded && step < lastStep;

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const updateMotion = () => {
      setReducedMotion(media?.matches ?? false);
      if (media?.matches) setPlaying(false);
    };
    const updateVisibility = () => setPageVisible(!document.hidden);
    media?.addEventListener("change", updateMotion);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => {
      media?.removeEventListener("change", updateMotion);
      document.removeEventListener("visibilitychange", updateVisibility);
    };
  }, []);

  useEffect(() => {
    if (visionRef.current?.complete && visionRef.current.naturalWidth > 0) setVisionLoaded(true);
    // The room and its explanation need to be visible together before advancing.
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        const visible = entry.isIntersecting && entry.intersectionRatio >= .6;
        if (entry.target === captionRef.current) setInView(visible);
        if (entry.target === imageRef.current) setImageInView(visible);
      }
    }, { threshold: [.6] });
    if (captionRef.current) observer.observe(captionRef.current);
    if (imageRef.current) observer.observe(imageRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!advancing) return;
    const timer = window.setTimeout(() => {
      setStep(step + 1);
      if (step + 1 === lastStep) setPlaying(false);
    }, STEP_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [advancing, lastStep, step]);

  function advanceStep() {
    const replay = step === lastStep;
    setPlaying(replay && !reducedMotion);
    setStep(replay ? 0 : step + 1);
  }

  return (
    <figure
      className="discover-hero-photo workspace-walkthrough"
      aria-label="Alex’s workspace walkthrough"
      onFocusCapture={event => {
        if (!(event.target as HTMLElement).closest("[data-playback-control]")) setPlaying(false);
      }}
    >
      <div ref={imageRef} id="alex-workspace-image" className="discover-hero-image workspace-tour-image">
        <img
          src={beforeImage}
          alt="Alex’s starting point: a laptop on an oak standing desk, ready for a chair, monitor and headphones"
          aria-hidden={step !== 0}
          width={1712} height={1152} fetchPriority="high"
        />
        <img
          ref={visionRef}
          className="workspace-tour-vision"
          src={visionImage}
          alt="The vision for Alex’s workspace: the same desk with a mesh chair on wheels, two monitors and headphones"
          aria-hidden={step === 0}
          data-visible={step > 0}
          width={1168} height={784} fetchPriority="low"
          onLoad={() => setVisionLoaded(true)}
        />
        <svg className="workspace-tour-focus" viewBox="0 0 1168 784" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <g data-active={current.focus === "headphones"}>
            <ellipse cx="709" cy="394" rx="63" ry="36" />
            <circle className="workspace-tour-pin" cx="770" cy="361" r="20" />
            <text x="770" y="362">1</text>
          </g>
          <g data-active={current.focus === "chair"}>
            <rect x="230" y="243" width="312" height="506" rx="28" />
            <circle className="workspace-tour-pin" cx="532" cy="256" r="20" />
            <text x="532" y="257">2</text>
          </g>
          <g data-active={current.focus === "monitors"}>
            <rect x="543" y="201" width="363" height="154" rx="18" />
            <circle className="workspace-tour-pin" cx="903" cy="214" r="20" />
            <text x="903" y="215">3</text>
          </g>
        </svg>
        <span className="workspace-tour-scene-label">{step === 0 ? "The starting point" : "The room Alex is working toward"}</span>
      </div>
      <figcaption ref={captionRef}>
        <div className="workspace-tour-heading">
          <span>Your home office, coming together.</span>
          <span className="workspace-tour-count" aria-label={`Step ${step + 1} of ${steps.length}`}>{step + 1} / {steps.length}</span>
        </div>
        <div className="workspace-tour-copy" aria-live={playing ? "off" : "polite"} aria-atomic="true">
          <h2>{current.title}</h2>
          <p>{current.detail}</p>
        </div>
        <div className="workspace-tour-actions">
          {current.href ? <Link className="workspace-tour-action" href={current.href}>{current.action}</Link>
            : <span className="workspace-tour-hint">Follow Alex’s three needs.</span>}
          <div className="workspace-tour-controls">
            {!reducedMotion && step < lastStep ? (
              <button type="button" data-playback-control aria-label={playing ? "Pause walkthrough" : "Play walkthrough"} onClick={() => setPlaying(value => !value)}>
                {playing ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
                <span>{playing ? "Pause" : "Play"}</span>
              </button>
            ) : null}
            <button className="workspace-tour-next" type="button" aria-controls="alex-workspace-image" onClick={advanceStep}>
              {step === lastStep ? <><RotateCcw size={14} aria-hidden="true" /> Replay</> : <>Next <ArrowRight size={15} aria-hidden="true" /></>}
            </button>
          </div>
        </div>
        <div className="workspace-tour-steps" aria-hidden="true">
          {steps.map((item, index) => (
            <span key={item.label} data-reached={index <= step} data-current={index === step} />
          ))}
        </div>
      </figcaption>
    </figure>
  );
}
