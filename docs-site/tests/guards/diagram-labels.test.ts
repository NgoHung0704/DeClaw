import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { CONTENT_DIR } from './_repo';

type Loc = { en: string; vi: string };
type Flow = {
  id: string;
  nodes: { id: string; kind: string; label: Loc }[];
  edges: { id: string; from: string; to: string; label: Loc }[];
};

const read = (file: string) => JSON.parse(readFileSync(file, 'utf8'));

const detailsDir = path.join(CONTENT_DIR, 'details');
const details = readdirSync(detailsDir)
  .filter((f) => f.endsWith('.json'))
  .map((f) => ({ name: f, json: read(path.join(detailsDir, f)) as { flows?: Flow[] } }));

const allFlows: { where: string; flow: Flow }[] = [
  ...details.flatMap((d) => (d.json.flows ?? []).map((flow) => ({ where: d.name, flow }))),
  { where: 'systems.json', flow: read(path.join(CONTENT_DIR, 'systems.json')) as Flow },
];

type Machine = {
  chassis: { label: Loc };
  ports: { id: string; label: Loc; note: Loc }[];
  parts: { id: string; label: Loc; note: Loc; component: string; subparts: unknown[] }[];
  exits: { id: string; label: Loc; note: Loc }[];
  links: { id: string; from: string; to: string; label: Loc }[];
};

const machine = read(path.join(CONTENT_DIR, 'machine.json')) as Machine;

function expectLabelled(loc: Loc, what: string) {
  expect(loc.en.trim().length, `${what}: empty English`).toBeGreaterThan(0);
  expect(loc.vi.trim().length, `${what}: empty Vietnamese`).toBeGreaterThan(0);
}

describe('the machine is fully labelled and wired to real parts', () => {
  const partIds = new Set(machine.parts.map((p) => p.id));

  it('names the chassis in both languages', () => {
    expectLabelled(machine.chassis.label, 'chassis');
  });

  for (const slot of [...machine.ports, ...machine.exits]) {
    it(`slot ${slot.id} is labelled and explained`, () => {
      expectLabelled(slot.label, slot.id);
      expectLabelled(slot.note, `${slot.id} note`);
    });
  }

  for (const part of machine.parts) {
    it(`part ${part.id} is labelled, explained and has pieces inside`, () => {
      expectLabelled(part.label, part.id);
      expectLabelled(part.note, `${part.id} note`);
      // A part with nothing inside cannot be opened, so the drill-down would
      // be a dead end rather than a detail.
      expect(part.subparts.length, `${part.id} has no sub-parts`).toBeGreaterThan(0);
    });
  }

  for (const link of machine.links) {
    it(`link ${link.id} is labelled and joins real parts`, () => {
      expectLabelled(link.label, link.id);
      expect(partIds.has(link.from), `unknown source ${link.from}`).toBe(true);
      expect(partIds.has(link.to), `unknown target ${link.to}`).toBe(true);
    });
  }
});

describe('every diagram is fully labelled in both languages', () => {
  it('finds diagrams to check', () => {
    expect(allFlows.length).toBeGreaterThan(0);
  });

  for (const { where, flow } of allFlows) {
    const nodeIds = new Set(flow.nodes.map((n) => n.id));

    for (const node of flow.nodes) {
      it(`${where}/${flow.id} node ${node.id} is labelled`, () => {
        expectLabelled(node.label, node.id);
      });
    }

    for (const edge of flow.edges) {
      it(`${where}/${flow.id} edge ${edge.id} is labelled`, () => {
        // An unlabelled edge is invisible to the companion list, which is the
        // whole keyboard and screen-reader surface. Gate branches especially:
        // the branching logic lives in the edge labels, nowhere else.
        expectLabelled(edge.label, edge.id);
      });

      it(`${where}/${flow.id} edge ${edge.id} connects real nodes`, () => {
        expect(nodeIds.has(edge.from), `unknown source ${edge.from}`).toBe(true);
        expect(nodeIds.has(edge.to), `unknown target ${edge.to}`).toBe(true);
      });
    }

    for (const gate of flow.nodes.filter((n) => n.kind === 'gate')) {
      it(`${where}/${flow.id} gate ${gate.id} has more than one labelled branch`, () => {
        const outgoing = flow.edges.filter((e) => e.from === gate.id);
        expect(outgoing.length, 'a gate with one exit is not a gate').toBeGreaterThan(1);
        for (const branch of outgoing) expectLabelled(branch.label, branch.id);
      });
    }
  }
});
