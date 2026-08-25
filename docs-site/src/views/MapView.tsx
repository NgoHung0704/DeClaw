import systemsJson from '../../content/systems.json';
import { ui } from '../content/load';
import type { SystemEdge, SystemNode } from '../content/types';
import { useT } from '../i18n/lang';
import { Diagram } from '../diagram/Diagram';
import { useNavigate, useRoute } from '../router/Router';
import { ContractPanel } from './ContractPanel';
import { OwnershipTable } from './OwnershipTable';

const systems = systemsJson as unknown as {
  nodes: SystemNode[];
  edges: SystemEdge[];
  canvas: { width: number; height: number };
};

export function MapView() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const openEdge = route.segments[0] === 'map' && route.segments[1] === 'edge'
    ? route.segments[2]
    : undefined;

  const nodes = systems.nodes.map((n) => ({
    id: n.id,
    label: n.label,
    kind: n.kind,
    x: n.x,
    y: n.y,
    w: n.w,
    h: n.h,
  }));
  const edges = systems.edges.map((e) => ({
    id: e.id,
    from: e.from,
    to: e.to,
    label: e.label,
  }));

  const select = (kind: 'node' | 'edge', id: string) => {
    if (kind !== 'edge') return;
    navigate({ segments: ['map', 'edge', id], query: route.query });
  };

  return (
    <div className="view">
      <section>
        <h2>{t(ui.map.heading)}</h2>
        <p className="lede">{t(ui.map.intro)}</p>
        <Diagram
          nodes={nodes}
          edges={edges}
          dimmed={new Set()}
          onSelect={select}
          canvas={systems.canvas}
          label={t(ui.map.heading)}
        />
        <ul className="node-notes">
          {systems.nodes.map((node) => (
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
