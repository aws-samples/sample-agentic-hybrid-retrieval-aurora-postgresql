import { useEffect, useRef } from "react";

/**
 * Decorative particle flow for the Mosaic Labs masthead.
 *
 * This is atmosphere, not instrumentation. It encodes no measurement, no
 * corpus statistic, and no retrieval state: a presenter cannot read a number
 * off it, which is deliberate, because every figure on this surface has to be
 * traceable to a query that actually ran.
 *
 * It stops drawing when it scrolls out of view, when the tab is hidden, and
 * when the machine asks for reduced motion - a workshop room runs this on a
 * projector for forty-five minutes.
 */

type Particle = {
  /** Position along the band, 0 at the left edge and 1 at the right. */
  x: number;
  /** Signed offset from the wave centreline, -1 to 1, scaled by the envelope. */
  spread: number;
  radius: number;
  drift: number;
  band: number;
  /** Per-particle warmth jitter so the field reads as painted, not computed. */
  tint: number;
};

const BANDS = 4;
const PER_BAND = 520;
const CORE_COUNT = 460;
const TWO_PI = Math.PI * 2;
/* Three stops sampled from the surface palette: --maroon-950 at the deep
   core, --maroon-700 through the mid-field, and a warm gold - between
   --gold and --gold-soft - at the outer fringe. The bright central thread
   leans further toward --gold-soft as the field opens toward the right. */
const CORE_DEEP = [43, 13, 19];
const CORE = [126, 36, 49];
const FRINGE = [201, 152, 84];
const HIGHLIGHT = [246, 234, 217];

function mixChannel(a: number[], b: number[], t: number, index: number) {
  return a[index] + (b[index] - a[index]) * Math.min(1, Math.max(0, t));
}

function buildParticles(): Particle[] {
  const particles: Particle[] = [];
  for (let band = 0; band < BANDS; band += 1) {
    for (let index = 0; index < PER_BAND; index += 1) {
      particles.push({
        // The masthead mask handles the copy boundary; the field itself spans
        // the whole canvas so it still reads as one broad flow on projectors.
        x: Math.random(),
        spread: (Math.random() * 2 - 1) * (0.5 + Math.random() ** 2 * 0.5),
        radius: 0.65 + Math.random() ** 2 * 1.45,
        drift: 0.012 + Math.random() * 0.035,
        band,
        tint: (Math.random() * 2 - 1) * 0.08,
      });
    }
  }
  for (let index = 0; index < CORE_COUNT; index += 1) {
    particles.push({
      x: 0.18 + Math.random() ** 0.72 * 0.82,
      spread: (Math.random() * 2 - 1) * 0.16,
      radius: 0.55 + Math.random() ** 2 * 1.1,
      drift: 0.01 + Math.random() * 0.02,
      band: -1,
      tint: Math.random() * 0.3,
    });
  }
  return particles;
}

/** Sparse at the left, opening toward the right, as in the reference frame. */
function envelope(x: number) {
  return 0.28 + x ** 1.2 * 0.92;
}

function centreline(x: number, phase: number, band: number, height: number) {
  const bandPhase = phase + band * 0.42;
  const primary = Math.sin(x * TWO_PI * 1.15 + bandPhase);
  const secondary = Math.sin(x * TWO_PI * 2.3 + bandPhase * 1.7) * 0.22;
  return height * 0.5 + (primary + secondary) * height * 0.25;
}

function paint(
  ctx: CanvasRenderingContext2D,
  particles: Particle[],
  width: number,
  height: number,
  phase: number,
) {
  ctx.clearRect(0, 0, width, height);
  for (const particle of particles) {
    const spread = particle.spread * envelope(particle.x);
    const y = centreline(particle.x, phase, Math.max(particle.band, 0), height)
      + spread * height * 0.36;
    const distance = Math.min(1, Math.abs(spread) / 0.55);
    const alpha = (particle.band < 0 ? 0.58 : 0.5) * (1 - distance * 0.66)
      * (0.25 + envelope(particle.x) * 0.75);
    const channel = (index: number) => {
      if (particle.band < 0) {
        // The bright core thread warms toward the highlight as the field
        // opens up on the right, instead of sitting at one flat tone.
        const warmth = Math.min(1, particle.tint + envelope(particle.x) * 0.55);
        return Math.round(mixChannel(CORE, HIGHLIGHT, warmth, index));
      }
      const mix = Math.min(1, Math.max(0, distance + particle.tint));
      const value = mix < 0.5
        ? mixChannel(CORE_DEEP, CORE, mix * 2, index)
        : mixChannel(CORE, FRINGE, (mix - 0.5) * 2, index);
      return Math.round(value);
    };
    ctx.fillStyle =
      `rgb(${channel(0)} ${channel(1)} ${channel(2)} / ${alpha.toFixed(3)})`;
    ctx.beginPath();
    ctx.arc(particle.x * width, y, particle.radius, 0, TWO_PI);
    ctx.fill();
  }
}

export function LabsIntroFlow() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const particles = buildParticles();
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let width = 0;
    let height = 0;
    let phase = 0;
    let frame = 0;
    let visible = true;
    let last = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const box = canvas.getBoundingClientRect();
      width = Math.max(1, Math.round(box.width));
      height = Math.max(1, Math.round(box.height));
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      paint(ctx, particles, width, height, phase);
    };

    const step = (now: number) => {
      const elapsed = last ? Math.min(now - last, 64) : 16;
      last = now;
      phase += elapsed * 0.00021;
      for (const particle of particles) {
        particle.x += particle.drift * (elapsed / 1000);
        if (particle.x > 1.04) particle.x -= 1.08;
      }
      paint(ctx, particles, width, height, phase);
      frame = window.requestAnimationFrame(step);
    };

    const run = () => {
      if (still || frame || !visible || document.hidden) return;
      last = 0;
      frame = window.requestAnimationFrame(step);
    };
    const halt = () => {
      if (!frame) return;
      window.cancelAnimationFrame(frame);
      frame = 0;
    };

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    const seen = new IntersectionObserver((entries) => {
      visible = entries.some((entry) => entry.isIntersecting);
      if (visible) run();
      else halt();
    });
    seen.observe(canvas);
    const onVisibility = () => (document.hidden ? halt() : run());
    document.addEventListener("visibilitychange", onVisibility);

    resize();
    run();
    return () => {
      halt();
      observer.disconnect();
      seen.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div className="labs-intro-flow" aria-hidden="true">
      <canvas ref={canvasRef} />
    </div>
  );
}
