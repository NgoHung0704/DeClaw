import { relatedComponents, ticketById, tickets, ui } from '../content/load';
import { useT } from '../i18n/lang';
import { MachineDiagram, machineContent } from '../diagram/Machine';
import { useNavigate, useRoute } from '../router/Router';

export function MachineView() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();

  const ticketId = route.query.ticket;
  const ticket = ticketId ? ticketById.get(ticketId) : undefined;
  const openPart = route.query.part ?? null;

  // The union of all three relations. Narrowing it to creates+modifies renders
  // a ticket's work as though it stopped mid-machine, because a part it drove
  // but never edited would stay dark.
  const related = ticket ? relatedComponents(ticket) : null;

  const setQuery = (patch: Record<string, string | undefined>) => {
    const query = { ...route.query };
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) delete query[k];
      else query[k] = v;
    }
    navigate({ segments: ['machine'], query }, { replace: true });
  };

  const openedPart = openPart ? machineContent.parts.find((p) => p.id === openPart) ?? null : null;

  return (
    <div className="view">
      <h2>{t(ui.machine.heading)}</h2>
      <p className="lede">{t(ui.machine.intro)}</p>

      <div className="filters">
        <label className="filters__field">
          <span>{t(ui.components.filterTicket)}</span>
          <select
            value={ticketId ?? ''}
            onChange={(e) => setQuery({ ticket: e.target.value || undefined })}
          >
            <option value="">{t(ui.machine.noTicket)}</option>
            {tickets.map((x) => (
              <option key={x.id} value={x.id}>
                {`${x.id} — ${t(x.title)}`}
              </option>
            ))}
          </select>
        </label>
        {ticket && (
          <ul className="legend">
            <li>{`${t(ui.machine.legendCreates)}: ${ticket.creates.join(', ') || '—'}`}</li>
            <li>{`${t(ui.machine.legendModifies)}: ${ticket.modifies.join(', ') || '—'}`}</li>
            <li>{`${t(ui.machine.legendTraverses)}: ${ticket.traverses.join(', ') || '—'}`}</li>
          </ul>
        )}
      </div>

      <MachineDiagram
        dimmedComponents={related}
        openPart={openPart}
        onOpenPart={(id) => setQuery({ part: id ?? undefined })}
        onOpenComponent={(componentId) =>
          navigate({ segments: ['component', componentId], query: route.query })
        }
      />

      {openedPart && (
        <section className="partdetail">
          <h3>{t(openedPart.label)}</h3>
          <p className="lede">{t(openedPart.note)}</p>
          <button
            type="button"
            className="button"
            onClick={() =>
              navigate({ segments: ['component', openedPart.component], query: route.query })
            }
          >
            {t(ui.machine.openComponent)}
          </button>
          <ul className="modules">
            {openedPart.subparts.map((sub) => (
              <li key={sub.id} className="mono">
                {sub.path}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
