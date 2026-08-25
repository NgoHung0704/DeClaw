import { motion } from 'motion/react';
import { componentById, tickets, ui } from '../content/load';
import type { Ticket } from '../content/types';
import { easeOut, useReducedMotion } from '../lib/motion';
import { useT } from '../i18n/lang';
import { useNavigate, useRoute } from '../router/Router';

type Phase = {
  id: string;
  title: Ticket['phaseTitle'];
  tickets: Ticket[];
  components: string[];
};

function groupByPhase(): Phase[] {
  const byId = new Map<string, Phase>();
  for (const ticket of tickets) {
    const phase = byId.get(ticket.phase) ?? {
      id: ticket.phase,
      title: ticket.phaseTitle,
      tickets: [],
      components: [],
    };
    phase.tickets.push(ticket);
    for (const c of [...ticket.creates, ...ticket.modifies]) {
      if (!phase.components.includes(c)) phase.components.push(c);
    }
    byId.set(ticket.phase, phase);
  }
  return [...byId.values()].sort((a, b) => Number(a.id) - Number(b.id));
}

/**
 * The build in order, one band per phase.
 *
 * Phases are the spine of this project — each one gated the next — but they
 * were only visible before as a dropdown filter, which is a control, not an
 * explanation. Reading top to bottom should tell the story on its own.
 */
export function PhasesView() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const reduced = useReducedMotion();
  const phases = groupByPhase();

  return (
    <div className="view">
      <h2>{t(ui.phases.heading)}</h2>
      <p className="lede">{t(ui.phases.intro)}</p>

      <ol className="phases">
        {phases.map((phase, i) => {
          const done = phase.tickets.filter((x) => x.status === 'done').length;
          return (
            <motion.li
              key={phase.id}
              className="phase"
              initial={reduced ? { opacity: 0 } : { opacity: 0, y: 18 }}
              whileInView={reduced ? { opacity: 1 } : { opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-60px' }}
              transition={{ duration: reduced ? 0.2 : 0.5, delay: i * 0.05, ease: easeOut }}
            >
              <div className="phase__rail" aria-hidden="true">
                <span className="phase__dot" />
              </div>

              <div className="phase__body">
                <header className="phase__head">
                  <span className="phase__number">{phase.id}</span>
                  <h3 className="phase__title">{t(phase.title)}</h3>
                  <span className="phase__count">
                    {`${done}/${phase.tickets.length} ${t(ui.phases.ticketsDone)}`}
                  </span>
                </header>

                <ul className="phase__tickets">
                  {phase.tickets.map((ticket) => (
                    <li key={ticket.id}>
                      <button
                        type="button"
                        className="chip"
                        data-status={ticket.status}
                        onClick={() =>
                          navigate({
                            segments: ['machine'],
                            query: { ...route.query, ticket: ticket.id },
                          })
                        }
                      >
                        {`${ticket.id} · ${t(ticket.title)}`}
                      </button>
                    </li>
                  ))}
                </ul>

                <p className="phase__components">
                  <span className="phase__label">{`${t(ui.phases.components)}: `}</span>
                  {phase.components.map((id) => {
                    const component = componentById.get(id);
                    return component ? (
                      <button
                        key={id}
                        type="button"
                        className="chip chip--quiet"
                        onClick={() =>
                          navigate({ segments: ['component', id], query: route.query })
                        }
                      >
                        {t(component.title)}
                      </button>
                    ) : null;
                  })}
                </p>
              </div>
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}
