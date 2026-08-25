export type Route = { segments: string[]; query: Record<string, string> };

/** Segments that open a panel as a `key/value` pair; Escape pops one such pair. */
const PANEL_KEYS = new Set(['fn', 'edge', 'store', 'item']);

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '');
  const [pathPart, queryPart] = raw.split('?');
  const segments = pathPart.split('/').filter(Boolean);
  const query: Record<string, string> = {};
  for (const [k, v] of new URLSearchParams(queryPart ?? '')) query[k] = v;
  return { segments, query };
}

export function formatHash(route: Route): string {
  const path = route.segments.join('/');
  const params = new URLSearchParams(route.query).toString();
  return `#/${path}${params ? `?${params}` : ''}`;
}

/**
 * One level up, or null at a top-level view.
 *
 * Escape must pop exactly one layer per press, and the route — not a
 * mount-order stack — is the authority: a panel still playing its exit
 * transition is mounted, and a stack would let it swallow the next key.
 */
export function parentRoute(route: Route): Route | null {
  const s = route.segments;
  if (s.length >= 2 && PANEL_KEYS.has(s[s.length - 2])) {
    return { segments: s.slice(0, -2), query: route.query };
  }
  return null;
}
