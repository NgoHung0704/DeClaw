import type { Box } from './geometry';

/**
 * Bus routing for one source feeding many targets in a column.
 *
 * A hub with nine independent polylines is unfixable by tuning: nine lines
 * leave the same box edge, each turns at its own x, and the turns rake across
 * the space where the labels have to go. Schematics solve this with a bus —
 * one trunk out of the source, then short parallel stubs into each target.
 * Nothing crosses anything, and every label gets a clear run of its own.
 */
export type Stub = {
  id: string;
  d: string;
  labelX: number;
  labelY: number;
  anchor: 'start' | 'middle' | 'end';
};

export type Bus = { spine: string; stubs: Stub[] };

const RADIUS = 12;
/** Keep the trunk clear of the source box so the spine is visibly separate. */
const TRUNK_INSET = 0.34;
/** A stub needs at least a line of text between it and the next one. */
const MIN_STUB_SPACING = 19;

export function busRoute(
  hub: Box,
  targets: { id: string; box: Box }[],
  opts: { gap?: number } = {},
): Bus {
  if (targets.length === 0) return { spine: '', stubs: [] };

  const hubRight = hub.x + hub.w;
  const nearestTarget = Math.min(...targets.map((t) => t.box.x));
  const run = nearestTarget - hubRight;
  const trunkX = hubRight + Math.max(opts.gap ?? 0, run * TRUNK_INSET);

  const hubY = hub.y + hub.h / 2;
  const ys = targets.map((t) => t.box.y + t.box.h / 2);
  const top = Math.min(...ys, hubY);
  const bottom = Math.max(...ys, hubY);

  // One line out of the hub, then one vertical spine that every stub taps.
  const spine = [
    `M ${hubRight} ${hubY}`,
    `L ${trunkX - RADIUS} ${hubY}`,
    `Q ${trunkX} ${hubY} ${trunkX} ${hubY + Math.sign(bottom - hubY || 1) * RADIUS}`,
    `M ${trunkX} ${top}`,
    `L ${trunkX} ${bottom}`,
  ].join(' ');

  // Several stubs can share one target — three separate calls into Ollama, for
  // instance. Left on the box centre they become one line with three labels
  // printed on top of each other, so they fan out across the box.
  const perTarget = new Map<number, number>();
  for (const t of targets) perTarget.set(t.box.y, (perTarget.get(t.box.y) ?? 0) + 1);
  const seen = new Map<number, number>();

  const stubs = targets.map(({ id, box }) => {
    const total = perTarget.get(box.y) ?? 1;
    const index = seen.get(box.y) ?? 0;
    seen.set(box.y, index + 1);
    const span = Math.max(box.h, (total + 1) * MIN_STUB_SPACING);
    const y = box.y + box.h / 2 - span / 2 + (span * (index + 1)) / (total + 1);
    const endX = box.x;
    return {
      id,
      d: `M ${trunkX} ${y} L ${endX} ${y}`,
      // The label rides its own stub, clear of the spine and of the target.
      labelX: (trunkX + endX) / 2,
      labelY: y - 9,
      anchor: 'middle' as const,
    };
  });

  return { spine, stubs };
}
