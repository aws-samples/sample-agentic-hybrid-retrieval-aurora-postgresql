export const graphSteps = [
  { label: "Start wide", explanation: "A few links in the upper layer lead toward headphones for Alex’s calls." },
  { label: "Move closer", explanation: "Drop to the same product in the next layer, then explore nearby choices." },
  { label: "Find neighbors", explanation: "Explore the bottom layer for candidates. Filters and ranking decide what reaches Alex." },
];

// Teaching coordinates, not embedding coordinates or recorded pgvector edges.
export const graphProducts = [
  { id: "lamp", label: "Desk lamp", x: -4.5, z: -1.5 },
  { id: "monitor", label: "Monitor", x: -0.8, z: -1.8 },
  { id: "headphones", label: "Headphones", x: 2.4, z: 0 },
  { id: "chair", label: "Chair", x: -3.2, z: 1.4 },
  { id: "earbuds", label: "Earbuds", x: 1.1, z: 2.4 },
  { id: "headset", label: "Headset", x: 4.1, z: 1.5 },
  { id: "webcam", label: "Webcam", x: -0.4, z: 1.1 },
  { id: "microphone", label: "Microphone", x: 4, z: -1.8 },
  { id: "keyboard", label: "Keyboard", x: -2.6, z: -2.8 },
  { id: "desk", label: "Desk", x: -4.8, z: 2.9 },
  { id: "speaker", label: "Speaker", x: 1.3, z: -2.6 },
  { id: "dock", label: "Dock", x: -1, z: 3 },
  { id: "light", label: "Monitor light", x: -4.7, z: 0.4 },
  { id: "mouse", label: "Mouse", x: -2.6, z: -0.4 },
  { id: "stand", label: "Laptop stand", x: -2.5, z: 3 },
  { id: "cable", label: "Cable", x: 0.8, z: -0.7 },
  { id: "cushion", label: "Seat cushion", x: -3.8, z: -3 },
  { id: "audio", label: "Audio interface", x: 3.2, z: 3 },
];
export const graphLayers = [
  { label: "Upper layer", y: 6, ids: ["lamp", "monitor", "headphones"], path: ["lamp", "monitor", "headphones"] },
  { label: "Middle layer", y: 3, ids: ["lamp", "monitor", "headphones", "chair", "earbuds", "headset", "webcam", "microphone"], path: ["headphones", "headset"] },
  { label: "All products", y: 0, ids: graphProducts.map((product) => product.id), path: ["headset", "headphones", "earbuds"] },
];
export function graphLinks(layer: typeof graphLayers[number]): [string, string][] {
  const links = new Map<string, [string, string]>();
  const add = (a: string, b: string) => { links.set([a, b].sort().join("/"), [a, b]); };
  const products = graphProducts.filter((product) => layer.ids.includes(product.id));
  for (const product of products) {
    const nearest = products.filter((other) => other !== product).sort((a, b) => Math.hypot(a.x - product.x, a.z - product.z) - Math.hypot(b.x - product.x, b.z - product.z));
    for (const other of nearest.slice(0, 2)) add(product.id, other.id);
  }
  layer.path.slice(1).forEach((id, i) => add(layer.path[i], id));
  return [...links.values()];
}
