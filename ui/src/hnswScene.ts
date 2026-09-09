import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { graphLayers, graphLinks, graphProducts } from "./hnswGraph";

/** A small teaching sculpture. Rendering stops whenever the view is still. */
export function mountHnswScene(host: HTMLElement, onLost: () => void, onInteract: () => void = () => {}) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("webgl2", { antialias: true, alpha: true });
  if (!context) throw new Error("3D is unavailable in this browser.");
  const renderer = new THREE.WebGLRenderer({ canvas, context, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "3D HNSW graph. Drag or use arrow keys to rotate. Use the zoom buttons to move closer.");
  const labels = document.createElement("div");
  labels.className = "hnsw-scene-labels";
  labels.setAttribute("aria-hidden", "true");
  host.append(canvas, labels);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(37, 1, 0.1, 100);
  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false;
  controls.enableZoom = false;
  controls.minPolarAngle = 0.4;
  controls.maxPolarAngle = 1.45;
  const style = getComputedStyle(host);
  const color = (name: string) => new THREE.Color(style.getPropertyValue(name).trim());
  const maroon = color("--maroon-800");
  const cream = color("--paper");
  const warm = color("--paper-warm");
  const line = color("--line-strong");
  scene.add(new THREE.HemisphereLight(cream, line, 2.1));
  const light = new THREE.DirectionalLight(cream, 3.5);
  light.position.set(-6, 14, 9);
  light.castShadow = true;
  light.shadow.mapSize.set(1024, 1024);
  Object.assign(light.shadow.camera, { left: -10, right: 10, top: 10, bottom: -10, near: 0.5, far: 40 });
  light.shadow.bias = -0.001;
  light.shadow.normalBias = 0.04;
  light.shadow.radius = 4;
  scene.add(light);
  const fill = new THREE.DirectionalLight(cream, 1.5);
  fill.position.set(8, 5, -7); scene.add(fill);

  const geometries: THREE.BufferGeometry[] = [];
  const materials: THREE.Material[] = [];
  const nodes: { mesh: THREE.Mesh<THREE.SphereGeometry, THREE.MeshStandardMaterial>; layer: number; id: string; reached: number }[] = [];
  const paths: { mesh: THREE.Mesh; from: THREE.Vector3; to: THREE.Vector3; length: number; start: number; end: number }[] = [];
  const textLabels: { element: HTMLSpanElement; position: THREE.Vector3; layer: number; reached: number; id?: string; width: number; x: number; y: number; visible: boolean }[] = [];
  const baseEdges: { material: THREE.LineBasicMaterial; layer: number }[] = [];
  let activeStep = 0, progress = 0, frame = 0, width = 1, height = 1;
  let disposed = false;
  let selected: string | null = null;
  const projected = new THREE.Vector3();
  const offset = new THREE.Vector3();
  const pathPosition = new THREE.Vector3();
  const defaultCamera = new THREE.Vector3(11.5, 10.4, 17.5);
  const closeCamera = new THREE.Vector3(10, 8.4, 18.8);
  const defaultTarget = new THREE.Vector3(0, 3, 0);
  const closeTarget = new THREE.Vector3(0.3, 2.6, 0);

  function label(text: string, position: THREE.Vector3, layer: number, reached = 0, id?: string) {
    const element = document.createElement("span");
    element.className = id ? "hnsw-scene-product" : "hnsw-scene-layer";
    element.textContent = text; labels.append(element);
    textLabels.push({ element, position, layer, reached, id, width: element.offsetWidth, x: 0, y: 0, visible: false });
  }
  function point(id: string, layer: number) {
    const product = graphProducts.find((item) => item.id === id)!;
    return new THREE.Vector3(product.x, graphLayers[layer].y + 0.2, product.z);
  }
  function tube(from: THREE.Vector3, to: THREE.Vector3, start: number, end: number) {
    const geometry = new THREE.CylinderGeometry(0.035, 0.035, 1, 10);
    const material = new THREE.MeshStandardMaterial({ color: maroon, roughness: 0.45 });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), to.clone().sub(from).normalize());
    mesh.castShadow = true;
    geometries.push(geometry); materials.push(material); scene.add(mesh);
    paths.push({ mesh, from, to, length: from.distanceTo(to), start, end });
  }
  function surface(y: number) {
    const shape = new THREE.Shape();
    const left = -5.6, right = 5.2, back = -3.7, front = 3.8, radius = 0.3;
    shape.moveTo(left + radius, back);
    shape.lineTo(right - radius, back); shape.quadraticCurveTo(right, back, right, back + radius);
    shape.lineTo(right, front - radius); shape.quadraticCurveTo(right, front, right - radius, front);
    shape.lineTo(left + radius, front); shape.quadraticCurveTo(left, front, left, front - radius);
    shape.lineTo(left, back + radius); shape.quadraticCurveTo(left, back, left + radius, back);
    const geometry = new THREE.ExtrudeGeometry(shape, { depth: 0.06, bevelEnabled: true, bevelSegments: 2, steps: 1, bevelSize: 0.035, bevelThickness: 0.025, curveSegments: 12 });
    geometry.rotateX(-Math.PI / 2);
    const material = new THREE.MeshStandardMaterial({ color: warm, roughness: 0.8, transparent: true, opacity: 0.38, depthWrite: false });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.y = y - 0.15;
    mesh.receiveShadow = true; scene.add(mesh);
    const edgeGeometry = new THREE.EdgesGeometry(geometry, 30);
    const edgeMaterial = new THREE.LineBasicMaterial({ color: line, transparent: true, opacity: 0.6 });
    const edges = new THREE.LineSegments(edgeGeometry, edgeMaterial);
    edges.position.copy(mesh.position); scene.add(edges);
    geometries.push(geometry, edgeGeometry); materials.push(material, edgeMaterial);
  }

  const groundGeometry = new THREE.PlaneGeometry(40, 40);
  const groundMaterial = new THREE.ShadowMaterial({ color: line, opacity: 0.16 });
  const ground = new THREE.Mesh(groundGeometry, groundMaterial);
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.5; ground.receiveShadow = true;
  scene.add(ground); geometries.push(groundGeometry); materials.push(groundMaterial);

  graphLayers.forEach((layer, index) => {
    surface(layer.y);
    label(layer.label, new THREE.Vector3(-5.4, layer.y + 0.16, 4), index);
    const connections: { from: THREE.Vector3; to: THREE.Vector3 }[] = [];
    if (index > 0) {
      const id = graphLayers[index - 1].path.at(-1)!;
      connections.push({ from: point(id, index - 1), to: point(id, index) });
    }
    layer.path.slice(1).forEach((id, i) => connections.push({ from: point(layer.path[i], index), to: point(id, index) }));
    connections.forEach((connection, i) => tube(connection.from, connection.to, index + 0.12 + i * 0.76 / connections.length, index + 0.12 + (i + 1) * 0.76 / connections.length));
    for (const [a, b] of graphLinks(layer)) {
      const geometry = new THREE.BufferGeometry().setFromPoints([point(a, index), point(b, index)]);
      const material = new THREE.LineBasicMaterial({ color: line, transparent: true, opacity: 0.65 });
      scene.add(new THREE.Line(geometry, material)); geometries.push(geometry); materials.push(material);
      baseEdges.push({ material, layer: index });
    }
    for (const id of layer.ids) {
      const geometry = new THREE.SphereGeometry(0.155, 24, 16);
      const material = new THREE.MeshStandardMaterial({ color: cream, roughness: 0.3, metalness: 0.03 });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.copy(point(id, index)); mesh.castShadow = true; mesh.receiveShadow = true; scene.add(mesh);
      const pathIndex = layer.path.indexOf(id);
      const reached = pathIndex < 0 ? Infinity : index === 0 && pathIndex === 0 ? 0 : index + 0.12 + (pathIndex + (index > 0 ? 1 : 0)) * 0.76 / connections.length;
      geometries.push(geometry); materials.push(material); nodes.push({ mesh, layer: index, id, reached });
      if (pathIndex >= 0) label(graphProducts.find((item) => item.id === id)!.label, point(id, index).add(new THREE.Vector3(0, 0.52, 0)), index, reached, id);
    }
  });

  const markerGeometry = new THREE.TorusGeometry(0.27, 0.025, 8, 48);
  const markerMaterial = new THREE.MeshBasicMaterial({ color: maroon });
  const marker = new THREE.Mesh(markerGeometry, markerMaterial);
  marker.rotation.x = Math.PI / 2;
  geometries.push(markerGeometry); materials.push(markerMaterial); scene.add(marker);

  function render() {
    frame = 0;
    if (disposed) return;
    renderer.render(scene, camera);
    for (let index = 0; index < textLabels.length; index++) {
      const item = textLabels[index];
      projected.copy(item.position).project(camera);
      const visible = projected.z > -1 && projected.z < 1 && projected.y > -0.9 && projected.y < 0.95 && (!item.id || item.layer === activeStep && progress >= item.reached);
      item.element.hidden = !visible;
      item.visible = visible;
      if (visible) {
        const x = THREE.MathUtils.clamp((projected.x + 1) * width / 2, item.width / 2 + 8, width - item.width / 2 - 8);
        let y = (1 - projected.y) * height / 2;
        // Move a label above earlier labels when a narrow or rotated view
        // projects several connected products into the same small area.
        for (let attempt = 0; attempt < index; attempt++) {
          let overlap = false;
          for (let previous = 0; previous < index; previous++) {
            const other = textLabels[previous];
            if (other.visible && Math.abs(other.x - x) < (other.width + item.width) / 2 + 4 && Math.abs(other.y - y) < 28) { overlap = true; break; }
          }
          if (!overlap) break;
          y -= 28;
        }
        item.x = x; item.y = y;
        item.element.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`;
        item.element.dataset.active = String(item.id ? item.id === selected : item.layer === activeStep);
      }
    }
  }
  function schedule() { if (!frame && !disposed) frame = requestAnimationFrame(render); }
  function reset() { camera.position.copy(defaultCamera); controls.target.copy(defaultTarget); controls.update(); schedule(); }
  function rotate(horizontal: number, vertical = 0) { controls.rotateLeft(horizontal); controls.rotateUp(vertical); controls.update(); schedule(); }
  function zoom(factor: number) {
    offset.copy(camera.position).sub(controls.target);
    offset.setLength(THREE.MathUtils.clamp(offset.length() * factor, 13, 36));
    camera.position.copy(controls.target).add(offset); controls.update(); schedule();
  }
  function keydown(event: KeyboardEvent) {
    if (!event.key.startsWith("Arrow")) return;
    event.preventDefault(); onInteract();
    rotate(event.key === "ArrowLeft" ? 0.16 : event.key === "ArrowRight" ? -0.16 : 0, event.key === "ArrowUp" ? 0.12 : event.key === "ArrowDown" ? -0.12 : 0);
  }
  function lost(event: Event) { event.preventDefault(); onLost(); }
  canvas.addEventListener("keydown", keydown); canvas.addEventListener("webglcontextlost", lost);
  controls.addEventListener("start", onInteract);
  controls.addEventListener("change", schedule);
  const observer = new ResizeObserver(() => {
    width = Math.max(host.clientWidth, 1); height = Math.max(host.clientHeight, 1);
    camera.aspect = width / height; camera.zoom = Math.min(1.12, camera.aspect / (width < 600 ? 1.1 : 1.35));
    for (const item of textLabels) { item.element.hidden = false; item.width = item.element.offsetWidth; }
    camera.updateProjectionMatrix(); renderer.setSize(width, height); schedule();
  });
  observer.observe(host); reset();

  function setProgress(value: number, followCamera = false) {
    progress = THREE.MathUtils.clamp(value, 0, 3);
    activeStep = Math.min(2, Math.max(0, Math.ceil(progress) - 1));
    marker.position.copy(nodes[0].mesh.position);
    for (const path of paths) {
      const portion = THREE.MathUtils.clamp((progress - path.start) / (path.end - path.start), 0, 1);
      path.mesh.visible = portion > 0;
      if (!path.mesh.visible) continue;
      pathPosition.lerpVectors(path.from, path.to, portion);
      path.mesh.position.copy(path.from).add(pathPosition).multiplyScalar(0.5);
      path.mesh.scale.set(1, path.length * portion, 1);
      marker.position.copy(pathPosition);
    }
    for (const node of nodes) {
      const reached = progress >= node.reached;
      const highlighted = node.layer === 2 && node.id === selected;
      node.mesh.material.color.copy(reached ? maroon : cream);
      node.mesh.scale.setScalar(highlighted ? 1.9 : reached ? 1.3 : 1);
      if (highlighted) marker.position.copy(node.mesh.position);
    }
    marker.position.y += 0.02;
    for (const edge of baseEdges) edge.material.opacity = edge.layer === activeStep ? 0.8 : 0.45;
    if (followCamera) {
      const amount = (1 - Math.cos(progress / 3 * Math.PI)) / 2;
      camera.position.lerpVectors(defaultCamera, closeCamera, amount);
      controls.target.lerpVectors(defaultTarget, closeTarget, amount);
      controls.update();
    }
    schedule();
  }
  function highlight(id: string | null) { selected = id; setProgress(progress); }
  setProgress(0);
  return { setProgress, setStep(step: number) { setProgress(step + 1); activeStep = step; schedule(); }, highlight, reset, rotate, zoom, dispose() {
    if (disposed) return;
    disposed = true; cancelAnimationFrame(frame); observer.disconnect();
    canvas.removeEventListener("keydown", keydown); canvas.removeEventListener("webglcontextlost", lost);
    controls.removeEventListener("start", onInteract); controls.removeEventListener("change", schedule);
    controls.dispose(); geometries.forEach((item) => item.dispose()); materials.forEach((item) => item.dispose());
    renderer.dispose(); renderer.forceContextLoss(); canvas.remove(); labels.remove();
  } };
}
