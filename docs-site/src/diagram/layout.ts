import { estimateTextWidth, wrapText } from './wrapText';

export type BoxStyle = { maxWidth: number; fontSize: number; padding: number; lineHeight: number };
export type LayoutInput = {
  nodes: { id: string; label: string; column: number }[];
  edges: { id: string; from: string; to: string; label: string }[];
  box: BoxStyle;
  columnGap: number;
};
export type Box = { id: string; x: number; y: number; w: number; h: number; lines: string[] };
export type EdgeRoute = {
  id: string;
  points: { x: number; y: number }[];
  labelX: number;
  labelY: number;
  lane: number;
};
export type LayoutResult = {
  boxes: Map<string, Box>;
  routes: EdgeRoute[];
  width: number;
  height: number;
};

const LANE_SPACING = 26;
const ROW_GAP = 34;

/** Unordered pair key: two edges between the same nodes share lanes even in opposite directions. */
const pairKey = (a: string, b: string) => [a, b].sort().join('::');

export function layoutGraph(input: LayoutInput): LayoutResult {
  const { box, columnGap } = input;

  const lanesByPair = new Map<string, number>();
  for (const e of input.edges) {
    const key = pairKey(e.from, e.to);
    lanesByPair.set(key, (lanesByPair.get(key) ?? 0) + 1);
  }
  const maxLanes = Math.max(0, ...lanesByPair.values());
  const required = maxLanes * LANE_SPACING;
  if (columnGap < required) {
    throw new Error(
      `column gap ${columnGap}px is too narrow: ${maxLanes} lanes need at least ${required}px`,
    );
  }

  const columns = new Map<number, typeof input.nodes>();
  for (const node of input.nodes) {
    const list = columns.get(node.column) ?? [];
    list.push(node);
    columns.set(node.column, list);
  }

  const boxes = new Map<string, Box>();
  let width = 0;
  let height = 0;
  for (const [columnIndex, nodes] of [...columns.entries()].sort(([a], [b]) => a - b)) {
    let y = 0;
    for (const node of nodes) {
      const lines = wrapText(node.label, box.maxWidth, box.fontSize);
      const w =
        Math.min(box.maxWidth, Math.max(...lines.map((l) => estimateTextWidth(l, box.fontSize)))) +
        box.padding * 2;
      const h = lines.length * box.lineHeight + box.padding * 2;
      const x = columnIndex * (box.maxWidth + box.padding * 2 + columnGap);
      boxes.set(node.id, { id: node.id, x, y, w, h, lines });
      y += h + ROW_GAP;
      width = Math.max(width, x + w);
      height = Math.max(height, y);
    }
  }

  const laneCursor = new Map<string, number>();
  const routes: EdgeRoute[] = input.edges.map((edge) => {
    const from = boxes.get(edge.from);
    const to = boxes.get(edge.to);
    if (!from || !to) throw new Error(`edge ${edge.id} references a node with no box`);
    const key = pairKey(edge.from, edge.to);
    const lane = laneCursor.get(key) ?? 0;
    laneCursor.set(key, lane + 1);
    const lanes = lanesByPair.get(key)!;

    const forward = from.x <= to.x;
    const startX = forward ? from.x + from.w : from.x;
    const endX = forward ? to.x : to.x + to.w;
    const startY = from.y + from.h / 2;
    const endY = to.y + to.h / 2;
    // Each lane gets its own vertical corridor inside the gap, so parallel
    // edges never collapse into one line.
    const midX = startX + (endX - startX) / 2 + (lane - (lanes - 1) / 2) * LANE_SPACING;

    const points = [
      { x: startX, y: startY },
      { x: midX, y: startY },
      { x: midX, y: endY },
      { x: endX, y: endY },
    ];
    // The label sits at the midpoint of THIS edge's own vertical corridor.
    // Anchoring at the source box centre gives every edge leaving that box the
    // same point, which is how a pile of overlapping labels happens.
    return { id: edge.id, points, labelX: midX, labelY: (startY + endY) / 2, lane };
  });

  return { boxes, routes, width, height: height + ROW_GAP };
}
