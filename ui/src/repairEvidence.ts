const SEARCH_EVENT_ID_SHAPE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether a pasted string has the shape of a `search_event_id`.
 *
 * A UUID shape, not a v4-specific one: the service issues v4 ids, but this check
 * exists to reject obvious typos and prose before spending a request, not to
 * re-validate what the database will validate anyway.
 */
export function isPlausibleSearchEventId(value: string): boolean {
  return SEARCH_EVENT_ID_SHAPE.test(value.trim());
}
