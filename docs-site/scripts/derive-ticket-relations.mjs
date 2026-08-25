// Derive creates/modifies from git history, at AUTHORING time.
// This is a derivation, not a CI guard: a history rewrite would make a guard
// over git history lie. `traverses` stays hand-curated from the call flow.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(here, '../..');
const components = JSON.parse(
  readFileSync(path.resolve(here, '../content/components.json'), 'utf8'),
).components;

const componentOf = new Map();
for (const c of components) for (const m of c.modules) componentOf.set(m, c.id);

const log = execFileSync(
  'git',
  ['log', '--reverse', '--name-status', '--format=%H%x09%s'],
  { cwd: REPO_ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
);

const byTicket = new Map();
let ticketsInCommit = [];
for (const line of log.split('\n')) {
  const header = line.match(/^[0-9a-f]{40}\t(.*)$/);
  if (header) {
    ticketsInCommit = [...header[1].matchAll(/DCL-\d{3}/g)].map((m) => m[0]);
    continue;
  }
  const change = line.match(/^([AMR])\d*\t(.+?)(?:\t(.+))?$/);
  if (!change || ticketsInCommit.length === 0) continue;
  const file = (change[3] ?? change[2]).replace(/\\/g, '/');
  const component = componentOf.get(file);
  if (!component) continue;
  for (const ticket of ticketsInCommit) {
    if (!byTicket.has(ticket)) byTicket.set(ticket, { creates: new Set(), modifies: new Set() });
    byTicket.get(ticket)[change[1] === 'A' ? 'creates' : 'modifies'].add(component);
  }
}

const out = [...byTicket.entries()]
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([id, r]) => ({
    id,
    creates: [...r.creates].sort(),
    modifies: [...r.modifies].filter((c) => !r.creates.has(c)).sort(),
    traverses: [],
  }));

console.log(JSON.stringify({ tickets: out }, null, 2));
