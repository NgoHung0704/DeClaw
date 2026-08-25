import { motion } from 'motion/react';
import { easeOut, spring, useReducedMotion } from '../lib/motion';
import { edgeLabelPoint, edgePath, type Attachment, type Box } from './geometry';
import { wrapLabel, charBudget } from './wrap';

const LINE_HEIGHT = 15;
// Faint enough to recede, solid enough to still read as content rather than
// as something that failed to load.
const DIM_OPACITY = 0.3;

/**
 * The arrowhead, defined once per SVG.
 *
 * `orient="auto-start-reverse"` keeps it pointing along the path whichever way
 * the edge runs, and `refX` sits it on the path's end so the head touches the
 * target box instead of floating short of it.
 */
export function ArrowDefs() {
  return (
    <defs>
      <marker
        id="edge-arrow"
        viewBox="0 0 8 8"
        refX="7"
        refY="4"
        markerWidth="6"
        markerHeight="6"
        orient="auto-start-reverse"
      >
        <path d="M 0 0 L 8 4 L 0 8 z" fill="currentColor" />
      </marker>
    </defs>
  );
}

export function DiagramEdge(props: {
  from: Box;
  to: Box;
  label: string;
  lane?: number;
  midShift?: number;
  attachment?: Attachment;
  dimmed?: boolean;
  index?: number;
  onActivate?: () => void;
}) {
  const reduced = useReducedMotion();
  const d = edgePath(props.from, props.to, props.lane ?? 0, props.midShift ?? 0, props.attachment);
  const at = edgeLabelPoint(props.from, props.to, props.lane ?? 0, props.attachment);
  const interactive = Boolean(props.onActivate);

  return (
    <g
      className={['edge', interactive ? 'edge--interactive' : ''].filter(Boolean).join(' ')}
      onClick={props.onActivate}
    >
      {/* The dim lives on an inner <g>, never on the element Motion animates:
          Motion writes `opacity` into that element's inline style, which beats
          any class on it. Nested, the two opacities multiply instead of one
          silently erasing the other. It stays an inline value rather than a
          class so a test can read the number instead of trusting a class name
          that may or may not resolve to anything. */}
      <g style={{ opacity: props.dimmed ? DIM_OPACITY : 1 }}>
        <motion.path
          d={d}
          className="edge__line"
          fill="none"
          markerEnd="url(#edge-arrow)"
          initial={reduced ? { opacity: 0 } : { pathLength: 0, opacity: 0 }}
          animate={reduced ? { opacity: 1 } : { pathLength: 1, opacity: 1 }}
          transition={
            reduced
              ? { duration: 0.2 }
              : { duration: 0.6, delay: (props.index ?? 0) * 0.045, ease: easeOut }
          }
        />
        <text className="edge__label" x={at.x} y={at.y} textAnchor={at.anchor}>
          {props.label}
        </text>
      </g>
    </g>
  );
}

export function DiagramNode(props: {
  id: string;
  box: Box;
  label: string;
  kind: string;
  dimmed?: boolean;
  index?: number;
  onActivate?: () => void;
}) {
  const reduced = useReducedMotion();
  const { box } = props;
  const lines = wrapLabel(props.label, charBudget(box.w));
  const blockHeight = lines.length * LINE_HEIGHT;
  const firstBaseline = box.y + box.h / 2 - blockHeight / 2 + LINE_HEIGHT - 4;
  const interactive = Boolean(props.onActivate);
  const isGate = props.kind === 'gate';

  return (
    <motion.g
      className={[
        'node',
        `node--${props.kind}`,
        interactive ? 'node--interactive' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 12 }}
      animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0 }}
      transition={{ ...spring, delay: reduced ? 0 : (props.index ?? 0) * 0.04 }}
      tabIndex={interactive ? 0 : undefined}
      role={interactive ? 'button' : undefined}
      aria-label={interactive ? props.label : undefined}
      onClick={props.onActivate}
      onKeyDown={(event) => {
        if (!interactive) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          props.onActivate?.();
        }
      }}
    >
      <g data-node-group={props.id} style={{ opacity: props.dimmed ? DIM_OPACITY : 1 }}>
        {isGate ? (
          <path
            className="node__shape"
            d={`M ${box.x + 16} ${box.y} L ${box.x + box.w} ${box.y} L ${box.x + box.w - 16} ${
              box.y + box.h
            } L ${box.x} ${box.y + box.h} Z`}
          />
        ) : (
          <rect
            className="node__shape"
            x={box.x}
            y={box.y}
            width={box.w}
            height={box.h}
            rx={10}
          />
        )}
        <text className="node__label" x={box.x + box.w / 2} textAnchor="middle">
          {lines.map((line, i) => (
            <tspan key={line} x={box.x + box.w / 2} y={firstBaseline + i * LINE_HEIGHT}>
              {line}
            </tspan>
          ))}
        </text>
      </g>
    </motion.g>
  );
}
