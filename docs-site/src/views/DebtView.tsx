import debtJson from '../../content/debt.json';
import { componentById, ui } from '../content/load';
import type { DebtItem } from '../content/types';
import { githubUrl } from '../content/links';
import { useT } from '../i18n/lang';
import { useNavigate, useRoute } from '../router/Router';

const items = (debtJson as unknown as { items: DebtItem[] }).items;
const ORDER: DebtItem['severity'][] = ['unbuilt', 'unvalidated', 'temporary'];

export function DebtView() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();

  return (
    <div className="view">
      <h2>{t(ui.debt.heading)}</h2>
      <p className="lede">{t(ui.debt.intro)}</p>

      {ORDER.map((severity) => {
        const group = items.filter((i) => i.severity === severity);
        if (group.length === 0) return null;
        return (
          <section key={severity} className="debt__group">
            <h3>{t(ui.debt[severity])}</h3>
            <ul className="debt__list">
              {group.map((item) => (
                <li key={item.id} className="debt__item" data-severity={severity}>
                  <h4>{t(item.title)}</h4>
                  <p>{t(item.body)}</p>
                  <p className="debt__affects">
                    <span>{`${t(ui.debt.affects)}: `}</span>
                    {item.components.map((id) => {
                      const component = componentById.get(id);
                      return component ? (
                        <button
                          type="button"
                          key={id}
                          className="chip"
                          onClick={() =>
                            navigate({ segments: ['component', id], query: route.query })
                          }
                        >
                          {t(component.title)}
                        </button>
                      ) : null;
                    })}
                  </p>
                  <p className="debt__source">{t(item.source.note)}</p>
                  <a
                    className="link mono"
                    href={githubUrl(item.source.file, item.source.start, item.source.end)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {`${item.source.file}:${item.source.start}`}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
