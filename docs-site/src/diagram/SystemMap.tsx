import { motion } from 'motion/react';
import systemsJson from '../../content/systems.json';
import type { SystemEdge, SystemNode } from '../content/types';
import { easeOut, spring, useReducedMotion } from '../lib/motion';
import { useT } from '../i18n/lang';
import { ArrowDefs } from './parts';
import { busRoute } from './trunk';
import { wrapLabel, charBudget } from './wrap';
import { Plot } from './Plot';

const systems = systemsJson as unknown as {
  nodes: SystemNode[];
  edges: SystemEdge[];
  canvas: { width: number; height: number };
};

const LINE = 15;

/**
 * The system map, drawn as a bus.
 *
 * Nine independent polylines out of one box cannot be made tidy: they leave the
 * same edge, each turns at its own x, and the turns rake straight through the
 * space the labels need. One trunk and nine parallel stubs has no crossings at
 * all, and gives every label a clear run of its own.
 */
export function SystemMap(props: { onOpenEdge: (edgeId: string) => void }) {
  const t = useT();
  const reduced = useReducedMotion();
  const byId = new Map(systems.nodes.map((n) => [n.id, n]));

  const hub = byId.get('declaw-core')!;
  const hubEdges = systems.edges.filter((e) => e.from === 'declaw-core');
  const directEdges = systems.edges.filter((e) => e.from !== 'declaw-core');

  const bus = busRoute(
    hub,
    hubEdges.map((e) => ({ id: e.id, box: byId.get(e.to)! })),
    { gap: 40 },
  );

  return (
    <Plot
      width={systems.canvas.width}
      height={systems.canvas.height}
      label={t(hub.label)}
    >
        <ArrowDefs />

        {directEdges.map((edge, i) => {
          const from = byId.get(edge.from)!;
          const to = byId.get(edge.to)!;
          const y = from.y + from.h / 2;
          return (
            <g
              key={edge.id}
              className="edge edge--interactive"
              role="button"
              tabIndex={0}
              aria-label={t(edge.label)}
              onClick={() => props.onOpenEdge(edge.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  props.onOpenEdge(edge.id);
                }
              }}
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

        <g className="bus">
          <motion.path
            className="wire wire--bus"
            d={bus.spine}
            fill="none"
            initial={reduced ? { opacity: 0 } : { pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 0.7, ease: easeOut }}
          />
          {bus.stubs.map((stub, i) => {
            const edge = hubEdges.find((e) => e.id === stub.id)!;
            return (
              <g
                key={stub.id}
                className="edge edge--interactive"
                role="button"
                tabIndex={0}
                aria-label={t(edge.label)}
                onClick={() => props.onOpenEdge(edge.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    props.onOpenEdge(edge.id);
                  }
                }}
              >
                <motion.path
                  className="edge__line"
                  fill="none"
                  markerEnd="url(#edge-arrow)"
                  d={stub.d}
                  initial={reduced ? { opacity: 0 } : { pathLength: 0, opacity: 0 }}
                  animate={{ pathLength: 1, opacity: 1 }}
                  transition={{ duration: 0.45, delay: 0.3 + i * 0.05, ease: easeOut }}
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
