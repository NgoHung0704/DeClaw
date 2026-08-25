import { motion } from 'motion/react';
import systemsJson from '../../content/systems.json';
import type { Loc, SystemEdge, SystemNode } from '../content/types';
import { easeOut, spring, useReducedMotion } from '../lib/motion';
import { useT } from '../i18n/lang';
import { ArrowDefs } from './parts';
import { busRoute } from './trunk';
import { wrapLabel, charBudget } from './wrap';
import { Plot } from './Plot';

type Band = {
  id: string;
  label: Loc;
  note: Loc;
  members: string[];
  x: number;
  y: number;
  w: number;
  h: number;
};

const systems = systemsJson as unknown as {
  nodes: (SystemNode & { group?: string })[];
  edges: SystemEdge[];
  groups: Band[];
  canvas: { width: number; height: number };
};

const LINE = 15;
/** Each band gets its own trunk, staggered so four buses never share a line. */
const TRUNK_STEP = 26;

/**
 * The system map, grouped by what each thing is.
 *
 * One bus for all nine targets was still a list: an inference daemon, three
 * stores, a subprocess and two unbuilt packages read as equals, strung on one
 * 860px spine. Four labelled bands, each with a short bus of its own, say
 * something instead — what DeClaw computes with, what it keeps, what it
 * isolates, and what it has not built.
 */
export function SystemMap(props: { onOpenEdge: (edgeId: string) => void }) {
  const t = useT();
  const reduced = useReducedMotion();
  const byId = new Map(systems.nodes.map((n) => [n.id, n]));
  const hub = byId.get('declaw-core')!;

  const directEdges = systems.edges.filter((e) => e.from !== 'declaw-core');
  const hubEdges = systems.edges.filter((e) => e.from === 'declaw-core');
  const groupOf = (nodeId: string) => byId.get(nodeId)?.group;

  const buses = systems.groups.map((band, index) => {
    const edges = hubEdges.filter((e) => groupOf(e.to) === band.id);
    return {
      band,
      edges,
      bus: busRoute(
        hub,
        edges.map((e) => ({ id: e.id, box: byId.get(e.to)! })),
        // Stagger the trunks, and give each bus its own row out of the hub.
        {
          gap: 60 + index * TRUNK_STEP,
          hubSlot: { index, total: systems.groups.length },
        },
      ),
    };
  });

  const openEdge = (id: string) => props.onOpenEdge(id);
  const activate = (id: string) => ({
    role: 'button' as const,
    tabIndex: 0,
    onClick: () => openEdge(id),
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openEdge(id);
      }
    },
  });

  return (
    <Plot width={systems.canvas.width} height={systems.canvas.height} label={t(hub.label)}>
      <ArrowDefs />

      {/* bands first, so every wire and box sits on top of them */}
      {systems.groups.map((band, i) => (
        <motion.g
          key={band.id}
          className={`band band--${band.id}`}
          initial={reduced ? { opacity: 0 } : { opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ ...spring, delay: reduced ? 0 : i * 0.06 }}
        >
          <rect className="band__shape" x={band.x} y={band.y} width={band.w} height={band.h} rx={14} />
          <text className="band__label" x={band.x + 20} y={band.y + 26}>
            {t(band.label)}
          </text>
        </motion.g>
      ))}

      {directEdges.map((edge, i) => {
        const from = byId.get(edge.from)!;
        const to = byId.get(edge.to)!;
        const y = from.y + from.h / 2;
        return (
          <g
            key={edge.id}
            className="edge edge--interactive"
            aria-label={t(edge.label)}
            {...activate(edge.id)}
          >
            <motion.path
              className="edge__line"
              fill="none"
              markerEnd="url(#edge-arrow)"
              d={`M ${from.x + from.w} ${y} L ${to.x} ${y}`}
              initial={reduced ? { opacity: 0 } : { pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{ duration: 0.5, delay: i * 0.05, ease: easeOut }}
            />
            <text
              className="edge__label"
              x={(from.x + from.w + to.x) / 2}
              y={y - 10}
              textAnchor="middle"
            >
              {t(edge.label)}
            </text>
          </g>
        );
      })}

      {buses.map(({ band, edges, bus }, bandIndex) => (
        <g key={band.id} className={`bus bus--${band.id}`}>
          <motion.path
            className="wire wire--bus"
            d={bus.spine}
            fill="none"
            initial={reduced ? { opacity: 0 } : { pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 0.55, delay: bandIndex * 0.08, ease: easeOut }}
          />
          {bus.stubs.map((stub, i) => {
            const edge = edges.find((e) => e.id === stub.id)!;
            return (
              <g
                key={stub.id}
                className="edge edge--interactive"
                aria-label={t(edge.label)}
                {...activate(edge.id)}
              >
                <motion.path
                  className="edge__line"
                  fill="none"
                  markerEnd="url(#edge-arrow)"
                  d={stub.d}
                  initial={reduced ? { opacity: 0 } : { pathLength: 0, opacity: 0 }}
                  animate={{ pathLength: 1, opacity: 1 }}
                  transition={{
                    duration: 0.4,
                    delay: 0.2 + bandIndex * 0.08 + i * 0.05,
                    ease: easeOut,
                  }}
                />
                <text
                  className="edge__label"
                  x={stub.labelX}
                  y={stub.labelY}
                  textAnchor={stub.anchor}
                >
                  {t(edge.label)}
                </text>
              </g>
            );
          })}
        </g>
      ))}

      {systems.nodes.map((node, i) => {
        const lines = wrapLabel(t(node.label), charBudget(node.w));
        const first = node.y + node.h / 2 - (lines.length * LINE) / 2 + LINE - 4;
        return (
          <motion.g
            key={node.id}
            className={`node node--${node.kind}`}
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring, delay: reduced ? 0 : i * 0.04 }}
          >
            <g data-node-group={node.id}>
              <rect
                className="node__shape"
                x={node.x}
                y={node.y}
                width={node.w}
                height={node.h}
                rx={10}
              />
              <text className="node__label" x={node.x + node.w / 2} textAnchor="middle">
                {lines.map((line, k) => (
                  <tspan key={line} x={node.x + node.w / 2} y={first + k * LINE}>
                    {line}
                  </tspan>
                ))}
              </text>
            </g>
          </motion.g>
        );
      })}
    </Plot>
  );
}

export { systems as systemContent };
