import { components, relatedComponents, ticketById, tickets, ui } from '../content/load';
import { useT } from '../i18n/lang';
import { useNavigate, useRoute } from '../router/Router';

export function ComponentsView() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();

  const phaseFilter = route.query.phase;
  const ticketFilter = route.query.ticket;

  // All three relations count. `creates` alone leaves tickets owning nothing,
  // and creates+modifies makes a ticket look like a pipeline that stops
  // mid-way, because a component it calls but never edited stays dark.
  const related = ticketFilter
    ? relatedComponents(ticketById.get(ticketFilter) ?? { creates: [], modifies: [], traverses: [] } as never)
    : null;

  const phases = [...new Set(tickets.map((x) => x.phase))].sort();
  const visibleTickets = phaseFilter ? tickets.filter((x) => x.phase === phaseFilter) : tickets;

  const setQuery = (patch: Record<string, string | undefined>) => {
    const query = { ...route.query };
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) delete query[k];
      else query[k] = v;
    }
    navigate({ segments: ['components'], query }, { replace: true });
  };

  const groups = [...new Set(components.map((c) => c.group))];

  return (
    <div className="view">
      <h2>{t(ui.components.heading)}</h2>
      <p className="lede">{t(ui.components.intro)}</p>

      <div className="filters">
        <label className="filters__field">
          <span>{t(ui.components.filterPhase)}</span>
          <select
            value={phaseFilter ?? ''}
            onChange={(e) => setQuery({ phase: e.target.value || undefined, ticket: undefined })}
          >
            <option value="">{t(ui.components.all)}</option>
            {phases.map((p) => (
              <option key={p} value={p}>
                {t(tickets.find((x) => x.phase === p)!.phaseTitle)}
              </option>
            ))}
          </select>
        </label>

        <label className="filters__field">
          <span>{t(ui.components.filterTicket)}</span>
          <select
            value={ticketFilter ?? ''}
            onChange={(e) => setQuery({ ticket: e.target.value || undefined })}
          >
            <option value="">{t(ui.components.all)}</option>
            {visibleTickets.map((x) => (
              <option key={x.id} value={x.id}>
                {`${x.id} — ${t(x.title)}`}
              </option>
            ))}
          </select>
        </label>

        {(phaseFilter || ticketFilter) && (
          <button type="button" className="button" onClick={() => setQuery({ phase: undefined, ticket: undefined })}>
            {t(ui.components.clearFilter)}
          </button>
        )}
      </div>

      {groups.map((group) => (
        <section className="group" key={group}>
          <h3 className="group__title">{group}</h3>
          <ul className="grid">
            {components
              .filter((c) => c.group === group)
              .map((component) => {
                const dimmed = related ? !related.has(component.id) : false;
                return (
                  <li
                    key={component.id}
                    className="card"
                    data-component-card={component.id}
                    data-dimmed={dimmed ? 'true' : 'false'}
                    style={{ opacity: dimmed ? 0.35 : 1 }}
                  >
                    <button
                      type="button"
                      className="card__button"
                      onClick={() =>
                        navigate({ segments: ['component', component.id], query: route.query })
                      }
                    >
                      <span className="card__title">{t(component.title)}</span>
                      <span className="card__summary">{t(component.summary)}</span>
                      <span className="card__meta">
                        {`${component.modules.length} ${t(ui.components.moduleCount)} · ${
                          component.tier === 'A' ? t(ui.components.tierA) : t(ui.components.tierB)
                        }`}
                      </span>
                    </button>
                  </li>
                );
              })}
          </ul>
        </section>
      ))}
    </div>
  );
}
