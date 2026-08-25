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
  { where: 'machine.json', flow: read(path.join(CONTENT_DIR, 'machine.json')) as Flow },
];

describe('every diagram is fully labelled in both languages', () => {
  it('finds diagrams to check', () => {
    expect(allFlows.length).toBeGreaterThan(0);
  });

  for (const { where, flow } of allFlows) {
    const nodeIds = new Set(flow.nodes.map((n) => n.id));

    for (const node of flow.nodes) {
      it(`${where}/${flow.id} node ${node.id} is labelled`, () => {
        expect(node.label.en.trim().length).toBeGreaterThan(0);
        expect(node.label.vi.trim().length).toBeGreaterThan(0);
      });
    }

    for (const edge of flow.edges) {
      it(`${where}/${flow.id} edge ${edge.id} is labelled`, () => {
        // An unlabelled edge is invisible to the companion list, which is the
        // whole keyboard and screen-reader surface. Gate branches especially:
        // the branching logic lives in the edge labels, nowhere else.
        expect(edge.label.en.trim().length).toBeGreaterThan(0);
        expect(edge.label.vi.trim().length).toBeGreaterThan(0);
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
        for (const branch of outgoing) {
          expect(branch.label.en.trim().length).toBeGreaterThan(0);
          expect(branch.label.vi.trim().length).toBeGreaterThan(0);
        }
      });
    }
  }
});
