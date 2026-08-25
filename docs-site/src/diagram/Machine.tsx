import { AnimatePresence, motion } from 'motion/react';
import machineJson from '../../content/machine.json';
import { ui } from '../content/load';
import type { Loc } from '../content/types';
import { easeOut, spring, useReducedMotion } from '../lib/motion';
import { useT } from '../i18n/lang';
import { busRoute } from './trunk';
import { ArrowDefs } from './parts';
import { wrapLabel, charBudget } from './wrap';
import { Canvas } from './Canvas';

type SubPart = { id: string; file: string; label: string; path: string };
type Part = {
  id: string;
  component: string;
  x: number;
  y: number;
  w: number;
  h: number;
  label: Loc;
  note: Loc;
  subparts: SubPart[];
};
type Slot = { id: string; x: number; y: number; w: number; h: number; label: Loc; note: Loc };
type Machine = {
  canvas: { width: number; height: number };
  chassis: { x: number; y: number; w: number; h: number; label: Loc };
  ports: Slot[];
  parts: Part[];
  exits: Slot[];
  links: { id: string; from: string; to: string; label: Loc }[];
  portLinks: { id: string; from: string; to: string }[];
};

const machine = machineJson as unknown as Machine;
const LINE = 15;
const DIM = 0.28;

function Label({
  text,
  box,
  className,
  weight,
}: {
  text: string;
  box: { x: number; y: number; w: number; h: number };
  className: string;
  weight?: number;
}) {
  const lines = wrapLabel(text, charBudget(box.w, 16));
  const first = box.y + box.h / 2 - (lines.length * LINE) / 2 + LINE - 4;
  return (
    <text
      className={className}
      x={box.x + box.w / 2}
      textAnchor="middle"
      fontWeight={weight}
    >
      {lines.map((line, i) => (
        <tspan key={line} x={box.x + box.w / 2} y={first + i * LINE}>
          {line}
        </tspan>
      ))}
    </text>
  );
}

/**
 * DeClaw drawn as one machine: intake ports on the left, parts inside a
 * chassis, exits on the right.
 *
 * Ports and exits connect to the chassis, not to individual parts. Wiring every
 * exit back to the part that produces it is truthful and unreadable — nine
 * lines crossing the whole body. The chassis is the boundary that matters, and
 * each part names its own inputs and outputs when you open it.
 */
export function MachineDiagram(props: {
  dimmedComponents: Set<string> | null;
  openPart: string | null;
  onOpenPart: (id: string | null) => void;
  onOpenComponent: (componentId: string) => void;
}) {
  const t = useT();
  const reduced = useReducedMotion();
  const { chassis, canvas } = machine;

  const open = props.openPart ? machine.parts.find((p) => p.id === props.openPart) ?? null : null;

  const isDim = (part: Part) =>
    props.dimmedComponents !== null && !props.dimmedComponents.has(part.component);

  // Ports feed the chassis; exits leave it. One bus each, so nothing crosses.
  const chassisBox = { x: chassis.x, y: chassis.y, w: chassis.w, h: chassis.h };
  const exitBus = busRoute(
    chassisBox,
    machine.exits.map((e) => ({ id: e.id, box: e })),
    { gap: 26 },
  );

  return (
    <Canvas width={canvas.width} height={canvas.height} label={t(machine.chassis.label)}>
      <svg
        className="diagram__svg machine"
        width={canvas.width}
        height={canvas.height}
        viewBox={`0 0 ${canvas.width} ${canvas.height}`}
        role="presentation"
      >
        <ArrowDefs />

        {/* intake ports */}
        {machine.ports.map((port, i) => (
          <motion.g
            key={port.id}
            className="slot slot--port"
            initial={reduced ? { opacity: 0 } : { opacity: 0, x: -14 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ ...spring, delay: reduced ? 0 : i * 0.05 }}
          >
            <rect className="slot__shape" x={port.x} y={port.y} width={port.w} height={port.h} rx={10} />
            <Label text={t(port.label)} box={port} className="slot__label" weight={600} />
            <path
              className="wire wire--in"
              markerEnd="url(#edge-arrow)"
              d={`M ${port.x + port.w} ${port.y + port.h / 2} L ${chassis.x - 2} ${port.y + port.h / 2}`}
            />
          </motion.g>
        ))}

        {/* chassis */}
        <g className="chassis">
          <rect
            className="chassis__shape"
            x={chassis.x}
            y={chassis.y}
            width={chassis.w}
            height={chassis.h}
            rx={18}
          />
          <text className="chassis__label" x={chassis.x + 20} y={chassis.y + 26}>
            {t(chassis.label)}
          </text>
        </g>

        {/* exits, fed by one bus off the chassis */}
        <g className="bus">
          <path className="wire wire--bus" d={exitBus.spine} />
          {exitBus.stubs.map((stub) => (
            <path key={stub.id} className="wire wire--out" d={stub.d} markerEnd="url(#edge-arrow)" />
          ))}
        </g>
        {machine.exits.map((exit, i) => (
          <motion.g
            key={exit.id}
            className="slot slot--exit"
            initial={reduced ? { opacity: 0 } : { opacity: 0, x: 14 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ ...spring, delay: reduced ? 0 : 0.1 + i * 0.05 }}
          >
            <rect className="slot__shape" x={exit.x} y={exit.y} width={exit.w} height={exit.h} rx={10} />
            <Label text={t(exit.label)} box={exit} className="slot__label" />
          </motion.g>
        ))}

        <AnimatePresence mode="wait">
          {open ? (
            <motion.g key="open" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {/* the opened part fills the chassis, and only its own pieces show */}
              <motion.rect
                layoutId={`part-${open.id}`}
                className="part__shape part__shape--open"
                x={chassis.x + 22}
                y={chassis.y + 44}
                width={chassis.w - 44}
                height={chassis.h - 66}
                rx={14}
                transition={reduced ? { duration: 0 } : spring}
              />
              <text className="part__open-title" x={chassis.x + 44} y={chassis.y + 78}>
                {t(open.label)}
              </text>
              <text className="part__open-note" x={chassis.x + 44} y={chassis.y + 100}>
                {t(open.note)}
              </text>

              {open.subparts.map((sub, i) => {
                const perRow = 2;
                const w = (chassis.w - 44 - 32 * 3) / perRow;
                const h = 40;
                const x = chassis.x + 22 + 32 + (i % perRow) * (w + 32);
                const y = chassis.y + 128 + Math.floor(i / perRow) * (h + 12);
                if (y + h > chassis.y + chassis.h - 30) return null;
                return (
                  <motion.g
                    key={sub.id}
                    className="subpart"
                    initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.32, delay: reduced ? 0 : i * 0.025, ease: easeOut }}
                  >
                    <rect className="subpart__shape" x={x} y={y} width={w} height={h} rx={8} />
                    <text className="subpart__label" x={x + 12} y={y + 25}>
                      {sub.label}
                    </text>
                  </motion.g>
                );
              })}

              <g
                className="part__back"
                role="button"
                tabIndex={0}
                aria-label={t(ui.machine.backToMachine)}
                onClick={() => props.onOpenPart(null)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    props.onOpenPart(null);
                  }
                }}
              >
                <rect
                  x={chassis.x + chassis.w - 150}
                  y={chassis.y + 56}
                  width={116}
                  height={30}
                  rx={8}
                />
                <text x={chassis.x + chassis.w - 92} y={chassis.y + 76} textAnchor="middle">
                  {t(ui.machine.backToMachine)}
                </text>
              </g>
            </motion.g>
          ) : (
            <motion.g key="parts" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {machine.links.map((link, i) => {
                const from = machine.parts.find((p) => p.id === link.from)!;
                const to = machine.parts.find((p) => p.id === link.to)!;
                const sameRow = Math.abs(from.y - to.y) < 4;
                // Two links leaving the same part downward would share one
                // vertical line and stack their labels on it, so each gets its
                // own lane out of the box.
                const siblings = machine.links.filter((l) => l.from === link.from);
                const lane =
                  (siblings.findIndex((l) => l.id === link.id) - (siblings.length - 1) / 2) * 34;

                let d: string;
                let mid: { x: number; y: number };
                if (sameRow) {
                  const goingRight = to.x > from.x;
                  const x1 = goingRight ? from.x + from.w : from.x;
                  const x2 = goingRight ? to.x : to.x + to.w;
                  const y = from.y + from.h / 2;
                  d = `M ${x1} ${y} L ${x2} ${y}`;
                  mid = { x: (x1 + x2) / 2, y: y - 10 };
                } else {
                  const x = from.x + from.w / 2 + lane;
                  const goingDown = to.y > from.y;
                  const y1 = goingDown ? from.y + from.h : from.y;
                  const y2 = goingDown ? to.y : to.y + to.h;
                  const enterX = to.x + to.w / 2 + lane;
                  d = `M ${x} ${y1} L ${x} ${(y1 + y2) / 2} L ${enterX} ${(y1 + y2) / 2} L ${enterX} ${y2}`;
                  mid = { x: (x + enterX) / 2, y: (y1 + y2) / 2 - 8 };
                }

                return (
                  <motion.g
                    key={link.id}
                    className="wirebox"
                    initial={reduced ? { opacity: 0 } : { pathLength: 0, opacity: 0 }}
                    animate={{ pathLength: 1, opacity: 1 }}
                    transition={{ duration: 0.5, delay: reduced ? 0 : 0.2 + i * 0.05, ease: easeOut }}
                  >
                    <path className="wire wire--link" d={d} markerEnd="url(#edge-arrow)" />
                    <text className="wire__label" x={mid.x} y={mid.y} textAnchor="middle">
                      {t(link.label)}
                    </text>
                  </motion.g>
                );
              })}

              {machine.parts.map((part, i) => (
                <motion.g
                  key={part.id}
                  className="part"
                  role="button"
                  tabIndex={0}
                  aria-label={t(part.label)}
                  onClick={() => props.onOpenPart(part.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      props.onOpenPart(part.id);
                    }
                  }}
                  initial={reduced ? { opacity: 0 } : { opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ ...spring, delay: reduced ? 0 : i * 0.04 }}
                >
                  {/* Dim on an inner group: Motion owns the outer element's
                      inline opacity, so a second value there would be erased. */}
                  <g data-part-group={part.id} style={{ opacity: isDim(part) ? DIM : 1 }}>
                    <motion.rect
                      layoutId={`part-${part.id}`}
                      className="part__shape"
                      x={part.x}
                      y={part.y}
                      width={part.w}
                      height={part.h}
                      rx={12}
                      transition={reduced ? { duration: 0 } : spring}
                    />
                    <Label
                      text={t(part.label)}
                      box={{ x: part.x, y: part.y - 18, w: part.w, h: part.h }}
                      className="part__label"
                      weight={600}
                    />
                    <text
                      className="part__count"
                      x={part.x + part.w / 2}
                      y={part.y + part.h - 16}
                      textAnchor="middle"
                    >
                      {`${part.subparts.length} ${t(ui.machine.modules)}`}
                    </text>
                  </g>
                </motion.g>
              ))}
            </motion.g>
          )}
        </AnimatePresence>
      </svg>
    </Canvas>
  );
}

export { machine as machineContent };
export type { Part as MachinePart };
