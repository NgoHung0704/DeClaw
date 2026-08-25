import systemsJson from '../../content/systems.json';
import { principleById, ui } from '../content/load';
import type { SystemEdge } from '../content/types';
import { githubUrl } from '../content/links';
import { useT } from '../i18n/lang';
import { Panel } from '../components/Panel';

const edges = (systemsJson as unknown as { edges: SystemEdge[] }).edges;

export function ContractPanel({ edgeId }: { edgeId: string }) {
  const t = useT();
  const edge = edges.find((e) => e.id === edgeId);
  if (!edge) return null;
  const c = edge.contract;

  const rows: { label: string; value: string }[] = [
    { label: t(ui.contract.transport), value: t(c.transport) },
    { label: t(ui.contract.method), value: c.method ?? t(ui.contract.none) },
    { label: t(ui.contract.path), value: c.path ?? t(ui.contract.none) },
    { label: t(ui.contract.auth), value: t(c.auth) },
    { label: t(ui.contract.request), value: t(c.request) },
    { label: t(ui.contract.response), value: t(c.response) },
  ];

  return (
    <Panel title={t(edge.label)}>
      <dl className="contract">
        {rows.map((row) => (
          <div className="contract__row" key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>

      <h3 className="panel__section">{t(ui.contract.errors)}</h3>
      <ul className="contract__errors">
        {c.errors.map((err) => (
          <li key={err.code}>
            <code className="contract__code">{err.code}</code>
            <span>{t(err.meaning)}</span>
          </li>
        ))}
      </ul>

      {edge.principles.length > 0 && (
        <>
          <h3 className="panel__section">{t(ui.contract.principles)}</h3>
          <ul className="contract__principles">
            {edge.principles.map((id) => {
              const principle = principleById.get(id);
              return principle ? <li key={id}>{t(principle.title)}</li> : null;
            })}
          </ul>
        </>
      )}

      <h3 className="panel__section">{t(ui.detail.source)}</h3>
      <p className="contract__source">{t(c.source.note)}</p>
      <a
        className="link"
        href={githubUrl(c.source.file, c.source.start, c.source.end)}
        target="_blank"
        rel="noreferrer"
      >
        {`${c.source.file}:${c.source.start}-${c.source.end}`}
      </a>
    </Panel>
  );
}
