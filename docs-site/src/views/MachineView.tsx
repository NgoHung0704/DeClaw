import machineJson from '../../content/machine.json';
import { relatedComponents, ticketById, tickets, ui } from '../content/load';
import type { Machine } from '../content/types';
import { useT } from '../i18n/lang';
import { Diagram } from '../diagram/Diagram';
import { useNavigate, useRoute } from '../router/Router';

const machine = machineJson as unknown as Machine;

export function MachineView() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const ticketId = route.query.ticket;
  const ticket = ticketId ? ticketById.get(ticketId) : undefined;

  // The union of all three relations. Narrowing this to creates+modifies makes
  // a ticket's request render as a pipeline that stops in the middle, because
  // components it calls but never edited would stay dimmed.
  const related = ticket ? relatedComponents(ticket) : null;

  const dimmed = new Set(
    related
      ? machine.nodes
          // Structural nodes — the gate, the intake ports — belong to no
          // component. Dimming them hides the very branch the reader is
          // following, so only component-backed parts can dim.
          .filter((n) => n.component !== undefined && !related.has(n.component))
          .map((n) => n.id)
      : [],
  );

  return (
    <div className="view">
      <h2>{t(ui.machine.heading)}</h2>
      <p className="lede">{t(ui.machine.intro)}</p>

      <div className="filters">
        <label className="filters__field">
          <span>{t(ui.components.filterTicket)}</span>
          <select
            value={ticketId ?? ''}
            onChange={(e) => {
              const query = { ...route.query };
              if (e.target.value) query.ticket = e.target.value;
              else delete query.ticket;
              navigate({ segments: ['machine'], query }, { replace: true });
            }}
          >
            <option value="">{t(ui.machine.noTicket)}</option>
            {tickets.map((x) => (
              <option key={x.id} value={x.id}>
                {`${x.id} — ${t(x.title)}`}
              </option>
            ))}
          </select>
        </label>
      </div>

      {ticket && (
        <ul className="legend">
          <li>{`${t(ui.machine.legendCreates)}: ${ticket.creates.join(', ') || '—'}`}</li>
          <li>{`${t(ui.machine.legendModifies)}: ${ticket.modifies.join(', ') || '—'}`}</li>
          <li>{`${t(ui.machine.legendTraverses)}: ${ticket.traverses.join(', ') || '—'}`}</li>
        </ul>
      )}

      <Diagram
        nodes={machine.nodes.map((n) => ({
          id: n.id,
          label: n.label,
          kind: n.kind,
          x: n.x,
          y: n.y,
          w: n.w,
          h: n.h,
        }))}
        edges={machine.edges}
        dimmed={dimmed}
        onSelect={() => {}}
        canvas={machine.canvas}
        label={t(ui.machine.heading)}
      />
    </div>
  );
}
