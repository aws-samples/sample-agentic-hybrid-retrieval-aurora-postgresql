// Hash-based route contract (SPEC 6.0, gate G-23). Pure functions with no DOM
// dependency beyond the hash string, so the gate executes this module directly
// under node --experimental-strip-types instead of maintaining a Python twin.
//
// Hash routing (not History-API paths) is deliberate: the built frontend is
// served under an environment-supplied base path (VITE_BASE_PATH) behind a
// front-door proxy this repo does not own, with no SPA-fallback rewrite. A path
// router would 404 on refresh or a pasted deep link; a fragment never reaches
// any server, so #/retrieval?preset=exact survives refresh under every topology.

// The .ts extension here is required, not stylistic: gate G-23 executes this
// module directly under `node --experimental-strip-types`, and Node's ESM
// resolver (unlike Vite's bundler resolution) does not infer extensions on
// relative specifiers.
import { type PersonaKey, isPersonaKey } from './persona.ts';

export type RouteSurface =
  | 'overview'
  | 'retrieval'
  | 'agent'
  | 'proof'
  | 'corpus'
  | 'evaluation'
  | 'health';

export type PresetKey = 'exact' | 'fuzzy' | 'semantic';
export type { PersonaKey };

export interface Route {
  surface: RouteSurface;
  lens?: string;
  preset?: PresetKey;
  role?: PersonaKey;
  runId?: string;
}

// Lenses each surface accepts as sub-navigation. The first entry is the default
// (emitted with no ?lens= param) so the canonical contract routes stay bare.
export const SURFACE_LENSES: Record<RouteSurface, readonly string[]> = {
  overview: [],
  retrieval: ['results', 'fusion'],
  agent: ['answer', 'graph'],
  proof: ['receipt', 'replay', 'timeline'],
  corpus: [],
  evaluation: [],
  health: [],
};

export const SURFACES = Object.keys(SURFACE_LENSES) as RouteSurface[];
export const PRESET_KEYS: readonly PresetKey[] = ['exact', 'fuzzy', 'semantic'];

function isSurface(value: string): value is RouteSurface {
  return (SURFACES as string[]).includes(value);
}

function readLens(surface: RouteSurface, params: URLSearchParams): string | undefined {
  const lens = params.get('lens');
  if (lens && SURFACE_LENSES[surface].includes(lens)) return lens;
  return undefined;
}

function readPreset(params: URLSearchParams): PresetKey | undefined {
  const preset = params.get('preset');
  return preset && (PRESET_KEYS as string[]).includes(preset)
    ? (preset as PresetKey)
    : undefined;
}

function readRole(params: URLSearchParams): PersonaKey | undefined {
  const role = params.get('role');
  return role && isPersonaKey(role) ? role : undefined;
}

/**
 * Parse a location hash into a Route. Tolerant by contract: an unknown surface,
 * lens, preset, or role is dropped rather than throwing, so a stale or
 * hand-mangled deep link degrades to the nearest valid surface instead of a
 * blank screen.
 */
export function parseRoute(hash: string): Route {
  const raw = hash.replace(/^#/, '').replace(/^\/+/, '');
  const [path, queryString = ''] = raw.split('?');
  const segments = path.split('/').filter(Boolean);
  const params = new URLSearchParams(queryString);

  const head = segments[0] ?? '';
  if (!head || !isSurface(head)) return { surface: 'overview' };

  const surface = head;
  const route: Route = { surface };

  const lens = readLens(surface, params);
  if (lens) route.lens = lens;

  if (surface === 'retrieval') {
    const preset = readPreset(params);
    if (preset) route.preset = preset;
  } else if (surface === 'agent') {
    const role = readRole(params);
    if (role) route.role = role;
  } else if (surface === 'proof') {
    const runId = segments[1] ? decodeURIComponent(segments[1]) : undefined;
    if (runId) route.runId = runId;
  }

  return route;
}

/**
 * Format a Route back into a location hash. The inverse of parseRoute for every
 * canonical contract route: formatRoute(parseRoute(url)) === url. Query params
 * are emitted in a fixed order (preset, role, lens) so the encoding is
 * deterministic and round-trip stable.
 */
export function formatRoute(route: Route): string {
  let path = `/${route.surface}`;
  if (route.surface === 'proof' && route.runId) {
    path += `/${encodeURIComponent(route.runId)}`;
  }

  const params = new URLSearchParams();
  if (route.surface === 'retrieval' && route.preset) {
    params.set('preset', route.preset);
  }
  if (route.surface === 'agent' && route.role) {
    params.set('role', route.role);
  }
  const lenses = SURFACE_LENSES[route.surface];
  if (route.lens && lenses.includes(route.lens) && lenses[0] !== route.lens) {
    params.set('lens', route.lens);
  }

  const query = params.toString();
  return `#${path}${query ? `?${query}` : ''}`;
}
