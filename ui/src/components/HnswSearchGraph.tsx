import { Headphones, Minus, Pause, Play, Plus, RotateCcw, RotateCw } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { graphCandidates, graphLayers, graphLinks, graphProducts, graphSteps, graphTourDuration } from "../hnswGraph";
import { mosaicLabManifest } from "../labMissions";
import type { mountHnswScene } from "../hnswScene";
import "../hnsw-search-graph.css";

function FlatGraph({ step }: { step: number }) {
  return <svg className="hnsw-flat-graph" viewBox="0 0 600 360" role="img" aria-label="Flat view of the HNSW layers">
    {graphLayers.map((layer, index) => <g key={layer.label}>
      <text x={16} y={index * 110 + 22}>{layer.label}</text>
      {graphLinks(layer).map(([a, b]) => {
        const first = graphProducts.find((item) => item.id === a)!;
        const second = graphProducts.find((item) => item.id === b)!;
        return <line key={`${a}-${b}`} x1={300 + first.x * 46} y1={index * 110 + 60 + first.z * 9} x2={300 + second.x * 46} y2={index * 110 + 60 + second.z * 9} />;
      })}
      {graphProducts.filter((product) => layer.ids.includes(product.id)).map((product) => <circle key={product.id} cx={300 + product.x * 46} cy={index * 110 + 60 + product.z * 9} r={6} data-active={index <= step && layer.path.includes(product.id)}><title>{product.label}</title></circle>)}
    </g>)}
  </svg>;
}

type Playback = "idle" | "playing" | "paused" | "complete";

/** The walkthrough is illustrative; it never invokes retrieval or reads index edges. */
export function HnswSearchGraph() {
  const [step, setStep] = useState(0);
  const [playback, setPlayback] = useState<Playback>("idle");
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const reducedMotion = useReducedMotion() ?? false;
  const host = useRef<HTMLDivElement>(null);
  const figure = useRef<HTMLElement>(null);
  const scene = useRef<ReturnType<typeof mountHnswScene> | null>(null);
  const progress = useRef(0);

  useEffect(() => {
    let active = true;
    setState("loading");
    void import("../hnswScene").then(({ mountHnswScene: mount }) => {
      if (!active || !host.current) return;
      scene.current = mount(host.current, () => {
        scene.current?.dispose(); scene.current = null;
        setState("unavailable"); setPlayback((value) => value === "playing" ? "paused" : value);
      }, () => setPlayback((value) => value === "playing" ? "paused" : value));
      scene.current.setProgress(progress.current, false);
      setState("ready");
    }).catch(() => { if (active) setState("unavailable"); });
    return () => { active = false; scene.current?.dispose(); scene.current = null; };
  }, [attempt]);

  useEffect(() => {
    if (playback !== "playing") return;
    const from = progress.current;
    const started = performance.now();
    let frame = 0;
    let previousStep = Math.min(2, Math.floor(from));
    const tick = (now: number) => {
      // A callback can share the frame that started playback; its timestamp
      // then precedes performance.now(). Never turn that into layer -1.
      const next = Math.min(3, from + Math.max(0, now - started) * 3 / graphTourDuration);
      progress.current = next;
      const nextStep = Math.min(2, Math.floor(next));
      if (nextStep !== previousStep) { setStep(nextStep); previousStep = nextStep; }
      scene.current?.setProgress(reducedMotion ? nextStep + 1 : next, !reducedMotion);
      if (next === 3) setPlayback("complete");
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playback, reducedMotion]);

  useEffect(() => {
    const pause = () => setPlayback((value) => value === "playing" ? "paused" : value);
    const onVisibility = () => { if (document.hidden) pause(); };
    document.addEventListener("visibilitychange", onVisibility);
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(([entry]) => { if (!entry.isIntersecting) pause(); });
    if (figure.current) observer?.observe(figure.current);
    return () => { document.removeEventListener("visibilitychange", onVisibility); observer?.disconnect(); };
  }, []);

  function chooseStep(index: number) {
    setStep(index); setSelected(null);
    progress.current = index + 1;
    setPlayback(index === 2 ? "complete" : "paused");
    scene.current?.setStep(index);
    scene.current?.highlight(null);
  }
  function watch() {
    if (playback === "playing") { setPlayback("paused"); return; }
    if (playback === "complete" || playback === "idle") {
      progress.current = 0; setStep(0); setSelected(null);
      scene.current?.highlight(null); scene.current?.reset();
      scene.current?.setProgress(0, false);
    }
    setPlayback("playing");
  }
  function inspect(action: () => void) {
    setPlayback((value) => value === "playing" ? "paused" : value);
    action();
  }
  function highlight(id: string) { setSelected(id); scene.current?.highlight(id); }
  const request = mosaicLabManifest.playground.requests.find((item) => item.id === "clear-calls");
  const finished = playback === "complete";
  const actionLabel = playback === "playing" ? "Pause search" : finished ? "Watch again" : playback === "paused" ? "Continue search" : "Watch the search";

  return <figure ref={figure} className="hnsw-search-graph" data-playback={playback}>
    <div className="hnsw-graph-request"><Headphones size={24} aria-hidden="true" /><p>{request?.query}</p></div>
    <div className="hnsw-graph-viewport">
      <div className="hnsw-graph-scene-note">HNSW · An illustrated search</div>
      <div ref={host} className="hnsw-graph-canvas" hidden={state === "unavailable"} />
      {state === "loading" && <p className="hnsw-graph-loading" role="status">Opening the 3D graph…</p>}
      {state === "unavailable" && <><FlatGraph step={step} /><p className="hnsw-graph-fallback" role="status">3D is unavailable. You can still explore the layers. <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry 3D</button></p></>}
      {state === "ready" && <div className="hnsw-graph-tools" aria-label="3D view controls">
        <span>Drag to explore · arrow keys rotate</span>
        <button type="button" aria-label="Rotate graph left" onClick={() => inspect(() => scene.current?.rotate(0.3))}><RotateCcw size={16} /></button>
        <button type="button" aria-label="Rotate graph right" onClick={() => inspect(() => scene.current?.rotate(-0.3))}><RotateCw size={16} /></button>
        <button type="button" aria-label="Zoom out" onClick={() => inspect(() => scene.current?.zoom(1.15))}><Minus size={16} /></button>
        <button type="button" aria-label="Zoom in" onClick={() => inspect(() => scene.current?.zoom(1 / 1.15))}><Plus size={16} /></button>
        <button type="button" onClick={() => inspect(() => scene.current?.reset())}>Reset view</button>
      </div>}
    </div>
    <div className="hnsw-graph-playback">
      <div className="hnsw-graph-steps" aria-label="Explore the graph search">{graphSteps.map((item, index) => <button key={item.label} type="button" aria-pressed={step === index} onClick={() => chooseStep(index)}><span>{index + 1}.</span> {item.label}</button>)}</div>
      <button type="button" className="hnsw-graph-play" disabled={state === "loading"} onClick={watch}>{playback === "playing" ? <Pause size={17} fill="currentColor" aria-hidden="true" /> : finished ? <RotateCcw size={17} aria-hidden="true" /> : <Play size={17} fill="currentColor" aria-hidden="true" />}{actionLabel}</button>
    </div>
    <div className="hnsw-graph-explanation" role="status"><h3>{graphSteps[step].label}.</h3><p>{graphSteps[step].explanation}</p></div>
    {finished && <div className="hnsw-graph-candidates">
      <div className="hnsw-candidates-heading"><h4>Nearby candidates.</h4><p>Explore a product type in the graph.</p></div>
      <ul aria-label="Illustrated candidate product types">{graphCandidates.map((product) => <li key={product.id}><button type="button" aria-pressed={selected === product.id} onClick={() => highlight(product.id)} onFocus={() => highlight(product.id)}><img src={product.image} alt="" width={300} height={200} loading="lazy" /><span>{product.label}<span className="hnsw-candidate-dot" aria-hidden="true" /></span></button></li>)}</ul>
      <p className="hnsw-candidates-note">These are candidates, not recommendations. Filters and ranking still determine Alex’s shortlist.</p>
    </div>}
    <figcaption>Illustration using Mosaic’s product types. Positions, links and the search path are for explanation, not a recorded Aurora traversal.</figcaption>
  </figure>;
}
