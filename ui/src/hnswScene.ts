import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { graphLayers, graphLinks, graphProducts } from "./hnswGraph";

/** Render on interaction, and release all GPU resources when leaving the page. */
export function mountHnswScene(host: HTMLElement, onLost: () => void) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("webgl2", { antialias: true, alpha: true });
  if (!context) throw new Error("3D is unavailable in this browser.");
  const renderer = new THREE.WebGLRenderer({ canvas, context, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "3D HNSW graph. Drag or use arrow keys to rotate. Use the zoom buttons to move closer.");
  const labels = document.createElement("div");
  labels.className = "hnsw-scene-labels";
  labels.setAttribute("aria-hidden", "true");
  host.append(canvas, labels);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false;
  controls.enableZoom = false; // Preserve normal page scrolling over the scene.
  controls.minPolarAngle = 0.3;
  controls.maxPolarAngle = 1.45;
  controls.target.set(0, 3, 0);
  const style = getComputedStyle(host);
  const color = (name: string) => style.getPropertyValue(name).trim();
  const maroon = new THREE.Color(color("--maroon-800"));
  const cream = new THREE.Color(color("--paper"));
  const line = new THREE.Color(color("--line-strong"));
  scene.add(new THREE.HemisphereLight(0xffffff, 0x827466, 2.5));
  const light = new THREE.DirectionalLight(0xffffff, 3);
  light.position.set(-5, 12, 8); scene.add(light);
  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];
  const nodes: { mesh: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>; layer: number; id: string }[] = [];
  const paths: { mesh: THREE.Mesh; layer: number }[] = [];
  const textLabels: { element: HTMLSpanElement; position: THREE.Vector3; layer: number; id?: string }[] = [];
  let activeStep = 0, frame = 0, width = 1, height = 1;
  let disposed = false;
  const projected = new THREE.Vector3();
  const offset = new THREE.Vector3();
  function label(text: string, position: THREE.Vector3, layer: number, id?: string) {
    const element = document.createElement("span");
    element.className = id ? "hnsw-scene-product" : "hnsw-scene-layer";
    element.textContent = text; labels.append(element);
    textLabels.push({ element, position, layer, id });
  }
  function point(id: string, layer: number) {
    const product = graphProducts.find((item) => item.id === id)!;
    return new THREE.Vector3(product.x, graphLayers[layer].y, product.z);
  }
  function tube(start: THREE.Vector3, end: THREE.Vector3, layer: number) {
    const geometry = new THREE.CylinderGeometry(0.035, 0.035, start.distanceTo(end), 6);
    const material = new THREE.MeshBasicMaterial({ color: maroon });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.copy(start).add(end).multiplyScalar(0.5);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), end.clone().sub(start).normalize());
    geometries.push(geometry); materials.push(material); scene.add(mesh); paths.push({ mesh, layer });
  }
  graphLayers.forEach((layer, index) => {
    const outline = new THREE.BufferGeometry().setFromPoints([[-5.5, -3.5], [5, -3.5], [5, 3.5], [-5.5, 3.5]].map(([x, z]) => new THREE.Vector3(x, layer.y - 0.08, z)));
    const outlineMaterial = new THREE.LineBasicMaterial({ color: line, transparent: true, opacity: 0.65 });
    scene.add(new THREE.LineLoop(outline, outlineMaterial)); geometries.push(outline); materials.push(outlineMaterial);
    label(layer.label, new THREE.Vector3(-5.5, layer.y + 0.25, 3.5), index);
    for (const [a, b] of graphLinks(layer)) {
      const geometry = new THREE.BufferGeometry().setFromPoints([point(a, index), point(b, index)]);
      const material = new THREE.LineBasicMaterial({ color: line });
      scene.add(new THREE.Line(geometry, material)); geometries.push(geometry); materials.push(material);
    }
    for (const id of layer.ids) {
      const geometry = new THREE.SphereGeometry(0.12, 16, 12);
      const material = new THREE.MeshStandardMaterial({ color: cream, roughness: 0.55, metalness: 0.08 });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.copy(point(id, index)); scene.add(mesh);
      geometries.push(geometry); materials.push(material); nodes.push({ mesh, layer: index, id });
      if (layer.path.includes(id)) label(graphProducts.find((item) => item.id === id)!.label, point(id, index).add(new THREE.Vector3(0, 0.38, 0)), index, id);
    }
    layer.path.slice(1).forEach((id, i) => tube(point(layer.path[i], index), point(id, index), index));
    if (index > 0) { const id = graphLayers[index - 1].path.at(-1)!; tube(point(id, index - 1), point(id, index), index); }
  });
  function render() {
    frame = 0;
    if (disposed) return;
    renderer.render(scene, camera);
    for (const item of textLabels) {
      projected.copy(item.position).project(camera);
      const visible = projected.z < 1 && (!item.id || item.layer === activeStep);
      item.element.hidden = !visible;
      if (visible) item.element.style.transform = `translate(${(projected.x + 1) * width / 2}px, ${(1 - projected.y) * height / 2}px) translate(-50%, -100%)`;
    }
  }
  function schedule() { if (!frame && !disposed) frame = requestAnimationFrame(render); }
  function reset() { camera.position.set(10, 10.5, 16); controls.target.set(0, 3, 0); controls.update(); schedule(); }
  function rotate(horizontal: number, vertical = 0) { controls.rotateLeft(horizontal); controls.rotateUp(vertical); controls.update(); schedule(); }
  function zoom(factor: number) {
    offset.copy(camera.position).sub(controls.target);
    offset.setLength(THREE.MathUtils.clamp(offset.length() * factor, 10, 36));
    camera.position.copy(controls.target).add(offset); controls.update(); schedule();
  }
  function keydown(event: KeyboardEvent) {
    if (!event.key.startsWith("Arrow")) return;
    event.preventDefault();
    rotate(event.key === "ArrowLeft" ? 0.16 : event.key === "ArrowRight" ? -0.16 : 0, event.key === "ArrowUp" ? 0.12 : event.key === "ArrowDown" ? -0.12 : 0);
  }
  function lost(event: Event) { event.preventDefault(); onLost(); }
  canvas.addEventListener("keydown", keydown); canvas.addEventListener("webglcontextlost", lost);
  controls.addEventListener("change", schedule);
  const observer = new ResizeObserver(() => {
    width = Math.max(host.clientWidth, 1); height = Math.max(host.clientHeight, 1);
    camera.aspect = width / height; camera.zoom = Math.min(1, camera.aspect / 1.5);
    camera.updateProjectionMatrix(); renderer.setSize(width, height); schedule();
  });
  observer.observe(host); reset();
  function setStep(step: number) {
    activeStep = step;
    for (const node of nodes) {
      const active = node.layer <= step && graphLayers[node.layer].path.includes(node.id);
      node.mesh.material.color.copy(active ? maroon : cream); node.mesh.scale.setScalar(active ? 1.5 : 1);
    }
    for (const path of paths) path.mesh.visible = path.layer <= step;
    schedule();
  }
  setStep(0);
  return { setStep, reset, rotate, zoom, dispose() {
    disposed = true; cancelAnimationFrame(frame); observer.disconnect();
    canvas.removeEventListener("keydown", keydown); canvas.removeEventListener("webglcontextlost", lost);
    controls.dispose(); geometries.forEach((item) => item.dispose()); materials.forEach((item) => item.dispose());
    renderer.dispose(); renderer.forceContextLoss(); canvas.remove(); labels.remove();
  } };
}
