export type Box = { x: number; y: number; w: number; h: number };

/** How far apart parallel edges sharing a gutter sit. */
const LANE_GAP = 16;

type Ends = { x1: number; y1: number; x2: number; y2: number; horizontal: boolean };

/**
 * Where an edge leaves one box and enters the other.
 *
 * Box edges, not centres: a line drawn centre-to-centre disappears under the
 * nodes at both ends, and the arrowhead lands inside the target instead of
 * touching it — which reads as an arrow pointing at nothing.
 */
/**
 * Spread the attachment points on one side of a node.
 *
 * `index` of `total` edges sharing this node, fanned across a span at least
 * `MIN_ANCHOR_SPACING` per edge. Dividing the box height alone gives 15px for
 * four edges into a 62px box, and a label needs more room than that — which is
 * how "health check", "embed chunks" and "chat with bound tools" ended up
 * printed on top of one another.
 */
const MIN_ANCHOR_SPACING = 17;

function anchor(centre: number, size: number, index: number, total: number): number {
  const span = Math.max(size, (total + 1) * MIN_ANCHOR_SPACING);
  return centre - span / 2 + (span * (index + 1)) / (total + 1);
}

export type Attachment = { outIndex: number; outTotal: number; inIndex: number; inTotal: number };

function ends(from: Box, to: Box, lane: number, at: Attachment): Ends {
  const horizontal = Math.abs(to.x - from.x) >= Math.abs(to.y - from.y);

  if (horizontal) {
    const goingRight = to.x >= from.x;
    return {
      x1: goingRight ? from.x + from.w : from.x,
      x2: goingRight ? to.x : to.x + to.w,
      y1: anchor(from.y + from.h / 2, from.h, at.outIndex, at.outTotal) + lane * 2,
      y2: anchor(to.y + to.h / 2, to.h, at.inIndex, at.inTotal),
      horizontal,
    };
  }

  const goingDown = to.y >= from.y;
  return {
    x1: anchor(from.x + from.w / 2, from.w, at.outIndex, at.outTotal),
    x2: anchor(to.x + to.w / 2, to.w, at.inIndex, at.inTotal),
    y1: goingDown ? from.y + from.h : from.y,
    y2: goingDown ? to.y : to.y + to.h,
    horizontal,
  };
}

/** Count how many edges attach to each node, and in what order. */
export function attachments<T extends { from: string; to: string }>(edges: T[]): Attachment[] {
  const outTotals = new Map<string, number>();
  const inTotals = new Map<string, number>();
  for (const e of edges) {
    outTotals.set(e.from, (outTotals.get(e.from) ?? 0) + 1);
    inTotals.set(e.to, (inTotals.get(e.to) ?? 0) + 1);
  }
  const outSeen = new Map<string, number>();
  const inSeen = new Map<string, number>();
  return edges.map((e) => {
    const outIndex = outSeen.get(e.from) ?? 0;
    const inIndex = inSeen.get(e.to) ?? 0;
    outSeen.set(e.from, outIndex + 1);
    inSeen.set(e.to, inIndex + 1);
    return {
      outIndex,
      outTotal: outTotals.get(e.from) ?? 1,
      inIndex,
      inTotal: inTotals.get(e.to) ?? 1,
    };
  });
}

const NO_ATTACHMENT: Attachment = { outIndex: 0, outTotal: 1, inIndex: 0, inTotal: 1 };

/**
 * An orthogonal path with a rounded turn.
 *
 * `midShift` moves the segment that crosses the gutter sideways. Lanes alone
 * are not enough when many edges share one gutter: they leave their boxes at
 * different heights but still turn on the same middle line, so the turns pile
 * into one thick stripe.
 */
export function edgePath(
  from: Box,
  to: Box,
  lane = 0,
  midShift = 0,
  at: Attachment = NO_ATTACHMENT,
): string {
  const { x1, y1, x2, y2, horizontal } = ends(from, to, lane, at);
  const r = 10;

  if (horizontal) {
    const mid = x1 + (x2 - x1) / 2 + midShift;
    if (Math.abs(y2 - y1) < 1) return `M ${x1} ${y1} L ${x2} ${y2}`;
    const dirY = Math.sign(y2 - y1);
    const dirX = Math.sign(x2 - x1);
    return [
      `M ${x1} ${y1}`,
      `L ${mid - r * dirX} ${y1}`,
      `Q ${mid} ${y1} ${mid} ${y1 + r * dirY}`,
      `L ${mid} ${y2 - r * dirY}`,
      `Q ${mid} ${y2} ${mid + r * dirX} ${y2}`,
      `L ${x2} ${y2}`,
    ].join(' ');
  }

  const mid = y1 + (y2 - y1) / 2 + midShift;
  if (Math.abs(x2 - x1) < 1) return `M ${x1} ${y1} L ${x2} ${y2}`;
  const dirX = Math.sign(x2 - x1);
  const dirY = Math.sign(y2 - y1);
  return [
    `M ${x1} ${y1}`,
    `L ${x1} ${mid - r * dirY}`,
    `Q ${x1} ${mid} ${x1 + r * dirX} ${mid}`,
    `L ${x2 - r * dirX} ${mid}`,
    `Q ${x2} ${mid} ${x2} ${mid + r * dirY}`,
    `L ${x2} ${y2}`,
  ].join(' ');
}

/**
 * Where an edge's label goes: on its own approach into the target.
 *
 * The middle of the gutter is the tidy-looking choice and the wrong one — with
 * lanes a few pixels apart and labels ten times wider than a lane, neighbouring
 * labels print straight through each other.
 */
export function edgeLabelPoint(
  from: Box,
  to: Box,
  lane = 0,
  at: Attachment = NO_ATTACHMENT,
): { x: number; y: number; anchor: 'start' | 'middle' | 'end' } {
  const { x1, y1, x2, y2, horizontal } = ends(from, to, lane, at);
  if (horizontal) {
    // Centred in the gap between the boxes, on this edge's own arrival row.
    // Hugging the target instead pushes a long label backwards until its first
    // characters disappear behind the source box.
    return { x: (x1 + x2) / 2, y: y2 - 7, anchor: 'middle' };
  }
  return { x: (x1 + x2) / 2 + 12, y: (y1 + y2) / 2, anchor: 'start' };
}

/** Fan parallel edges out symmetrically around their shared gutter. */
export function assignLanes<T extends { from: string; to: string }>(edges: T[]): number[] {
  const key = (e: T) => [e.from, e.to].sort().join('::');
  const totals = new Map<string, number>();
  for (const edge of edges) totals.set(key(edge), (totals.get(key(edge)) ?? 0) + 1);
  const seen = new Map<string, number>();
  return edges.map((edge) => {
    const k = key(edge);
    const total = totals.get(k)!;
    const index = seen.get(k) ?? 0;
    seen.set(k, index + 1);
    return index - (total - 1) / 2;
  });
}

/** Give each edge crossing the same gutter its own track across it. */
export function assignMidShifts<T extends { from: string; to: string }>(
  edges: T[],
  boxes: Map<string, Box>,
): number[] {
  const gutter = (e: T) => {
    const a = boxes.get(e.from);
    const b = boxes.get(e.to);
    if (!a || !b) return 'none';
    return `${Math.round(Math.min(a.x, b.x) / 40)}`;
  };
  const totals = new Map<string, number>();
  for (const edge of edges) totals.set(gutter(edge), (totals.get(gutter(edge)) ?? 0) + 1);
  const seen = new Map<string, number>();
  return edges.map((edge) => {
    const g = gutter(edge);
    const total = totals.get(g)!;
    const index = seen.get(g) ?? 0;
    seen.set(g, index + 1);
    return (index - (total - 1) / 2) * LANE_GAP;
  });
}

export type LayeredNode = { id: string; w: number; h: number };

/**
 * Place a small flow graph by longest-path layering.
 *
 * Numbering nodes by array order puts a gate's two branches in adjacent
 * columns as though one followed the other. Layering by longest path from a
 * source puts both branches in the same column, which is what a branch is.
 */
export function layerGraph(
  nodes: LayeredNode[],
  edges: { from: string; to: string }[],
  opts: { colGap: number; rowGap: number },
): Map<string, Box> {
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const n of nodes) {
    incoming.set(n.id, []);
    outgoing.set(n.id, []);
  }
  for (const e of edges) {
    outgoing.get(e.from)?.push(e.to);
    incoming.get(e.to)?.push(e.from);
  }

  const depth = new Map<string, number>();
  const visit = (id: string, seen: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0; // a cycle: stop rather than recurse forever
    seen.add(id);
    const parents = incoming.get(id) ?? [];
    const d = parents.length === 0 ? 0 : Math.max(...parents.map((p) => visit(p, seen) + 1));
    depth.set(id, d);
    return d;
  };
  for (const n of nodes) visit(n.id, new Set());

  const byLayer = new Map<number, LayeredNode[]>();
  for (const n of nodes) {
    const d = depth.get(n.id) ?? 0;
    byLayer.set(d, [...(byLayer.get(d) ?? []), n]);
  }

  const colWidth = Math.max(...nodes.map((n) => n.w));
  const layerHeights = [...byLayer.entries()].map(
    ([, list]) => list.reduce((sum, n) => sum + n.h, 0) + (list.length - 1) * opts.rowGap,
  );
  const tallest = Math.max(0, ...layerHeights);

  const boxes = new Map<string, Box>();
  for (const [layer, list] of [...byLayer.entries()].sort(([a], [b]) => a - b)) {
    const height = list.reduce((sum, n) => sum + n.h, 0) + (list.length - 1) * opts.rowGap;
    let y = (tallest - height) / 2;
    for (const n of list) {
      boxes.set(n.id, { x: layer * (colWidth + opts.colGap), y, w: n.w, h: n.h });
      y += n.h + opts.rowGap;
    }
  }
  return boxes;
}
