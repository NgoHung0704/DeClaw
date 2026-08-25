import { ui } from '../content/load';
import { useT } from '../i18n/lang';
import { SystemMap, systemContent } from '../diagram/SystemMap';
import { CompanionList } from '../diagram/CompanionList';
import { useNavigate, useRoute } from '../router/Router';
import { ContractPanel } from './ContractPanel';
import { OwnershipTable } from './OwnershipTable';

export function MapView() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const openEdge =
    route.segments[0] === 'map' && route.segments[1] === 'edge' ? route.segments[2] : undefined;

  const openContract = (id: string) =>
    navigate({ segments: ['map', 'edge', id], query: route.query });

  return (
    <div className="view">
      <section>
        <h2>{t(ui.map.heading)}</h2>
        <p className="lede">{t(ui.map.intro)}</p>

        <div className="diagram">
          <SystemMap onOpenEdge={openContract} />
          <CompanionList
            nodes={systemContent.nodes.map((n) => ({ id: n.id, label: n.label, kind: n.kind }))}
            edges={systemContent.edges.map((e) => ({
              id: e.id,
              from: e.from,
              to: e.to,
              label: e.label,
            }))}
            onSelect={(kind, id) => {
              if (kind === 'edge') openContract(id);
            }}
          />
        </div>

        <ul className="node-notes">
          {systemContent.nodes.map((node) => (
            <li key={node.id} data-kind={node.kind}>
              <strong>{t(node.label)}</strong>
              <span>{t(node.note)}</span>
            </li>
          ))}
        </ul>
      </section>

      <OwnershipTable />
      {openEdge && <ContractPanel edgeId={openEdge} />}
    </div>
  );
}
