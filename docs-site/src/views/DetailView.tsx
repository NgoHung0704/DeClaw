import { componentById, loadDetail, principleById, ticketById, ui } from '../content/load';
import { githubUrl } from '../content/links';
import { useT } from '../i18n/lang';
import { Diagram } from '../diagram/Diagram';
import { Panel } from '../components/Panel';
import { useNavigate, useRoute } from '../router/Router';

export function DetailView({ id }: { id: string }) {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const component = componentById.get(id);
  const detail = loadDetail(id);
  if (!component || !detail) return null;

  const openFn = route.segments[2] === 'fn' ? route.segments[3] : undefined;
  const fn = openFn ? detail.functions.find((f) => f.id === openFn) : undefined;

  return (
    <div className="view">
      <button
        type="button"
        className="button button--back"
        onClick={() => navigate({ segments: ['components'], query: route.query })}
      >
        {t(ui.detail.back)}
      </button>

      <h2>{t(component.title)}</h2>
      <p className="lede">{t(component.summary)}</p>

      <section>
        <h3>{t(ui.detail.modules)}</h3>
        <ul className="modules">
          {component.modules.map((module) => (
            <li key={module}>
              <a className="link mono" href={githubUrl(module)} target="_blank" rel="noreferrer">
                {module}
              </a>
            </li>
          ))}
        </ul>
      </section>

      {detail.flows.map((flow) => (
        <section key={flow.id}>
          <h3>{`${t(ui.detail.flow)} — ${t(flow.title)}`}</h3>
          <Diagram
            nodes={flow.nodes.map((n) => ({ id: n.id, label: n.label, kind: n.kind }))}
            edges={flow.edges}
            dimmed={new Set()}
            onSelect={() => {}}
            label={t(flow.title)}
          />
        </section>
      ))}

      <section>
        <h3>{t(ui.detail.functions)}</h3>
        <ul className="functions">
          {detail.functions.map((f) => (
            <li key={f.id} className="functions__item">
              <button
                type="button"
                className="functions__name"
                onClick={() =>
                  navigate({ segments: ['component', id, 'fn', f.id], query: route.query })
                }
              >
                {f.name}
              </button>
              <code className="functions__signature">{f.signature}</code>
              <a className="link mono" href={githubUrl(f.file, f.line)} target="_blank" rel="noreferrer">
                {`${f.file}:${f.line}`}
              </a>
            </li>
          ))}
        </ul>
      </section>

      {detail.snippets.length > 0 && (
        <section>
          <h3>{t(ui.detail.code)}</h3>
          {detail.snippets.map((s) => (
            <figure className="snippet" key={`${s.file}:${s.start}`}>
              <figcaption>{t(s.caption)}</figcaption>
              <pre className="snippet__code">
                <code>{s.code}</code>
              </pre>
              <a
                className="link mono"
                href={githubUrl(s.file, s.start, s.end)}
                target="_blank"
                rel="noreferrer"
              >
                {`${s.file}:${s.start}-${s.end}`}
              </a>
            </figure>
          ))}
        </section>
      )}

      {detail.quotes.length > 0 && (
        <section>
          <h3>{t(ui.detail.quotes)}</h3>
          <ul className="quotes">
            {detail.quotes.map((q) => (
              <li key={`${q.file}:${q.start}`}>
                <p>{t(q.note)}</p>
                <a
                  className="link mono"
                  href={githubUrl(q.file, q.start, q.end)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {`${q.file}:${q.start}-${q.end}`}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>{t(ui.detail.why)}</h3>
        <ul className="why">
          {detail.why.map((w) => (
            <li key={w.id} className="why__card">
              <h4>{t(w.title)}</h4>
              <p>{t(w.body)}</p>
              <p className="why__source">{t(w.source.note)}</p>
              <a
                className="link mono"
                href={githubUrl(w.source.file, w.source.start, w.source.end)}
                target="_blank"
                rel="noreferrer"
              >
                {`${w.source.file}:${w.source.start}-${w.source.end}`}
              </a>
              {w.principles.length > 0 && (
                <ul className="why__principles">
                  {w.principles.map((p) => {
                    const principle = principleById.get(p);
                    return principle ? <li key={p}>{t(principle.title)}</li> : null;
                  })}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </section>

      {component.tickets.length > 0 && (
        <section>
          <h3>{t(ui.detail.tickets)}</h3>
          <ul className="tickets">
            {component.tickets.map((tid) => {
              const ticket = ticketById.get(tid);
              return ticket ? (
                <li key={tid}>
                  <button
                    type="button"
                    className="chip"
                    onClick={() =>
                      navigate({ segments: ['machine'], query: { ...route.query, ticket: tid } })
                    }
                  >
                    {`${ticket.id} — ${t(ticket.title)}`}
                  </button>
                </li>
              ) : null;
            })}
          </ul>
        </section>
      )}

      {fn && (
        <Panel title={fn.name}>
          <p>{t(fn.note)}</p>
          <h3 className="panel__section">{t(ui.detail.signature)}</h3>
          <code className="functions__signature">{fn.signature}</code>
          <p>
            <a
              className="link mono"
              href={githubUrl(fn.file, fn.line)}
              target="_blank"
              rel="noreferrer"
            >
              {`${fn.file}:${fn.line}`}
            </a>
          </p>
        </Panel>
      )}
    </div>
  );
}
