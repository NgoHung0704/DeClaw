// Re-pull snippet `code` from its DECLARED range only.
// It never re-locates a range and never touches an `anchor`: an auto-fixer
// that re-found anchors would launder exactly the drift the guard exists to catch.
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(here, '../..');
const CONTENT_DIR = path.resolve(here, '../content');

const slice = (file, start, end) =>
  readFileSync(path.resolve(REPO_ROOT, file), 'utf8')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .slice(start - 1, end)
    .join('\n');

let changed = 0;
const visit = (node) => {
  if (Array.isArray(node)) return node.forEach(visit);
  if (node && typeof node === 'object') {
    if (typeof node.file === 'string' && typeof node.code === 'string') {
      const fresh = slice(node.file, node.start, node.end);
      if (fresh !== node.code) {
        node.code = fresh;
        changed += 1;
      }
    }
    Object.values(node).forEach(visit);
  }
};

const walk = (dir) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (entry.name.endsWith('.json')) {
      const json = JSON.parse(readFileSync(full, 'utf8'));
      visit(json);
      writeFileSync(full, `${JSON.stringify(json, null, 2)}\n`, 'utf8');
    }
  }
};

walk(CONTENT_DIR);
console.log(`sync-snippets: ${changed} snippet(s) refreshed`);
