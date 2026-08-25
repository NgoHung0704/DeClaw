import { describe, expect, it } from 'vitest';
import { formatHash, parentRoute, parseHash } from '../../src/router/route';

describe('route parsing', () => {
  it('reads segments and query', () => {
    const r = parseHash('#/component/tool-registry/fn/langchain_tools?lang=vi');
    expect(r.segments).toEqual(['component', 'tool-registry', 'fn', 'langchain_tools']);
    expect(r.query.lang).toBe('vi');
  });

  it('treats an empty hash as the root route', () => {
    expect(parseHash('').segments).toEqual([]);
  });

  it('round-trips', () => {
    const hash = '#/components?phase=8&lang=en';
    expect(formatHash(parseHash(hash))).toBe(hash);
  });
});

describe('parentRoute pops exactly one panel level', () => {
  it('pops a function panel off a component route', () => {
    const r = parseHash('#/component/tool-registry/fn/langchain_tools');
    expect(parentRoute(r)!.segments).toEqual(['component', 'tool-registry']);
  });

  it('pops an edge panel off the map route', () => {
    const r = parseHash('#/map/edge/host-plugin');
    expect(parentRoute(r)!.segments).toEqual(['map']);
  });

  it('preserves the query when popping, so language survives Escape', () => {
    const r = parseHash('#/map/edge/host-plugin?lang=vi');
    expect(parentRoute(r)!.query.lang).toBe('vi');
  });

  it('returns null at a top-level view, so Escape does nothing there', () => {
    expect(parentRoute(parseHash('#/map'))).toBeNull();
    expect(parentRoute(parseHash(''))).toBeNull();
  });
});
