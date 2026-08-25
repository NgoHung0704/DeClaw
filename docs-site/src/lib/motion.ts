import { useSyncExternalStore } from 'react';
import type { Transition } from 'motion/react';

/** One spring for the whole site, so panels and nodes settle the same way. */
export const spring: Transition = { type: 'spring', stiffness: 420, damping: 38, mass: 0.9 };

/** Expo-out: fast start, long settle. The site's default for anything drawn. */
export const easeOut = [0.16, 1, 0.3, 1] as const;

const QUERY = '(prefers-reduced-motion: reduce)';

/** True when the reader has asked the system for less movement. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(QUERY);
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    () => window.matchMedia(QUERY).matches,
    () => false,
  );
}
