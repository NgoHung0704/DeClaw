import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { formatHash, parentRoute, parseHash, type Route } from './route';

type NavOptions = { replace?: boolean };
type RouterValue = { route: Route; navigate: (r: Route, o?: NavOptions) => void };

const RouterContext = createContext<RouterValue | null>(null);

export function useRoute(): Route {
  return useContext(RouterContext)!.route;
}

export function useNavigate(): (r: Route, o?: NavOptions) => void {
  return useContext(RouterContext)!.navigate;
}

export function RouterProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  // Depths this router pushed itself. Escape can then use history.back() —
  // which keeps history from growing — and fall back to a replacing
  // navigation for a visitor who arrived by deep link, whose first Back
  // press would otherwise leave the site.
  const pushedDepths = useRef<Set<number>>(new Set());
  const lastTrigger = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const navigate = useCallback((next: Route, opts?: NavOptions) => {
    lastTrigger.current = document.activeElement as HTMLElement | null;
    const hash = formatHash(next);
    if (opts?.replace) {
      window.history.replaceState(null, '', hash);
      setRoute(next);
      return;
    }
    pushedDepths.current.add(next.segments.length);
    window.location.hash = hash;
    setRoute(next);
  }, []);

  // The ONLY Escape listener in the app. stopPropagation does not separate
  // listeners bound to the same target, so per-panel document listeners would
  // close every open panel at once and push several history entries.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      const current = parseHash(window.location.hash);
      const parent = parentRoute(current);
      if (!parent) return;
      event.preventDefault();
      const depth = current.segments.length;
      const trigger = lastTrigger.current;
      if (pushedDepths.current.has(depth)) {
        pushedDepths.current.delete(depth);
        window.history.back();
        // jsdom and some browsers apply the popstate asynchronously; keep the
        // rendered route in step immediately so one Escape is one layer.
        window.history.replaceState(null, '', formatHash(parent));
        setRoute(parent);
      } else {
        window.history.replaceState(null, '', formatHash(parent));
        setRoute(parent);
      }
      window.setTimeout(() => trigger?.focus(), 0);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  // Move focus into a panel when one opens, so keyboard users are not left
  // behind at the trigger while the content changes elsewhere.
  const depth = route.segments.length;
  const previousDepth = useRef(depth);
  useLayoutEffect(() => {
    if (depth > previousDepth.current) {
      const panels = document.querySelectorAll<HTMLElement>('[data-panel-heading]');
      panels[panels.length - 1]?.focus();
    }
    previousDepth.current = depth;
  }, [depth]);

  return <RouterContext.Provider value={{ route, navigate }}>{children}</RouterContext.Provider>;
}
