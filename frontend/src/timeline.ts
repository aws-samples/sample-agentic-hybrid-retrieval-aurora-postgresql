// Pure derivation for the Proof > Timeline lens (SPEC-session Section 6.0). Kept
// free of React and the DOM so the placement, day-bucketing, and hot-day logic
// can be executed and verified in isolation (same discipline as route.ts).
//
// The lens teaches that the cited evidence set has two independently
// reconstructable orderings: rank order (retrieval) and chronological order.
// This module produces the chronological grid: source-system lanes crossed with
// calendar-day columns, plus a sequence index that stitches events in the order
// they actually happened.

export interface TimelineEventInput {
  evidence_id?: string;
  external_key?: string;
  evidence_kind?: string;
  title?: string;
  source_system?: string;
  occurred_at?: string | null;
}

export interface PlacedEvent<E extends TimelineEventInput = TimelineEventInput> {
  event: E;
  row: number; // 1-based CSS grid row: lane index + 2 (row 1 is the day header).
  col: number; // 1-based CSS grid column: day index + 2 (col 1 is the lane label).
  seq: number; // 1-based chronological position; drives the stitch-thread order.
}

export interface TimelineLane {
  system: string;
  label: string;
}

export interface TimelineDay {
  key: string; // YYYY-MM-DD (UTC), stable across timezones and test runners.
  label: string;
  count: number;
  hot: boolean;
}

export interface TimelineGrid<E extends TimelineEventInput = TimelineEventInput> {
  lanes: TimelineLane[];
  days: TimelineDay[];
  placed: PlacedEvent<E>[];
  hotDayKey: string | null;
  undated: E[]; // events with no occurred_at: shown in the list, not on the grid.
}

/**
 * Turn a raw source_system value into a projector-legible label. Derived from
 * the real value (never a hardcoded system list), so an unrecognized system
 * degrades to a cleaned title-case string rather than dropping off the grid.
 */
export function systemLabel(raw?: string | null): string {
  if (!raw) return 'Unknown';
  const cleaned = raw.replace(/_/g, ' ').trim();
  if (!cleaned) return 'Unknown';
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

// Day bucketing uses UTC so the same payload yields the same columns regardless
// of the presenter's timezone (and so the node verification is deterministic).
function dayKey(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().slice(0, 10);
}

function dayLabel(key: string): string {
  const parsed = new Date(`${key}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return key;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(parsed);
}

/**
 * Place chronologically-ordered timeline events onto a system-lane x day grid.
 *
 * Events are expected pre-sorted by (occurred_at, external_key) as the API
 * returns them, so the array index is the true chronological order and becomes
 * each event's stitch sequence. Lanes appear in first-seen order; day columns in
 * chronological order. A day is marked hot only when it holds a strict maximum of
 * events (more than one, and no tie) so the busiest-day tint never fabricates
 * emphasis on an all-tied run.
 */
export function buildTimelineGrid<E extends TimelineEventInput>(
  events: E[],
): TimelineGrid<E> {
  const dated = events.filter((event) => event.occurred_at);
  const undated = events.filter((event) => !event.occurred_at);

  const laneOrder: string[] = [];
  for (const event of dated) {
    const system = event.source_system || 'unknown';
    if (!laneOrder.includes(system)) laneOrder.push(system);
  }
  const lanes = laneOrder.map((system) => ({ system, label: systemLabel(system) }));

  const dayOrder: string[] = [];
  const dayCount = new Map<string, number>();
  for (const event of dated) {
    const key = dayKey(event.occurred_at as string);
    if (!dayCount.has(key)) {
      dayOrder.push(key);
      dayCount.set(key, 0);
    }
    dayCount.set(key, (dayCount.get(key) as number) + 1);
  }

  let maxCount = 0;
  for (const key of dayOrder) {
    maxCount = Math.max(maxCount, dayCount.get(key) as number);
  }
  const leaders = dayOrder.filter((key) => dayCount.get(key) === maxCount);
  const hotDayKey = maxCount > 1 && leaders.length === 1 ? leaders[0] : null;

  const days = dayOrder.map((key) => ({
    key,
    label: dayLabel(key),
    count: dayCount.get(key) as number,
    hot: key === hotDayKey,
  }));

  const placed = dated.map((event, index) => {
    const system = event.source_system || 'unknown';
    const key = dayKey(event.occurred_at as string);
    return {
      event,
      row: laneOrder.indexOf(system) + 2,
      col: dayOrder.indexOf(key) + 2,
      seq: index + 1,
    };
  });

  return { lanes, days, placed, hotDayKey, undated };
}
