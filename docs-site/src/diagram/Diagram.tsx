import { useMemo } from 'react';
import { useLang } from '../i18n/lang';
import type { Loc } from '../content/types';
import { assignLanes, assignMidShifts, attachments, layerGraph, type Box } from './geometry';
import { ArrowDefs, DiagramEdge, DiagramNode } from './parts';
import { CompanionList, type ListEdge, type ListNode } from './CompanionList';
import { Plot } from './Plot';

export type DiagramNodeInput = ListNode & {
  /** Authored position. Small flow graphs omit it and get layered instead. */
  x?: number;
  y?: number;
  w?: number;
  h?: number;
};

const FLOW_BOX = { w: 210, h: 66 };
const PAD = 40;

export function Diagram(props: {
  nodes: DiagramNodeInput[];
  edges: ListEdge[];
  dimmed: Set<string>;
  onSelect: (kind: 'node' | 'edge', id: string) => void;
  canvas?: { width: number; height: number };
  label: string;
}) {
  const { lang } = useLang();

  const boxes = useMemo<Map<string, Box>>(() => {
    const authored = props.nodes.every((n) => typeof n.x === 'number');
    if (authored) {
      return new Map(
        props.nodes.map((n) => [n.id, { x: n.x!, y: n.y!, w: n.w!, h: n.h! }] as const),
      );
    }
    return layerGraph(
      props.nodes.map((n) => ({ id: n.id, w: n.w ?? FLOW_BOX.w, h: n.h ?? FLOW_BOX.h })),
      props.edges,
      { colGap: 110, rowGap: 34 },
    );
  }, [props.nodes, props.edges]);

  const size = useMemo(() => {
    if (props.canvas) return props.canvas;
    let width = 0;
    let height = 0;
    for (const box of boxes.values()) {
      width = Math.max(width, box.x + box.w);
      height = Math.max(height, box.y + box.h);
    }
    return { width: width + PAD * 2, height: height + PAD * 2 };
  }, [boxes, props.canvas]);

  const lanes = useMemo(() => assignLanes(props.edges), [props.edges]);
  const shifts = useMemo(() => assignMidShifts(props.edges, boxes), [props.edges, boxes]);
  const attached = useMemo(() => attachments(props.edges), [props.edges]);

  const label = (loc: Loc) => loc[lang];

  return (
    <div className="diagram">
      <Plot width={size.width} height={size.height} label={props.label}>
          <ArrowDefs />
          <g transform={props.canvas ? undefined : `translate(${PAD}, ${PAD})`}>
            {props.edges.map((edge, i) => {
              const from = boxes.get(edge.from);
              const to = boxes.get(edge.to);
              if (!from || !to) return null;
              const dimmed = props.dimmed.has(edge.from) || props.dimmed.has(edge.to);
              return (
                <DiagramEdge
                  key={edge.id}
                  from={from}
                  to={to}
                  label={label(edge.label)}
                  lane={lanes[i]}
                  midShift={shifts[i]}
                  attachment={attached[i]}
                  dimmed={dimmed}
                  index={i}
                  onActivate={() => props.onSelect('edge', edge.id)}
                />
              );
            })}
            {props.nodes.map((node, i) => {
              const box = boxes.get(node.id);
              if (!box) return null;
              return (
                <DiagramNode
                  key={node.id}
                  id={node.id}
                  box={box}
                  label={label(node.label)}
                  kind={node.kind}
                  dimmed={props.dimmed.has(node.id)}
                  index={i}
                  onActivate={() => props.onSelect('node', node.id)}
                />
              );
            })}
          </g>
      </Plot>

      <CompanionList
        nodes={props.nodes}
        edges={props.edges}
        onSelect={props.onSelect}
        dimmed={props.dimmed}
      />
    </div>
  );
}
