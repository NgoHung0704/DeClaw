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
  labelAnchor: 'start' | 'middle' | 'end';
  lane: number;
};
export type LayoutResult = {
  boxes: Map<string, Box>;
  routes: EdgeRoute[];
  width: number;
  height: number;
};

const LANE_SPACING = 18;
const ROW_GAP = 26;

/**
 * Lanes are per column gap, not per node pair.
 *
 * Keying on the pair looks right until many edges leave one node for different
 * targets in the same column: each pair is unique, every edge gets lane 0, and
 * they all collapse onto one shared corridor with their labels piled up. The
 * corridor is the scarce resource, so the gap is what has to be shared out.
 */
const gapKey = (fromColumn: number, toColumn: number) =>
  [fromColumn, toColumn].sort((a, b) => a - b).join('->');

/**
 * The narrowest column gap that can hold every lane crossing it, plus breathing
 * room for the labels sitting in those corridors. Callers ask for this rather
 * than guessing, because guessing is how five lanes end up in forty pixels.
 */
export function requiredColumnGap(input: {
  nodes: { id: string; column: number }[];
  edges: { from: string; to: string }[];
}): number {
  const columnOf = new Map(input.nodes.map((n) => [n.id, n.column]));
  const perGap = new Map<string, number>();
  for (const e of input.edges) {
    const key = gapKey(columnOf.get(e.from) ?? 0, columnOf.get(e.to) ?? 0);
    perGap.set(key, (perGap.get(key) ?? 0) + 1);
  }
  const maxLanes = Math.max(0, ...perGap.values());
  return maxLanes * LANE_SPACING + LANE_SPACING;
}

export function layoutGraph(input: LayoutInput): LayoutResult {
  const { box, columnGap } = input;

  const columnOf = new Map(input.nodes.map((n) => [n.id, n.column]));
  const edgeGap = new Map<string, string>();
  const lanesByGap = new Map<string, number>();
  for (const e of input.edges) {
    const key = gapKey(columnOf.get(e.from) ?? 0, columnOf.get(e.to) ?? 0);
    edgeGap.set(e.id, key);
    lanesByGap.set(key, (lanesByGap.get(key) ?? 0) + 1);
  }
  const maxLanes = Math.max(0, ...lanesByGap.values());
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

  // Centre short columns against the tallest one. Without this a column of one
  // node sits at the top beside a column of ten, and most of the drawing is
  // empty space with every edge raking diagonally across it.
  const columnHeights = new Map<number, number>();
  for (const node of input.nodes) {
    const b = boxes.get(node.id)!;
    columnHeights.set(node.column, Math.max(columnHeights.get(node.column) ?? 0, b.y + b.h));
  }
  const tallest = Math.max(0, ...columnHeights.values());
  for (const node of input.nodes) {
    const b = boxes.get(node.id)!;
    const offset = (tallest - (columnHeights.get(node.column) ?? 0)) / 2;
    boxes.set(node.id, { ...b, y: b.y + offset });
  }

  // Spread the points where edges leave and arrive, so several edges sharing a
  // node do not stack on one pixel — and so each edge gets a distinct row to
  // put its label on.
  const countBy = (pick: (e: (typeof input.edges)[number]) => string) => {
    const totals = new Map<string, number>();
    for (const e of input.edges) totals.set(pick(e), (totals.get(pick(e)) ?? 0) + 1);
    return totals;
  };
  const outTotals = countBy((e) => e.from);
  const inTotals = countBy((e) => e.to);
  const outCursor = new Map<string, number>();
  const inCursor = new Map<string, number>();

  const anchorY = (
    box: Box,
    id: string,
    totals: Map<string, number>,
    cursor: Map<string, number>,
  ) => {
    const total = totals.get(id) ?? 1;
    const index = cursor.get(id) ?? 0;
    cursor.set(id, index + 1);
    return box.y + (box.h * (index + 1)) / (total + 1);
  };

  const laneCursor = new Map<string, number>();
  const routes: EdgeRoute[] = input.edges.map((edge) => {
    const from = boxes.get(edge.from);
    const to = boxes.get(edge.to);
    if (!from || !to) throw new Error(`edge ${edge.id} references a node with no box`);
    const key = edgeGap.get(edge.id)!;
    const lane = laneCursor.get(key) ?? 0;
    laneCursor.set(key, lane + 1);
    const lanes = lanesByGap.get(key)!;

    const forward = from.x <= to.x;
    const startX = forward ? from.x + from.w : from.x;
    const endX = forward ? to.x : to.x + to.w;
    const startY = anchorY(from, edge.from, outTotals, outCursor);
    const endY = anchorY(to, edge.to, inTotals, inCursor);
    // Each lane gets its own vertical corridor inside the gap, so parallel
    // edges never collapse into one line.
    const midX = startX + (endX - startX) / 2 + (lane - (lanes - 1) / 2) * LANE_SPACING;

    const points = [
      { x: startX, y: startY },
      { x: midX, y: startY },
      { x: midX, y: endY },
      { x: endX, y: endY },
    ];
    // The label rides the approach into its own target row, right-aligned.
    // Sitting in the corridor instead looks tidy until the corridors are a
    // lane apart and the labels are ten times wider than a lane, at which
    // point neighbouring labels print straight through each other.
    return {
      id: edge.id,
      points,
      labelX: endX - 8,
      labelY: endY - 5,
      labelAnchor: forward ? 'end' : 'start',
      lane,
    };
  });

  return { boxes, routes, width, height: height + ROW_GAP };
}
