# Shared UI primitives
React 19 + Motion, custom components, no UI library.
## `docs-site/src/components/Panel.tsx`
```
import { useEffect, useRef, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { spring, useReducedMotion } from '../lib/motion';
import { useT } from '../i18n/lang';
import { ui } from '../content/load';
import { useNavigate, useRoute } from '../router/Router';
import { parentRoute } from '../router/route';

const FOCUSABLE =
  'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * A side panel over a scrim.
 *
 * Escape is deliberately NOT handled here. Panels stack, every instance would
 * listen on `document`, and `stopPropagation` does nothing between listeners on
 * the same target — one keypress would close the whole stack. Closing is a
 * route change and the router owns Escape. Tab is different: scoping it to the
 * panel that currently holds focus is correct for a stack with no coordination.
 */
export function Panel(props: { title: string; children: ReactNode }) {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const reduced = useReducedMotion();
  const panelRef = useRef<HTMLDivElement>(null);
  const parent = parentRoute(route);

  const close = () => {
    if (parent) navigate(parent, { replace: true });
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !panelRef.current) return;
      if (!panelRef.current.contains(document.activeElement)) return;
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <>
      <motion.div
        className="panel__scrim"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={close}
      />
      <motion.aside
        ref={panelRef}
        className="panel"
        role="dialog"
        aria-modal="true"
        aria-label={props.title}
        initial={reduced ? { opacity: 0 } : { opacity: 0, x: 44 }}
        animate={reduced ? { opacity: 1 } : { opacity: 1, x: 0 }}
        exit={reduced ? { opacity: 0 } : { opacity: 0, x: 44 }}
        transition={spring}
      >
        <header className="panel__bar">
          <h2 className="panel__title" data-panel-heading tabIndex={-1}>
            {props.title}
          </h2>
          <button type="button" className="panel__close" onClick={close}>
            {t(ui.contract.close)}
          </button>
        </header>
        <div className="panel__body">{props.children}</div>
      </motion.aside>
    </>
  );
}

```

## `docs-site/src/diagram/CompanionList.tsx`
```
import { useT } from '../i18n/lang';
import { ui } from '../content/load';
import type { Loc } from '../content/types';

export type ListNode = { id: string; label: Loc; kind: string };
export type ListEdge = { id: string; from: string; to: string; label: Loc };

/**
 * The diagram's text equivalent, and its keyboard surface.
 *
 * It is always rendered — never a collapsed fallback — because a diagram that
 * is aria-hidden with an incomplete substitute is worse than no diagram: a
 * function list carries no edge labels and no gate branch labels, so all the
 * branching logic disappears. Building this from the same records as the SVG
 * makes losing a label impossible.
 */
export function CompanionList(props: {
  nodes: ListNode[];
  edges: ListEdge[];
  onSelect: (kind: 'node' | 'edge', id: string) => void;
  dimmed?: Set<string>;
}) {
  const t = useT();
  const labelOf = (id: string) => {
    const node = props.nodes.find((n) => n.id === id);
    return node ? t(node.label) : id;
  };
  return (
    <div className="companion">
      <h3 className="companion__title">{t(ui.diagram.companionTitle)}</h3>
      <p className="companion__hint">{t(ui.diagram.companionHint)}</p>
      <ul className="companion__list">
        {props.nodes.map((node) => (
          <li key={node.id}>
            <button
              type="button"
              className="companion__button"
              data-kind={node.kind}
              data-dimmed={props.dimmed?.has(node.id) ? 'true' : 'false'}
              onClick={() => props.onSelect('node', node.id)}
            >
              {t(node.label)}
            </button>
          </li>
        ))}
        {props.edges.map((edge) => (
          <li key={edge.id}>
            <button
              type="button"
              className="companion__button companion__button--edge"
              onClick={() => props.onSelect('edge', edge.id)}
            >
              {`${labelOf(edge.from)} → ${labelOf(edge.to)}: ${t(edge.label)}`}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

```