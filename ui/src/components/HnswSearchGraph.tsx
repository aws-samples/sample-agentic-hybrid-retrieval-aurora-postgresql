import { ChevronRight, Play, RotateCcw } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { memo, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  buildToyIndex, EFFORT_OPTIONS, LINK_OPTIONS, MAP_WIDTH, searchToyIndex, TOY_GROUPS, TOY_REQUESTS, TOY_RESULTS,
  type ToyIndex, type ToySearch, type TraceEvent,
} from "../hnswToy";
import "../hnsw-search-graph.css";

export type ServedHnsw = { efSearch: number; vectors: number; dimensions: number | null; definition: string };
type Request = { id: string; label: string; x: number; y: number };

const VIEW_W = 1000;
const VIEW_H = 625;
const PAD = 28;
const sx = (x: number) => PAD + (x / MAP_WIDTH) * (VIEW_W - 2 * PAD);
const sy = (y: number) => PAD + y * (VIEW_H - 2 * PAD);
const LAYER_NAMES = ["All products", "Middle layer", "Top layer"];
const LAYER_NOTES = [
  "On the bottom layer, a beam of candidates explores short links around the request.",
  "The middle layer has more products and shorter links.",
  "The top layer holds a few products joined by long links that get close quickly.",
];
const percent = (value: number) => `${Math.round(value * 100)}%`;

/** Times each trace event so upper layers read as hops and the bottom layer as a sweep. */
function schedule(trace: TraceEvent[], checks: number) {
  const bottom = trace.filter((event) => event.layer === 0 && event.kind !== "descend").length;
  const sweep = Math.min(2600, Math.max(1100, checks * 28)) / Math.max(bottom, 1);
  let time = 0;
  return trace.map((event) => {
    time += event.kind === "descend" ? 420 : event.layer > 0 ? 120 : sweep;
    return time;
  });
}

type Playhead = {
  layer: number; current: number; checked: Set<number>; beam: Set<number>;
  trail: [number, number][]; path: [number, number][];
};

function replay(trace: TraceEvent[], upTo: number, entry: number, top: number): Playhead {
  const head: Playhead = { layer: top, current: entry, checked: new Set([entry]), beam: new Set(), trail: [], path: [] };
  for (const event of trace.slice(0, upTo)) {
    head.layer = event.layer;
    if (event.kind === "check") { head.checked.add(event.node); head.trail.push([event.from, event.node]); }
    if (event.kind === "move") { head.path.push([event.from, event.node]); head.current = event.node; }
    if (event.kind === "descend") { head.current = event.node; head.beam.clear(); }
    if (event.kind === "admit") head.beam.add(event.node);
    if (event.kind === "evict") head.beam.delete(event.node);
  }
  return head;
}

/** Each group's label sits just above its products, or below them when the map's top edge is close. */
function groupLabels(points: ToyIndex["points"]) {
  return TOY_GROUPS.map((group) => {
    const members = points.filter((point) => point.group === group.name);
    const top = sy(Math.min(...members.map((point) => point.y))) - 16;
    const x = members.reduce((sum, point) => sum + sx(point.x), 0) / members.length;
    return { name: group.name, x, y: top < 44 ? sy(Math.max(...members.map((point) => point.y))) + 30 : top };
  });
}

const MapBase = memo(function MapBase({ index, layer }: { index: ToyIndex; layer: number }) {
  const { points, levels, links } = index;
  const edges: [number, number][] = [];
  links[layer].forEach((list, from) => list.forEach((to) => { if (from < to || !links[layer][to].includes(from)) edges.push([from, to]); }));
  return <>
    <g className="hnsw-map-edges" data-upper={layer > 0}>
      {edges.map(([a, b]) => <line key={`${a}-${b}`} x1={sx(points[a].x)} y1={sy(points[a].y)} x2={sx(points[b].x)} y2={sy(points[b].y)} />)}
    </g>
    <g className="hnsw-map-nodes">
      {points.map((point) => <circle key={point.id} cx={sx(point.x)} cy={sy(point.y)} r={4 + levels[point.id] * 2.5}
        data-member={levels[point.id] >= layer} />)}
    </g>
    <g className="hnsw-map-groups" aria-hidden="true">
      {groupLabels(points).map((label) => <text key={label.name} x={label.x} y={label.y} textAnchor="middle">{label.name}</text>)}
    </g>
  </>;
});

function MapOverlay({ index, head, search, done, request }: {
  index: ToyIndex; head: Playhead; search: ToySearch; done: boolean; request: Request;
}) {
  const { points } = index;
  const at = (id: number) => ({ x: sx(points[id].x), y: sy(points[id].y) });
  const line = ([a, b]: [number, number], className: string) => {
    const from = at(a); const to = at(b);
    return <line key={`${className}-${a}-${b}`} className={className} x1={from.x} y1={from.y} x2={to.x} y2={to.y} />;
  };
  const current = at(head.current);
  return <>
    <g className="hnsw-map-trail">{head.trail.map((edge) => line(edge, "hnsw-trail"))}</g>
    <g className="hnsw-map-path">{head.path.map((edge) => line(edge, "hnsw-hop"))}</g>
    <g className="hnsw-map-checked">{[...head.checked].map((id) => <circle key={id} cx={at(id).x} cy={at(id).y} r={4 + index.levels[id] * 2.5} />)}</g>
    {!done && <g className="hnsw-map-beam">{[...head.beam].map((id) => <circle key={id} cx={at(id).x} cy={at(id).y} r={9} />)}</g>}
    {done && <g className="hnsw-map-exact">{search.exact.map((id) => <circle key={id} cx={at(id).x} cy={at(id).y} r={12} />)}</g>}
    {done && <g className="hnsw-map-results">{search.results.map((id) => <circle key={id} cx={at(id).x} cy={at(id).y} r={7} />)}</g>}
    {!done && <circle className="hnsw-map-current" cx={current.x} cy={current.y} r={8} />}
    <g className="hnsw-map-request" transform={`translate(${sx(request.x)} ${sy(request.y)})`}>
      <circle r={9} /><line x1={-16} x2={-5} /><line x1={5} x2={16} /><line y1={-16} y2={-5} /><line y1={5} y2={16} />
      <text x={request.x > MAP_WIDTH * 0.8 ? -24 : 24} y={6} textAnchor={request.x > MAP_WIDTH * 0.8 ? "end" : "start"}>
        {request.id === "custom" ? "Your point" : "Alex’s request"}</text>
    </g>
  </>;
}

function takeaway(search: ToySearch, effort: number, m: number, recallByEffort: number[], total: number) {
  const matches = Math.round(search.recall * TOY_RESULTS);
  if (effort < TOY_RESULTS) {
    return `ef_search ${effort} keeps only ${effort} candidate${effort === 1 ? "" : "s"}, so one index scan returns ${search.results.length} of ${TOY_RESULTS} rows. Raise ef_search, or let an iterative scan continue, to fill the list.`;
  }
  if (matches < TOY_RESULTS) {
    const fix = EFFORT_OPTIONS.find((value, i) => value > effort && recallByEffort[i] === 1);
    return `The beam settled among the wrong products and returned ${matches} of the ${TOY_RESULTS} true nearest. ${fix ? `A wider beam escapes it here: try ef_search ${fix}.` : "No ef_search in this list escapes it; more links per product (a larger m) would."}${m === LINK_OPTIONS[0] && fix ? " Or rebuild with more links per product." : ""}`;
  }
  const enough = EFFORT_OPTIONS.find((value, i) => recallByEffort[i] === 1 && value >= TOY_RESULTS);
  return enough !== undefined && enough < effort
    ? `HNSW checked ${search.checks} of ${total} products and matched an exact scan. ef_search ${enough} was already enough here; the extra effort only added checks.`
    : `HNSW checked ${search.checks} of ${total} products and returned the same ${TOY_RESULTS} as an exact scan, which checks all ${total}.`;
}

/** A real HNSW index on a toy product map, searched in the browser with the participant's settings. */
export function HnswSearchGraph({ served = null }: { served?: ServedHnsw | null }) {
  const [request, setRequest] = useState<Request>({ ...TOY_REQUESTS[0] });
  const [effortChoice, setEffortChoice] = useState(2);
  const [linkChoice, setLinkChoice] = useState(1);
  const [run, setRun] = useState(0);
  const [cursor, setCursor] = useState(0);
  const reducedMotion = useReducedMotion() ?? false;
  const svg = useRef<SVGSVGElement>(null);
  const effort = EFFORT_OPTIONS[effortChoice];
  const m = LINK_OPTIONS[linkChoice];

  const index = useMemo(() => buildToyIndex(m), [m]);
  const search = useMemo(() => searchToyIndex(index, request, effort), [index, request, effort]);
  const recallByEffort = useMemo(() => EFFORT_OPTIONS.map((value) => searchToyIndex(index, request, value).recall), [index, request]);
  const times = useMemo(() => schedule(search.trace, search.checks), [search]);
  const end = search.trace.length;

  useEffect(() => {
    if (reducedMotion) { setCursor(end); return; }
    setCursor(0);
    const started = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const elapsed = Math.max(0, now - started);
      let next = 0;
      while (next < end && times[next] <= elapsed) next += 1;
      setCursor(next);
      if (next < end) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [search, times, end, reducedMotion, run]);

  const done = cursor >= end;
  const head = useMemo(() => replay(search.trace, cursor, index.entry, index.top), [search, cursor, index]);
  const layer = done ? 0 : head.layer;
  const total = index.points.length;
  const shownChecks = done ? search.checks : head.checked.size;
  const servedM = served?.definition.match(/\bm\s*=\s*'?(\d+)/i)?.[1];

  function place(event: MouseEvent<SVGSVGElement>) {
    const box = svg.current?.getBoundingClientRect();
    if (!box || !box.width) return;
    const x = ((event.clientX - box.left) / box.width * VIEW_W - PAD) / (VIEW_W - 2 * PAD) * MAP_WIDTH;
    const y = ((event.clientY - box.top) / box.height * VIEW_H - PAD) / (VIEW_H - 2 * PAD);
    if (x < 0 || x > MAP_WIDTH || y < 0 || y > 1) return;
    setRequest({ id: "custom", label: "Your point", x, y });
  }

  return <figure className="hnsw-lab" data-done={done}>
    <div className="hnsw-lab-head">
      <div className="hnsw-lab-requests" role="group" aria-label="Alex’s request">
        {TOY_REQUESTS.map((item) => <button key={item.id} type="button" aria-pressed={request.id === item.id}
          onClick={() => setRequest({ ...item })}>{item.label}</button>)}
      </div>
      <button type="button" className="hnsw-graph-play" onClick={() => setRun((value) => value + 1)}>
        {done ? <RotateCcw size={17} aria-hidden="true" /> : <Play size={17} fill="currentColor" aria-hidden="true" />}
        {done ? "Search again" : "Restart search"}
      </button>
    </div>

    <div className="hnsw-lab-stage">
      <ol className="hnsw-lab-layers" aria-label="Graph layers, top to bottom">
        {[2, 1, 0].filter((value) => value <= index.top).map((value) => <li key={value}
          data-active={!done && layer === value} data-passed={done || layer < value}>
          <strong>{LAYER_NAMES[value]}</strong>
          <span>{index.levels.filter((level) => level >= value).length} products</span>
          {value > 0 && <ChevronRight size={16} aria-hidden="true" />}
        </li>)}
      </ol>
      <svg ref={svg} className="hnsw-lab-map" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} onClick={place}
        role="img" aria-label={`HNSW search map. ${done ? `${search.results.length} results, ${percent(search.recall)} recall against exact search.` : `Searching the ${LAYER_NAMES[layer].toLowerCase()}.`}`}>
        <MapBase index={index} layer={layer} />
        <MapOverlay index={index} head={head} search={search} done={done} request={request} />
      </svg>
      <ul className="hnsw-lab-legend" aria-label="Map key">
        <li><svg viewBox="0 0 24 24" aria-hidden="true"><circle className="key-checked" cx="12" cy="12" r="5" /></svg>Distance checked</li>
        <li><svg viewBox="0 0 24 24" aria-hidden="true"><circle className="key-result" cx="12" cy="12" r="6" /></svg>Returned by HNSW</li>
        <li><svg viewBox="0 0 24 24" aria-hidden="true"><circle className="key-exact" cx="12" cy="12" r="9" /></svg>True nearest (exact)</li>
        <li className="hnsw-lab-legend-hint">Click the map to move the request.</li>
      </ul>
    </div>

    <div className="hnsw-lab-panel">
      <div className="hnsw-lab-controls">
        <fieldset>
          <legend>Search effort <code>ef_search</code></legend>
          <div className="hnsw-lab-options">
            {EFFORT_OPTIONS.map((value, i) => <button key={value} type="button" aria-pressed={effortChoice === i}
              aria-label={`ef_search ${value}, recall ${percent(recallByEffort[i])}`} onClick={() => setEffortChoice(i)}>
              <span>{value}</span><small>{percent(recallByEffort[i])}</small>
            </button>)}
          </div>
          <p>Candidates kept while searching. The small figure is the recall it reaches for this request.</p>
        </fieldset>
        <fieldset>
          <legend>Links per product <code>m</code></legend>
          <div className="hnsw-lab-options">
            {LINK_OPTIONS.map((value, i) => <button key={value} type="button" aria-pressed={linkChoice === i}
              aria-label={`m ${value}`} onClick={() => setLinkChoice(i)}><span>{value}</span></button>)}
          </div>
          <p>Set when the index is built. Changing it rebuilds this graph.</p>
        </fieldset>
      </div>
      <div className="hnsw-lab-receipt">
        <dl>
          <div><dt>Distance checks</dt><dd>{shownChecks}<small> of {total}</small></dd></div>
          <div><dt>Rows returned</dt><dd>{done ? search.results.length : "–"}<small> of {TOY_RESULTS}</small></dd></div>
          <div><dt>Same as exact search</dt><dd>{done ? Math.round(search.recall * TOY_RESULTS) : "–"}<small> of {TOY_RESULTS}</small></dd></div>
          <div className="hnsw-lab-total"><dt>Recall@{TOY_RESULTS}</dt><dd>{done ? percent(search.recall) : "–"}</dd></div>
        </dl>
        <p className="hnsw-lab-takeaway" role="status">{done ? takeaway(search, effort, m, recallByEffort, total) : LAYER_NOTES[layer]}</p>
      </div>
    </div>

    <figcaption>
      A real HNSW index built in your browser over {total} products on a two-dimensional map; the points are a teaching stand-in.
      {served ? ` Mosaic’s Aurora index searches ${served.vectors.toLocaleString("en-US")} products${served.dimensions ? ` in ${served.dimensions.toLocaleString("en-US")} dimensions` : ""}${servedM ? ` with m = ${servedM}` : ""} and ef_search = ${served.efSearch}. The steps are the same.` : " Aurora’s index searches far more products in far more dimensions; the steps are the same."}
    </figcaption>
  </figure>;
}
