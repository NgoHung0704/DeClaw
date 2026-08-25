// React Testing Library only auto-cleans when a global afterEach exists.
// Without this, renders accumulate across tests and queries find duplicates.
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(cleanup);

// jsdom ships no matchMedia, and the reduced-motion hook reads it on every
// render. Default to "no preference" so tests exercise the animated path — the
// one a reader without an accessibility setting actually sees.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
