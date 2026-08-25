import type { ReactNode } from 'react';
import { useT } from '../i18n/lang';
import { ui } from '../content/load';
import { useNavigate, useRoute } from '../router/Router';
import { parentRoute } from '../router/route';

/**
 * A side panel. It carries `data-panel-heading` so the router can move focus
 * into it, and its close button navigates to the parent route — the same
 * transition Escape performs, so there is one way to close a panel, not two.
 */
export function Panel(props: { title: string; children: ReactNode }) {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const parent = parentRoute(route);

  return (
    <aside className="panel">
      <div className="panel__bar">
        <h2 className="panel__title" data-panel-heading tabIndex={-1}>
          {props.title}
        </h2>
        <button
          type="button"
          className="panel__close"
          onClick={() => parent && navigate(parent, { replace: true })}
        >
          {t(ui.contract.close)}
        </button>
      </div>
      <div className="panel__body">{props.children}</div>
    </aside>
  );
}
