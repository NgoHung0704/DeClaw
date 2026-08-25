import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { CONTENT_DIR } from './_repo';

const read = <T>(name: string): T =>
  JSON.parse(readFileSync(path.join(CONTENT_DIR, name), 'utf8')) as T;

type Component = { id: string; tickets: string[]; detail?: string; modules: string[] };
type Ticket = { id: string; creates: string[]; modifies: string[]; traverses: string[] };

const components = read<{ components: Component[] }>('components.json').components;
const tickets = read<{ tickets: Ticket[] }>('tickets.json').tickets;

const componentIds = new Set(components.map((c) => c.id));
const ticketIds = new Set(tickets.map((t) => t.id));

describe('cross-references resolve in both directions', () => {
  for (const c of components) {
    for (const t of c.tickets) {
      it(`component ${c.id} -> ticket ${t} resolves`, () => {
        expect(ticketIds.has(t)).toBe(true);
      });
      it(`ticket ${t} lists component ${c.id} back`, () => {
        const ticket = tickets.find((x) => x.id === t);
        expect(ticket, `ticket ${t} does not exist`).toBeTruthy();
        const related = [...ticket!.creates, ...ticket!.modifies, ...ticket!.traverses];
        expect(related).toContain(c.id);
      });
    }
    if (c.detail) {
      it(`component ${c.id} detail file exists`, () => {
        expect(existsSync(path.join(CONTENT_DIR, 'details', `${c.detail}.json`))).toBe(true);
      });
    }
  }

  for (const t of tickets) {
    const related = [...t.creates, ...t.modifies, ...t.traverses];

    it(`ticket ${t.id} relates to at least one component`, () => {
      // A ticket with no relation owns nothing and silently vanishes from the
      // machine diagram's ticket filter.
      expect(related.length).toBeGreaterThan(0);
    });

    for (const c of related) {
      it(`ticket ${t.id} -> component ${c} resolves`, () => {
        expect(componentIds.has(c)).toBe(true);
      });
      it(`component ${c} lists ticket ${t.id} back`, () => {
        const comp = components.find((x) => x.id === c);
        expect(comp, `component ${c} does not exist`).toBeTruthy();
        expect(comp!.tickets).toContain(t.id);
      });
    }
  }
});
