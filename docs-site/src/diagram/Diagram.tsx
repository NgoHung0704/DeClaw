import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLang, useT } from '../i18n/lang';
import { layoutGraph, requiredColumnGap, type LayoutResult } from './layout';
import { CompanionList, type ListEdge, type ListNode } from './CompanionList';

const BOX = { maxWidth: 165, fontSize: 13, padding: 9, lineHeight: 16 };
const MIN_COLUMN_GAP = 150;
const DIM_OPACITY = 0.22;

export type DiagramNode = ListNode & { column: number };

export function Diagram(props: {
  nodes: DiagramNode[];
  edges: ListEdge[];
  dimmed: Set<string>;
  onSelect: (kind: 'node' | 'edge', id: string) => void;
}) {
  const { lang } = useLang();
  const t = useT();
  const svgRef = useRef<SVGSVGElement>(null);
  const [widthBudget, setWidthBudget] = useState(BOX.maxWidth);

  const layout: LayoutResult = useMemo(
    () =>
      layoutGraph({
        nodes: props.nodes.map((n) => ({ id: n.id, label: n.label[lang], column: n.column })),
        edges: props.edges.map((e) => ({
          id: e.id,
          from: e.from,
          to: e.to,
          label: e.label[lang],
        })),
        box: { ...BOX, maxWidth: widthBudget },
        columnGap: Math.max(MIN_COLUMN_GAP, requiredColumnGap({ nodes: props.nodes, edges: props.edges })),
      }),
    [props.nodes, props.edges, lang, widthBudget],
  );

  // Re-measure with the browser's real metrics. The estimator is a fallback
  // for jsdom, where getComputedTextLength() returns 0 — so a test using it
  // proves internal consistency, and only a real browser proves text fits.
  useLayoutEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    let widest = 0;
    svg.querySelectorAll<SVGTextContentElement>('.diagram__label tspan').forEach((node) => {
      const measured = node.getComputedTextLength?.() ?? 0;
      if (measured > widest) widest = measured;
    });
    if (widest > widthBudget && widthBudget > BOX.maxWidth * 0.6) {
      setWidthBudget(Math.max(BOX.maxWidth * 0.6, widthBudget * 0.9));
    }
  }, [lang, layout, widthBudget]);

  return (
    <div className="diagram">
      <div className="diagram__scroll">
        <svg
          ref={svgRef}
          viewBox={`-8 -8 ${layout.width + 40} ${layout.height + 24}`}
          width={layout.width + 40}
          height={layout.height + 24}
          className="diagram__svg"
          role="presentation"
        >
          {layout.routes.map((route) => {
            const edge = props.edges.find((e) => e.id === route.id)!;
            return (
              <g key={route.id} data-edge-group={route.id}>
                <polyline
                  points={route.points.map((p) => `${p.x},${p.y}`).join(' ')}
                  className="diagram__edge"
                />
                <text x={route.labelX} y={route.labelY} textAnchor={route.labelAnchor} className="diagram__edge-label">
                  {t(edge.label)}
                </text>
              </g>
            );
          })}
          {[...layout.boxes.values()].map((box) => {
            const node = props.nodes.find((n) => n.id === box.id)!;
            return (
              // Dimming is inline opacity on the PARENT group. Two opacities
              // then multiply instead of one overwriting the other, which is
              // what breaks a `.dimmed` class the moment anything writes an
              // inline style onto the same element.
              <g
                key={box.id}
                data-node-group={box.id}
                style={{ opacity: props.dimmed.has(box.id) ? DIM_OPACITY : 1 }}
              >
                <rect
                  x={box.x}
                  y={box.y}
                  width={box.w}
                  height={box.h}
                  rx={8}
                  className={`diagram__box diagram__box--${node.kind}`}
                />
                <text
                  x={box.x + box.w / 2}
                  y={box.y + BOX.padding + BOX.fontSize}
                  className="diagram__label"
                  textAnchor="middle"
                >
                  {box.lines.map((line, i) => (
                    <tspan key={line} x={box.x + box.w / 2} dy={i === 0 ? 0 : BOX.lineHeight}>
                      {line}
                    </tspan>
                  ))}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <CompanionList
        nodes={props.nodes}
        edges={props.edges}
        onSelect={props.onSelect}
        dimmed={props.dimmed}
      />
    </div>
  );
}
