import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { CONTENT_DIR, gitTrackedFiles } from './_repo';

/** The documentation universe: every git-tracked .py outside tests/. */
function sourceModules(): string[] {
  return gitTrackedFiles().filter((f) => f.endsWith('.py') && !f.startsWith('tests/'));
}

/**
 * Modules claimed by components.json ONLY.
 *
 * Counting any other file that happens to list modules — tickets.json does —
 * would let a module pass merely by being mentioned in a ticket, with nobody
 * ever writing about it. That is the exact hole this guard exists to close.
 */
function modulesFromComponents(): Set<string> {
  const raw = readFileSync(path.join(CONTENT_DIR, 'components.json'), 'utf8');
  const parsed = JSON.parse(raw) as { components: { modules: string[] }[] };
  return new Set(parsed.components.flatMap((c) => c.modules));
}

describe('module coverage', () => {
  const modules = sourceModules();

  it('discovers the source universe from git, not from a hardcoded number', () => {
    expect(modules.length).toBeGreaterThan(0);
  });

  const covered = modulesFromComponents();
  for (const module of modules) {
    it(`${module} is documented by a component`, () => {
      expect(covered.has(module), `${module} appears in no component's modules[]`).toBe(true);
    });
  }

  it('does not count modules that only a ticket mentions', () => {
    const ticketsPath = path.join(CONTENT_DIR, 'tickets.json');
    const tickets = JSON.parse(readFileSync(ticketsPath, 'utf8')) as {
      tickets: { modulesTouched?: string[] }[];
    };
    const ticketOnly = new Set(tickets.tickets.flatMap((t) => t.modulesTouched ?? []));
    for (const m of ticketOnly) {
      if (!covered.has(m)) {
        expect.fail(`${m} is mentioned by a ticket but documented by no component`);
      }
    }
  });
});
