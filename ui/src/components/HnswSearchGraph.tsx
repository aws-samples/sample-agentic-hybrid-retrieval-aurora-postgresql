import { Headphones, Minus, Plus, RotateCcw, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { graphLayers, graphLinks, graphProducts, graphSteps } from "../hnswGraph";
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

/** The scene and its renderer are loaded only when visiting Scale & HNSW. */
export function HnswSearchGraph() {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [attempt, setAttempt] = useState(0);
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<ReturnType<typeof mountHnswScene> | null>(null);
  useEffect(() => {
    let active = true;
    setState("loading");
    void import("../hnswScene").then(({ mountHnswScene: mount }) => {
      if (!active || !host.current) return;
      scene.current = mount(host.current, () => { scene.current?.dispose(); scene.current = null; setState("unavailable"); });
      setState("ready");
    }).catch(() => { if (active) setState("unavailable"); });
    return () => { active = false; scene.current?.dispose(); scene.current = null; };
  }, [attempt]);
  useEffect(() => { scene.current?.setStep(step); }, [step, state]);
  const request = mosaicLabManifest.playground.requests.find((item) => item.id === "clear-calls");
  return <figure className="hnsw-search-graph">
    <div className="hnsw-graph-request"><Headphones size={22} aria-hidden="true" /><p>{request?.query}</p></div>
    <div className="hnsw-graph-steps" aria-label="Explore the graph search">{graphSteps.map((item, index) => <button key={item.label} type="button" aria-pressed={step === index} onClick={() => setStep(index)}>{index + 1}. {item.label}</button>)}</div>
    <div className="hnsw-graph-viewport">
      <div ref={host} className="hnsw-graph-canvas" hidden={state === "unavailable"} />
      {state === "loading" ? <p className="hnsw-graph-loading" role="status">Opening the 3D graph…</p> : null}
      {state === "unavailable" ? <><FlatGraph step={step} /><p className="hnsw-graph-fallback" role="status">3D is unavailable. You can still explore the layers. <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry 3D</button></p></> : null}
      {state === "ready" ? <div className="hnsw-graph-tools" aria-label="3D view controls"><span>Drag or use arrow keys to rotate</span><button type="button" aria-label="Rotate graph left" onClick={() => scene.current?.rotate(0.3)}><RotateCcw size={16} /></button><button type="button" aria-label="Rotate graph right" onClick={() => scene.current?.rotate(-0.3)}><RotateCw size={16} /></button><button type="button" aria-label="Zoom out" onClick={() => scene.current?.zoom(1.15)}><Minus size={16} /></button><button type="button" aria-label="Zoom in" onClick={() => scene.current?.zoom(1 / 1.15)}><Plus size={16} /></button><button type="button" onClick={() => scene.current?.reset()}>Reset view</button></div> : null}
    </div>
    <p className="hnsw-graph-explanation" role="status">{graphSteps[step].explanation}</p>
    <figcaption>Illustration using Mosaic’s product types. Positions and paths are for explanation.</figcaption>
  </figure>;
}
