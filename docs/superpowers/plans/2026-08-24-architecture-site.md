# Architecture Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a bilingual (EN + VI) static site at `docs-site/` that explains DeClaw's architecture in three layers, published to GitHub Pages, whose every code claim is verified in CI by drift guards.

**Architecture:** Vite + React + TypeScript. All human-visible strings live in `docs-site/content/*.json`; `.tsx` files contain zero literal copy. Ten Vitest guards read the **real repository** through `git ls-files` and `fs` to prove snippets are verbatim, citations are anchored inside their declared ranges, every source module is documented, and every cross-reference resolves both ways. Diagrams are hand-rolled SVG (own text wrapping, own edge-lane routing) with an always-visible companion list of real buttons as the keyboard/narrow-screen surface.

**Tech Stack:** Node 22 LTS (CI) / 24 (local), Vite 6, React 19, TypeScript 5, Vitest 3, jsdom, @testing-library/react. No animation library. No CSS framework. No CDN.

**Spec:** `docs/superpowers/specs/2026-08-24-architecture-site-design.md`

## Global Constraints

- Work lands directly on branch `feat/phase-7-plugin-host`. Commit after every task.
- **Run `npm install` / `npm ci` from PowerShell, never Git Bash.** Through Git Bash npm mis-detects the platform, skips native optional dependencies (rollup) and emits shims missing their `.cmd` files.
- **Never pipe a command whose exit code matters.** `cmd | tail` returns `tail`'s status, so a following `&&` runs after a failure. Run bare, or echo `$?` on its own line.
- **No user-visible string in `.tsx`** — including button labels, `title` and `aria-label`. Guard 9 enforces this.
- **No test hardcodes a quantity.** Never `expect(x.length).toBe(20)`. Iterate content and assert per item.
- **Every behaviour-protecting test must be seen red**: break the behaviour, run the test, observe failure, restore. A test never seen failing is not evidence.
- Content path convention: every `file` field is a **repo-root-relative POSIX path** (`declaw/tools/registry.py`).
- Prose fields are `{ "en": string, "vi": string }`. Structural fields (ids, paths, line numbers) are language-neutral.
- A `snippet` has `code` and no `anchor`; a `quote` has `anchor` and no `code`. Both/neither fails.
- Verbatim comparison normalises CRLF to LF, preserves indentation exactly, and tolerates only a trailing-newline difference. (The repo is checked out with CRLF on Windows — git warns on every commit.)
- Vite `base` is `/DeClaw/`. Routing is hash-based.
- All transitions live inside `@media (prefers-reduced-motion: no-preference)`.

## File Structure

```
docs-site/
  package.json  tsconfig.json  vite.config.ts  vitest.config.ts  .nvmrc  index.html
  content/
    ui.json  principles.json  systems.json  ownership.json
    components.json  tickets.json  debt.json  machine.json  repo.json (generated)
    details/<component-id>.json
  scripts/
    sync-snippets.mjs        re-pull snippet code from declared ranges only
    gen-repo-json.mjs        owner/repo + commit SHA for deep links
    derive-ticket-relations.mjs   git log -> component-level creates/modifies
  src/
    main.tsx  App.tsx
    content/types.ts         TS types for every content file
    content/load.ts          typed imports + id indexes
    i18n/lang.tsx            Lang context, useT()
    router/route.ts          PURE: parseHash/formatHash/parentRoute
    router/Router.tsx        history, single Escape listener, focus return
    diagram/wrapText.ts      PURE: label -> tspan lines
    diagram/layout.ts        PURE: columns, lanes, polylines, label midpoints
    diagram/Diagram.tsx      SVG renderer, inline-opacity dimming
    diagram/CompanionList.tsx  real <button>s: nodes + edge labels + gate labels
    views/MapView.tsx  ContractPanel.tsx  OwnershipTable.tsx
    views/ComponentsView.tsx  DetailView.tsx  MachineView.tsx  DebtView.tsx
    components/Panel.tsx
    styles/tokens.css  layout.css  diagram.css
  tests/
    guards/_repo.ts and 10 guard specs
    ui/*.test.tsx
.github/workflows/ci.yml
```

---

### Task 1: Scaffold + guard harness + paths-exist guard

**Files:**
- Create: `docs-site/package.json`, `docs-site/tsconfig.json`, `docs-site/vite.config.ts`, `docs-site/vitest.config.ts`, `docs-site/.nvmrc`, `docs-site/index.html`, `docs-site/src/main.tsx`, `docs-site/src/App.tsx`
- Create: `docs-site/content/components.json`, `docs-site/content/ui.json`
- Create: `docs-site/tests/guards/_repo.ts`, `docs-site/tests/guards/paths-exist.test.ts`

**Interfaces:**
- Produces: `REPO_ROOT: string`, `readRepoLines(file: string): string[]`, `sliceLines(file: string, start: number, end: number): string`, `allContentFiles(): {name: string, json: unknown}[]`, `collectPathRefs(json: unknown): {file: string, start?: number, end?: number}[]`

- [ ] **Step 1: Create the project from PowerShell**

```powershell
cd d:\Documents\INSA_Lyon\INSA_4A\4IF2\Projects_4IF\DeClaw
New-Item -ItemType Directory -Force docs-site | Out-Null
Set-Content -Encoding utf8 docs-site\.nvmrc "22"
```

- [ ] **Step 2: Write `docs-site/package.json`**

```json
{
  "name": "declaw-architecture-site",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "node scripts/gen-repo-json.mjs && tsc -b && vite build",
    "preview": "vite preview",
    "guards": "vitest run",
    "test": "vitest run",
    "sync:snippets": "node scripts/sync-snippets.mjs"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@testing-library/dom": "^10.4.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.1",
    "typescript": "^5.7.2",
    "vite": "^6.0.5",
    "vitest": "^3.0.0"
  }
}
```

- [ ] **Step 3: Write the configs**

`docs-site/vite.config.ts`:

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/DeClaw/',
  plugins: [react()],
});
```

`docs-site/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    // Guards are node-side; UI specs opt in with a
    // `@vitest-environment jsdom` docblock at the top of the file.
    environment: 'node',
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
  },
});
```

`docs-site/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "resolveJsonModule": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vite/client"]
  },
  "include": ["src", "tests", "scripts"]
}
```

- [ ] **Step 4: Write `index.html`, `src/main.tsx`, `src/App.tsx`**

`docs-site/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>DeClaw Architecture</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`docs-site/src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`docs-site/src/App.tsx` (placeholder markup only — no copy, so guard 9 stays green):

```tsx
export function App() {
  return <main id="app" />;
}
```

- [ ] **Step 5: Install from PowerShell**

```powershell
cd d:\Documents\INSA_Lyon\INSA_4A\4IF2\Projects_4IF\DeClaw\docs-site
npm install
```

Expected: `node_modules/` created, no `EBADPLATFORM`, and `node_modules\.bin\vite.cmd` exists.

- [ ] **Step 6: Write the guard harness `tests/guards/_repo.ts`**

```ts
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(here, '../../..');
export const CONTENT_DIR = path.resolve(here, '../../content');

/** Repo-root-relative POSIX path -> absolute OS path. */
export function repoPath(file: string): string {
  return path.resolve(REPO_ROOT, file);
}

export function repoFileExists(file: string): boolean {
  return existsSync(repoPath(file));
}

/** Lines of a repo file, CRLF normalised, 0-indexed array. */
export function readRepoLines(file: string): string[] {
  return readFileSync(repoPath(file), 'utf8').replace(/\r\n/g, '\n').split('\n');
}

/** Inclusive 1-indexed line range, joined with LF, no trailing newline. */
export function sliceLines(file: string, start: number, end: number): string {
  return readRepoLines(file).slice(start - 1, end).join('\n');
}

/** Every git-tracked file, as repo-root-relative POSIX paths. */
export function gitTrackedFiles(): string[] {
  const out = execFileSync('git', ['ls-files'], { cwd: REPO_ROOT, encoding: 'utf8' });
  return out.split('\n').filter(Boolean).map((p) => p.replace(/\\/g, '/'));
}

export type ContentFile = { name: string; json: unknown };

/** Every content JSON, including details/*.json, named by relative path. */
export function allContentFiles(): ContentFile[] {
  const files: ContentFile[] = [];
  const walk = (dir: string, prefix: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        walk(path.join(dir, entry.name), `${prefix}${entry.name}/`);
      } else if (entry.name.endsWith('.json')) {
        const raw = readFileSync(path.join(dir, entry.name), 'utf8');
        files.push({ name: `${prefix}${entry.name}`, json: JSON.parse(raw) });
      }
    }
  };
  walk(CONTENT_DIR, '');
  return files;
}

export type PathRef = { file: string; start?: number; end?: number; where: string };

/** Every object anywhere in the content tree that carries a `file` field. */
export function collectPathRefs(json: unknown, where = ''): PathRef[] {
  const refs: PathRef[] = [];
  const visit = (node: unknown, trail: string) => {
    if (Array.isArray(node)) {
      node.forEach((item, i) => visit(item, `${trail}[${i}]`));
      return;
    }
    if (node && typeof node === 'object') {
      const rec = node as Record<string, unknown>;
      if (typeof rec.file === 'string') {
        refs.push({
          file: rec.file,
          start: typeof rec.start === 'number' ? rec.start : undefined,
          end: typeof rec.end === 'number' ? rec.end : undefined,
          where: `${where}${trail}`,
        });
      }
      for (const [key, value] of Object.entries(rec)) visit(value, `${trail}.${key}`);
    }
  };
  visit(json, '');
  return refs;
}
```

- [ ] **Step 7: Write the failing guard `tests/guards/paths-exist.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import { allContentFiles, collectPathRefs, readRepoLines, repoFileExists } from './_repo';

const refs = allContentFiles().flatMap((f) => collectPathRefs(f.json, f.name));

describe('every path declared in content exists, with a valid line range', () => {
  it('finds at least one path reference to check', () => {
    expect(refs.length).toBeGreaterThan(0);
  });

  for (const ref of refs) {
    it(`${ref.where} -> ${ref.file}`, () => {
      expect(repoFileExists(ref.file), `missing file: ${ref.file}`).toBe(true);
      if (ref.start !== undefined) {
        const lineCount = readRepoLines(ref.file).length;
        expect(ref.start).toBeGreaterThanOrEqual(1);
        expect(ref.end ?? ref.start).toBeGreaterThanOrEqual(ref.start);
        expect(ref.end ?? ref.start).toBeLessThanOrEqual(lineCount);
      }
    });
  }
});
```

- [ ] **Step 8: Seed minimal content so the guard has something to check**

`docs-site/content/ui.json`:

```json
{
  "site": {
    "title": { "en": "DeClaw Architecture", "vi": "Kiến trúc DeClaw" },
    "tagline": {
      "en": "How this repository is put together, and what it still owes.",
      "vi": "Repo này được ghép lại thế nào, và còn nợ những gì."
    }
  }
}
```

`docs-site/content/components.json`:

```json
{
  "components": [
    {
      "id": "tool-registry",
      "group": "tools",
      "tier": "A",
      "title": { "en": "Tool registry and wrapper order", "vi": "Registry công cụ và thứ tự bọc" },
      "summary": {
        "en": "Single source of truth for how a tool reaches the model: READ tools auto-run, non-READ tools are gated, audit wraps outermost.",
        "vi": "Nguồn sự thật duy nhất cho việc một tool đến tay model: tool READ chạy thẳng, tool non-READ bị chặn hỏi, audit bọc ngoài cùng."
      },
      "modules": ["declaw/tools/registry.py"],
      "tickets": [],
      "detail": "tool-registry",
      "sources": [
        { "file": "declaw/tools/registry.py", "start": 105, "end": 148 }
      ]
    }
  ]
}
```

- [ ] **Step 9: Run the guard — it must PASS, then break it and watch it FAIL**

```powershell
npx vitest run tests/guards/paths-exist.test.ts
```

Expected: PASS.

Now break it deliberately — edit `components.json` and change the path to `declaw/tools/registry_TYPO.py`, re-run:

Expected: FAIL with `missing file: declaw/tools/registry_TYPO.py`.

Restore the correct path and re-run. Expected: PASS. **Do not skip this — a guard never seen red is not evidence.**

- [ ] **Step 10: Commit**

```bash
git add docs-site .gitignore
git commit -m "feat(site): scaffold docs-site and the paths-exist drift guard"
```

Add `docs-site/node_modules/`, `docs-site/dist/` and `docs-site/content/repo.json` to `.gitignore` in this same commit.

---

### Task 2: snippet-verbatim + quote-anchor guards, and the sync script

**Files:**
- Create: `docs-site/tests/guards/citations.test.ts`, `docs-site/scripts/sync-snippets.mjs`
- Modify: `docs-site/content/components.json` (add one real snippet and one real quote to exercise both)

**Interfaces:**
- Consumes: `sliceLines`, `allContentFiles`, `collectPathRefs` from Task 1.
- Produces: `collectCitations(json, where): Citation[]` where `Citation = { file, start, end, code?, anchor?, where }`.

- [ ] **Step 1: Write the failing test `tests/guards/citations.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import { allContentFiles, sliceLines } from './_repo';

type Citation = {
  file: string; start: number; end: number;
  code?: string; anchor?: string; where: string;
};

function collectCitations(json: unknown, where: string): Citation[] {
  const found: Citation[] = [];
  const visit = (node: unknown, trail: string) => {
    if (Array.isArray(node)) return node.forEach((n, i) => visit(n, `${trail}[${i}]`));
    if (node && typeof node === 'object') {
      const r = node as Record<string, unknown>;
      const isCitation =
        typeof r.file === 'string' &&
        typeof r.start === 'number' &&
        (typeof r.code === 'string' || typeof r.anchor === 'string');
      if (isCitation) {
        found.push({
          file: r.file as string,
          start: r.start as number,
          end: (r.end as number) ?? (r.start as number),
          code: typeof r.code === 'string' ? r.code : undefined,
          anchor: typeof r.anchor === 'string' ? r.anchor : undefined,
          where: `${where}${trail}`,
        });
      }
      for (const [k, v] of Object.entries(r)) visit(v, `${trail}.${k}`);
    }
  };
  visit(json, '');
  return found;
}

const citations = allContentFiles().flatMap((f) => collectCitations(f.json, f.name));
const norm = (s: string) => s.replace(/\r\n/g, '\n').replace(/\n+$/, '');

describe('citations', () => {
  it('finds citations to check', () => {
    expect(citations.length).toBeGreaterThan(0);
  });

  // A snippet has code and no anchor; a quote has an anchor and no code.
  // Allowing both would let an author skip the anchor rule by adding code;
  // allowing neither would let a record cite nothing at all.
  for (const c of citations) {
    it(`${c.where} is exactly one of snippet or quote`, () => {
      const isSnippet = c.code !== undefined;
      const isQuote = c.anchor !== undefined;
      expect(isSnippet !== isQuote, 'a record must be a snippet XOR a quote').toBe(true);
    });
  }

  for (const c of citations.filter((x) => x.code !== undefined)) {
    it(`${c.where} embeds ${c.file}:${c.start}-${c.end} verbatim`, () => {
      expect(norm(c.code!)).toBe(norm(sliceLines(c.file, c.start, c.end)));
    });
  }

  for (const c of citations.filter((x) => x.anchor !== undefined)) {
    it(`${c.where} anchor is inside ${c.file}:${c.start}-${c.end}`, () => {
      // Checking the range boundaries alone is not enough: insert a paragraph
      // above and the citation slides onto different content while the range
      // stays valid. The anchor must still be found INSIDE the range.
      const inRange = norm(sliceLines(c.file, c.start, c.end));
      expect(inRange.includes(c.anchor!), `anchor not found in range: ${c.anchor}`).toBe(true);
    });
  }
});
```

- [ ] **Step 2: Run it to see it fail**

```powershell
npx vitest run tests/guards/citations.test.ts
```

Expected: FAIL on `finds citations to check` — no snippet or quote exists yet.

- [ ] **Step 3: Add one real snippet and one real quote**

Get the exact text first, so the snippet is copied rather than typed:

```bash
sed -n '131,140p' declaw/tools/registry.py
```

Add to the `tool-registry` component in `components.json` (replace `sources`):

```json
"snippets": [
  {
    "file": "declaw/tools/registry.py",
    "start": 131,
    "end": 140,
    "code": "<paste the exact ten lines here>",
    "caption": {
      "en": "READ external-content tools take the sanitizer branch; every non-READ tool takes the confirmation branch.",
      "vi": "Tool READ sinh nội dung ngoài đi nhánh sanitizer; mọi tool non-READ đi nhánh xác nhận."
    }
  }
],
"quotes": [
  {
    "file": "declaw/tools/registry.py",
    "start": 141,
    "end": 147,
    "anchor": "the audit wrapper is outermost",
    "note": {
      "en": "Audit wraps whichever branch was taken, so an event records the call as the model experienced it.",
      "vi": "Audit bọc bên ngoài nhánh đã chọn, nên sự kiện ghi lại lời gọi đúng như model trải nghiệm."
    }
  }
]
```

Verify the anchor text really exists in that range before saving:

```bash
sed -n '141,147p' declaw/tools/registry.py
```

- [ ] **Step 4: Run the guard**

```powershell
npx vitest run tests/guards/citations.test.ts
```

Expected: PASS.

- [ ] **Step 5: Break each behaviour and watch it fail (three separate breaks)**

1. **Verbatim** — change one character inside the snippet's `code`. Expected: FAIL on `embeds ... verbatim`. Restore.
2. **Anchor-inside-range** — change the quote's range to `start: 105, end: 112` (a valid range that no longer contains the anchor). Expected: FAIL with `anchor not found in range`. This is the exact drift the spec calls out. Restore.
3. **XOR** — add `"anchor": "x"` to the snippet record. Expected: FAIL on `is exactly one of snippet or quote`. Restore.

- [ ] **Step 6: Write `scripts/sync-snippets.mjs`**

```js
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
```

- [ ] **Step 7: Prove the sync script works and respects its limits**

Change one character in a snippet's `code`, then:

```powershell
npm run sync:snippets
npx vitest run tests/guards/citations.test.ts
```

Expected: script reports `1 snippet(s) refreshed`; guard PASSES.

Now change a **quote's** `anchor` to nonsense and run `npm run sync:snippets` again.
Expected: script reports `0 snippet(s) refreshed` and the guard still FAILS — the script must not repair anchors. Restore the anchor.

- [ ] **Step 8: Commit**

```bash
git add docs-site
git commit -m "feat(site): verbatim-snippet and anchored-quote guards with a range-only sync script"
```

---

### Task 3: module-coverage guard

**Files:**
- Create: `docs-site/tests/guards/module-coverage.test.ts`

**Interfaces:**
- Consumes: `gitTrackedFiles`, `CONTENT_DIR` from Task 1.
- Produces: `coveredModules(source: 'components' | 'all'): Set<string>`

- [ ] **Step 1: Write the failing test**

```ts
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
```

- [ ] **Step 2: Run it to see it fail**

```powershell
npx vitest run tests/guards/module-coverage.test.ts
```

Expected: FAIL — 111 of 112 modules are undocumented (only `declaw/tools/registry.py` is covered so far), and `tickets.json` does not exist yet.

- [ ] **Step 3: Create `content/tickets.json` with an empty list so the companion assertion can run**

```json
{ "tickets": [] }
```

- [ ] **Step 4: Confirm the failure is now only about coverage**

```powershell
npx vitest run tests/guards/module-coverage.test.ts
```

Expected: FAIL listing undocumented modules by name. This failing list is the worklist for Task 6 — leave it red and commit the guard.

- [ ] **Step 5: Commit the guard while it is red**

```bash
git add docs-site/tests/guards/module-coverage.test.ts docs-site/content/tickets.json
git commit -m "feat(site): module-coverage guard, counted from components only"
```

This is the one deliberate exception to committing green: the guard is correct and the content it demands is Task 6. Task 6 is not complete until this is green.

---

### Task 4: xref-bidirectional + ticket-relations guards

**Files:**
- Create: `docs-site/tests/guards/xref.test.ts`
- Create: `docs-site/scripts/derive-ticket-relations.mjs`

**Interfaces:**
- Consumes: `CONTENT_DIR` from Task 1.
- Produces: content contract — `tickets[].creates|modifies|traverses` hold **component ids**; `components[].tickets` holds **ticket ids**; `components[].detail` names a file in `content/details/`.

- [ ] **Step 1: Write the failing test `tests/guards/xref.test.ts`**

```ts
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
        const ticket = tickets.find((x) => x.id === t)!;
        const related = [...ticket.creates, ...ticket.modifies, ...ticket.traverses];
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
        const comp = components.find((x) => x.id === c)!;
        expect(comp.tickets).toContain(t.id);
      });
    }
  }
});
```

- [ ] **Step 2: Run it — expect PASS trivially (both lists are nearly empty)**

```powershell
npx vitest run tests/guards/xref.test.ts
```

Expected: PASS. A guard that passes on empty content is fine; Task 6 gives it real work. Prove it can fail now, before trusting it later.

- [ ] **Step 3: Prove the bidirectionality actually bites**

Temporarily add to `tickets.json`:

```json
{ "tickets": [ { "id": "DCL-025", "creates": ["tool-registry"], "modifies": [], "traverses": [] } ] }
```

Run. Expected: FAIL on `component tool-registry lists ticket DCL-025 back` — because `components.json` has `"tickets": []`.

Now add `"tickets": ["DCL-025"]` to the component. Run. Expected: PASS.

Then remove `creates` to make it `{"creates": [], "modifies": [], "traverses": []}`. Expected: FAIL on `relates to at least one component`. Restore.

- [ ] **Step 4: Write `scripts/derive-ticket-relations.mjs`**

```js
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
```

- [ ] **Step 5: Smoke-run it (output is used in Task 6)**

```powershell
node scripts/derive-ticket-relations.mjs
```

Expected: JSON on stdout with `DCL-0xx` entries whose `creates` are component ids. With only one component defined it will be sparse — that is correct at this point.

- [ ] **Step 6: Commit**

```bash
git add docs-site
git commit -m "feat(site): bidirectional xref guard and git-derived ticket relations"
```

---

### Task 5: i18n-complete + no-strings-in-code guards

**Files:**
- Create: `docs-site/tests/guards/i18n.test.ts`, `docs-site/tests/guards/no-strings-in-code.test.ts`

**Interfaces:**
- Produces: the rule that any object with an `en` key must also have a non-empty `vi`, recursively, in every content file.

- [ ] **Step 1: Write `tests/guards/i18n.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import { allContentFiles } from './_repo';

type Loc = { where: string; en: unknown; vi: unknown };

function collectLoc(json: unknown, where: string): Loc[] {
  const found: Loc[] = [];
  const visit = (node: unknown, trail: string) => {
    if (Array.isArray(node)) return node.forEach((n, i) => visit(n, `${trail}[${i}]`));
    if (node && typeof node === 'object') {
      const r = node as Record<string, unknown>;
      if ('en' in r || 'vi' in r) found.push({ where: `${where}${trail}`, en: r.en, vi: r.vi });
      for (const [k, v] of Object.entries(r)) visit(v, `${trail}.${k}`);
    }
  };
  visit(json, '');
  return found;
}

const strings = allContentFiles().flatMap((f) => collectLoc(f.json, f.name));

describe('every prose field is complete in both languages', () => {
  it('finds prose to check', () => {
    expect(strings.length).toBeGreaterThan(0);
  });

  for (const s of strings) {
    it(`${s.where} has both en and vi`, () => {
      expect(typeof s.en, 'missing or non-string en').toBe('string');
      expect(typeof s.vi, 'missing or non-string vi').toBe('string');
      expect((s.en as string).trim().length).toBeGreaterThan(0);
      expect((s.vi as string).trim().length).toBeGreaterThan(0);
    });
  }
});
```

- [ ] **Step 2: Run, then break it**

```powershell
npx vitest run tests/guards/i18n.test.ts
```

Expected: PASS. Now delete the `vi` field from `ui.json`'s `site.title`. Expected: FAIL on `has both en and vi`. Restore.

- [ ] **Step 3: Write `tests/guards/no-strings-in-code.test.ts`**

```ts
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(here, '../../src');

function tsxFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return tsxFiles(full);
    return e.name.endsWith('.tsx') ? [full] : [];
  });
}

// Allowlist: whitespace, punctuation and digits carry no meaning to translate.
const MEANINGLESS = /^[\s\p{P}\p{S}\d]*$/u;
const JSX_TEXT = />([^<>{}]+)</g;
const LITERAL_ATTR = /\s(?:aria-label|title|placeholder|alt)\s*=\s*"([^"]*)"/g;

describe('no user-visible string is written in code', () => {
  const files = tsxFiles(SRC);

  it('finds tsx files to scan', () => {
    expect(files.length).toBeGreaterThan(0);
  });

  for (const file of files) {
    const rel = path.relative(SRC, file);
    const source = readFileSync(file, 'utf8');

    it(`${rel} has no literal JSX text`, () => {
      const offenders = [...source.matchAll(JSX_TEXT)]
        .map((m) => m[1])
        .filter((t) => !MEANINGLESS.test(t));
      expect(offenders, `move these into content/: ${offenders.join(' | ')}`).toEqual([]);
    });

    it(`${rel} has no literal aria-label/title/placeholder/alt`, () => {
      const offenders = [...source.matchAll(LITERAL_ATTR)]
        .map((m) => m[1])
        .filter((t) => !MEANINGLESS.test(t));
      expect(offenders, `move these into content/: ${offenders.join(' | ')}`).toEqual([]);
    });
  }
});
```

- [ ] **Step 4: Break it deliberately**

Add `<span aria-label="Close">x</span>` to `App.tsx`, run:

```powershell
npx vitest run tests/guards/no-strings-in-code.test.ts
```

Expected: FAIL twice — once for the literal text `x`... (note: single letter `x` is meaningful, so it is caught) and once for `aria-label="Close"`. Restore `App.tsx`.

- [ ] **Step 5: Record the guard's known limit in a comment**

Add to the top of the file:

```ts
// Limit, stated so nobody over-trusts this: it is a lint over JSX shapes.
// A string smuggled through a helper function (e.g. label("Close")) evades it.
// It is a tripwire for the common mistake, not a proof of absence.
```

- [ ] **Step 6: Commit**

```bash
git add docs-site/tests/guards
git commit -m "feat(site): bilingual-completeness and no-copy-in-code guards"
```

---

### Task 6: Author the base content — components covering all 112 modules, principles, tickets

**Files:**
- Modify: `docs-site/content/components.json` (full component set)
- Create: `docs-site/content/principles.json`
- Modify: `docs-site/content/tickets.json` (from the derive script + curated `traverses`)

**Interfaces:**
- Produces: the component id vocabulary every later task consumes:
  `entry-cli`, `brain-loop`, `brain-model`, `brain-repl`, `brain-eval`, `tool-base`, `tool-registry`, `tool-filesystem`, `sanitizer`, `sanitizer-corpus`, `memory`, `audit`, `persistence`, `credentials`, `plugin-host`, `plugin-sdk`, `documents`, `doc-intel-plugin`, `planned-surfaces`, `dev-tooling`.

- [ ] **Step 1: Get the authoritative module list**

```bash
git ls-files '*.py' | grep -v '^tests/' | sort
```

Expected: 112 paths. Every one must land in exactly one component's `modules[]` (duplication is allowed by the guard but avoid it — one home per module keeps the grid honest).

- [ ] **Step 2: Assign modules to components using this mapping**

| Component id | group | tier | modules |
|---|---|---|---|
| `entry-cli` | entry | B | `declaw/__init__.py`, `declaw/main.py`, `declaw/config.py`, `declaw/log.py`, `declaw/preflight.py` |
| `brain-loop` | brain | A | `declaw/brain/__init__.py`, `declaw/brain/loop.py`, `declaw/brain/state.py` |
| `brain-model` | brain | B | `declaw/brain/chat_model.py`, `declaw/brain/ollama_client.py`, `declaw/brain/context.py`, `declaw/brain/compaction.py`, `declaw/brain/repair.py`, `declaw/brain/memory_context.py` |
| `brain-repl` | brain | B | `declaw/brain/repl.py`, `declaw/brain/prompts.py`, `declaw/brain/stub_tools.py` |
| `brain-eval` | brain | B | `declaw/brain/eval.py` |
| `tool-base` | tools | B | `declaw/tools/__init__.py`, `declaw/tools/base.py` |
| `tool-registry` | tools | A | `declaw/tools/registry.py`, `declaw/tools/confirmation.py` |
| `tool-filesystem` | tools | B | `declaw/tools/builtin/__init__.py`, `declaw/tools/builtin/filesystem.py`, `declaw/tools/builtin/_paths.py` |
| `sanitizer` | security | A | `declaw/sanitizer/__init__.py`, `classifier.py`, `pipeline.py`, `sanitizer.py`, `prompts.py`, `verdict.py`, `quarantine.py`, `benchmark.py` (all under `declaw/sanitizer/`) |
| `sanitizer-corpus` | security | B | the 5 files under `declaw/sanitizer/corpus/` |
| `memory` | memory | B | the 8 files under `declaw/memory/` |
| `audit` | audit | A | the 9 files under `declaw/audit/` |
| `persistence` | data | B | the 3 files under `declaw/db/` |
| `credentials` | security | B | the 3 files under `declaw/credentials/` |
| `plugin-host` | plugins | A | the 14 files under `declaw/plugin_host/` |
| `plugin-sdk` | plugins | A | the 6 files under `declaw_plugin_sdk/` |
| `documents` | documents | A | the 11 files under `declaw/documents/` |
| `doc-intel-plugin` | plugins | B | the 8 files under `plugins/builtin/doc-intel/` |
| `planned-surfaces` | planned | B | `declaw/gateway/__init__.py`, `declaw/gateway/routes/__init__.py`, `declaw/sandbox/__init__.py` |
| `dev-tooling` | tooling | B | the 4 files under `scripts/`, plus `alembic/env.py` and the 4 files under `alembic/versions/` |

`documents` is Tier A but covers both indexing and search; it declares two flows in Task 13.

`planned-surfaces` is the honest-debt component: three zero-byte `__init__.py` files for subsystems that are declared in the architecture but not built. Its summary must say exactly that.

- [ ] **Step 3: Write `content/principles.json`**

Source the wording from `CLAUDE.md`'s "The 7 Inviolable Principles" section. Each entry:

```json
{
  "principles": [
    {
      "id": "P1",
      "title": { "en": "Never store credentials in plaintext", "vi": "Không bao giờ lưu credential dạng plaintext" },
      "body": {
        "en": "Credentials always go through python-keyring, with an AES-256-GCM file only when keyring resolves to its fail backend.",
        "vi": "Credential luôn đi qua python-keyring; chỉ dùng file AES-256-GCM khi keyring rơi vào backend fail."
      },
      "source": {
        "file": "CLAUDE.md",
        "start": 0,
        "end": 0,
        "anchor": "NEVER store credentials in plaintext",
        "note": { "en": "Stated in the project's living context.", "vi": "Ghi trong tài liệu ngữ cảnh sống của dự án." }
      }
    }
  ]
}
```

Find the real line numbers first — do not guess:

```bash
grep -n "NEVER store credentials in plaintext" CLAUDE.md
```

Use the returned line number for both `start` and `end`, and the guard from Task 2 will confirm the anchor sits inside it.

- [ ] **Step 4: Generate ticket relations and add `traverses` by hand**

```powershell
node scripts/derive-ticket-relations.mjs > content/tickets.json
```

Then, for each ticket, add `title`, `phase`, `status` (read from `TICKETS.md`), and curate `traverses`: components the ticket's flow **passes through but never edits**. Worked example — `DCL-110` (document_search tool) creates/modifies `documents`, and **traverses** `tool-registry` (its tool is registered and wrapped there), `sanitizer` (retrieval-time classification) and `brain-loop` (the model calls it). Without those three, the ticket's request renders as a pipeline that stops in the middle.

- [ ] **Step 5: Run all guards**

```powershell
npx vitest run
```

Expected: PASS, including the module-coverage guard left red in Task 3. If a module is missing, the failure names it.

- [ ] **Step 6: Break coverage deliberately**

Create an empty `declaw/scratch_probe.py`, `git add` it, re-run the guard.
Expected: FAIL — `declaw/scratch_probe.py appears in no component's modules[]`.

Now add it **only to `tickets.json`** as `modulesTouched`. Re-run.
Expected: still FAIL, plus the companion assertion fires. This is the "a ticket mention is not documentation" rule proving itself.

Delete the file (`git rm -f declaw/scratch_probe.py`) and re-run. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docs-site/content
git commit -m "feat(site): component grid covering every source module, principles, ticket relations"
```

---

### Task 7: Language runtime and the pure route module

**Files:**
- Create: `docs-site/src/content/types.ts`, `docs-site/src/content/load.ts`, `docs-site/src/i18n/lang.tsx`, `docs-site/src/router/route.ts`
- Create: `docs-site/tests/ui/route.test.ts`

**Interfaces:**
- Produces:
  - `type Lang = 'en' | 'vi'`, `type Loc = { en: string; vi: string }`
  - `useLang(): { lang: Lang; setLang(l: Lang): void }`, `useT(): (loc: Loc) => string`
  - `type Route = { segments: string[]; query: Record<string, string> }`
  - `parseHash(hash: string): Route`, `formatHash(route: Route): string`, `parentRoute(route: Route): Route | null`

- [ ] **Step 1: Write the failing test `tests/ui/route.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import { formatHash, parentRoute, parseHash } from '../../src/router/route';

describe('route parsing', () => {
  it('reads segments and query', () => {
    const r = parseHash('#/component/tool-registry/fn/langchain_tools?lang=vi');
    expect(r.segments).toEqual(['component', 'tool-registry', 'fn', 'langchain_tools']);
    expect(r.query.lang).toBe('vi');
  });

  it('treats an empty hash as the root route', () => {
    expect(parseHash('').segments).toEqual([]);
  });

  it('round-trips', () => {
    const hash = '#/components?phase=8a&lang=en';
    expect(formatHash(parseHash(hash))).toBe(hash);
  });
});

describe('parentRoute pops exactly one panel level', () => {
  it('pops a function panel off a component route', () => {
    const r = parseHash('#/component/tool-registry/fn/langchain_tools');
    expect(parentRoute(r)!.segments).toEqual(['component', 'tool-registry']);
  });

  it('pops an edge panel off the map route', () => {
    const r = parseHash('#/map/edge/host-plugin');
    expect(parentRoute(r)!.segments).toEqual(['map']);
  });

  it('preserves the query when popping, so language survives Escape', () => {
    const r = parseHash('#/map/edge/host-plugin?lang=vi');
    expect(parentRoute(r)!.query.lang).toBe('vi');
  });

  it('returns null at a top-level view, so Escape does nothing there', () => {
    expect(parentRoute(parseHash('#/map'))).toBeNull();
    expect(parentRoute(parseHash(''))).toBeNull();
  });
});
```

- [ ] **Step 2: Run it to see it fail**

```powershell
npx vitest run tests/ui/route.test.ts
```

Expected: FAIL — cannot resolve `../../src/router/route`.

- [ ] **Step 3: Implement `src/router/route.ts`**

```ts
export type Route = { segments: string[]; query: Record<string, string> };

/** Segments that open a panel as a `key/value` pair; Escape pops one such pair. */
const PANEL_KEYS = new Set(['fn', 'edge', 'store', 'debt']);

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '');
  const [pathPart, queryPart] = raw.split('?');
  const segments = pathPart.split('/').filter(Boolean);
  const query: Record<string, string> = {};
  for (const [k, v] of new URLSearchParams(queryPart ?? '')) query[k] = v;
  return { segments, query };
}

export function formatHash(route: Route): string {
  const path = route.segments.join('/');
  const params = new URLSearchParams(route.query).toString();
  return `#/${path}${params ? `?${params}` : ''}`;
}

/**
 * One level up, or null at a top-level view.
 *
 * Escape must pop exactly one layer per press, and the route — not a
 * mount-order stack — is the authority: a panel still playing its exit
 * transition is mounted, and a stack would let it swallow the next key.
 */
export function parentRoute(route: Route): Route | null {
  const s = route.segments;
  if (s.length >= 2 && PANEL_KEYS.has(s[s.length - 2])) {
    return { segments: s.slice(0, -2), query: route.query };
  }
  return null;
}
```

- [ ] **Step 4: Run the test**

Expected: PASS (all 7).

- [ ] **Step 5: Break it and watch it fail**

Change `parentRoute` to `s.slice(0, -1)` (pop one segment instead of the pair).
Expected: FAIL on `pops a function panel off a component route` — it would leave `['component','tool-registry','fn']`. Restore.

- [ ] **Step 6: Implement `src/content/types.ts`**

```ts
export type Lang = 'en' | 'vi';
export type Loc = { en: string; vi: string };

export type Snippet = { file: string; start: number; end: number; code: string; caption: Loc };
export type Quote = { file: string; start: number; end: number; anchor: string; note: Loc };

export type FlowNode = { id: string; kind: 'port' | 'step' | 'gate' | 'exit'; label: Loc };
export type FlowEdge = { id: string; from: string; to: string; label: Loc };
export type Flow = { id: string; title: Loc; nodes: FlowNode[]; edges: FlowEdge[] };

export type FunctionRef = {
  id: string; name: string; signature: string; file: string; line: number; note: Loc;
};

export type Why = { id: string; title: Loc; body: Loc; source: Quote; principles: string[] };

export type Detail = {
  component: string;
  functions: FunctionRef[];
  flows: Flow[];
  snippets: Snippet[];
  quotes: Quote[];
  why: Why[];
};

export type Component = {
  id: string; group: string; tier: 'A' | 'B';
  title: Loc; summary: Loc;
  modules: string[]; tickets: string[]; detail?: string;
  snippets?: Snippet[]; quotes?: Quote[];
};

export type Ticket = {
  id: string; phase: string; status: string; title: Loc;
  creates: string[]; modifies: string[]; traverses: string[];
};

export type Contract = {
  transport: Loc; method: string | null; path: string | null; auth: Loc;
  request: Loc; response: Loc;
  errors: { code: string; meaning: Loc }[];
  source: Quote;
};

export type SystemNode = {
  id: string; kind: 'core' | 'external' | 'store' | 'planned';
  label: Loc; note: Loc; column: number;
};
export type SystemEdge = {
  id: string; from: string; to: string; label: Loc; contract: Contract; principles: string[];
};

export type Store = {
  id: string; label: Loc; kind: Loc; lifetime: Loc;
  owner: string; writers: string[]; readers: string[]; enforcement: Quote;
};

export type Principle = { id: string; title: Loc; body: Loc; source: Quote };

export type DebtItem = {
  id: string; title: Loc; body: Loc;
  severity: 'unbuilt' | 'unvalidated' | 'temporary';
  components: string[]; source: Quote;
};
```

- [ ] **Step 7: Implement `src/content/load.ts`**

```ts
import componentsJson from '../../content/components.json';
import debtJson from '../../content/debt.json';
import ownershipJson from '../../content/ownership.json';
import principlesJson from '../../content/principles.json';
import systemsJson from '../../content/systems.json';
import ticketsJson from '../../content/tickets.json';
import uiJson from '../../content/ui.json';
import type {
  Component, DebtItem, Principle, Store, SystemEdge, SystemNode, Ticket,
} from './types';

export const components = (componentsJson as { components: Component[] }).components;
export const tickets = (ticketsJson as { tickets: Ticket[] }).tickets;
export const principles = (principlesJson as { principles: Principle[] }).principles;
export const stores = (ownershipJson as { stores: Store[] }).stores;
export const systemNodes = (systemsJson as { nodes: SystemNode[] }).nodes;
export const systemEdges = (systemsJson as { edges: SystemEdge[] }).edges;
export const debt = (debtJson as { items: DebtItem[] }).items;
export const ui = uiJson as Record<string, Record<string, { en: string; vi: string }>>;

export const componentById = new Map(components.map((c) => [c.id, c]));
export const ticketById = new Map(tickets.map((t) => [t.id, t]));
export const principleById = new Map(principles.map((p) => [p.id, p]));

/** Details are loaded lazily so one big JSON per component never blocks first paint. */
const detailModules = import.meta.glob('../../content/details/*.json');
export async function loadDetail(name: string) {
  const key = `../../content/details/${name}.json`;
  const mod = (await detailModules[key]()) as { default: unknown };
  return mod.default;
}
```

- [ ] **Step 8: Implement `src/i18n/lang.tsx`**

```tsx
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import type { Lang, Loc } from '../content/types';

type LangValue = { lang: Lang; setLang: (l: Lang) => void };
const LangContext = createContext<LangValue>({ lang: 'en', setLang: () => {} });

export function LangProvider(props: { lang: Lang; setLang: (l: Lang) => void; children: ReactNode }) {
  const value = useMemo(() => ({ lang: props.lang, setLang: props.setLang }), [props.lang, props.setLang]);
  return <LangContext.Provider value={value}>{props.children}</LangContext.Provider>;
}

export function useLang(): LangValue {
  return useContext(LangContext);
}

/** Resolve a bilingual record against the active language. */
export function useT(): (loc: Loc) => string {
  const { lang } = useLang();
  return (loc: Loc) => loc[lang];
}
```

- [ ] **Step 9: Run every test, then commit**

```powershell
npx vitest run
```

```bash
git add docs-site
git commit -m "feat(site): typed content loading, language context, pure route module"
```

---

### Task 8: Router — one Escape listener, correct history, focus return

**Files:**
- Create: `docs-site/src/router/Router.tsx`
- Create: `docs-site/tests/ui/router.test.tsx`
- Modify: `docs-site/src/App.tsx`

**Interfaces:**
- Consumes: `parseHash`, `formatHash`, `parentRoute` (Task 7).
- Produces: `useRoute(): Route`, `navigate(route: Route, opts?: { replace?: boolean }): void`, `<RouterProvider>`, and the DOM contract that a panel root carries `data-panel-heading` (focus target) and its trigger carries `data-route-target="<child segment id>"`.

- [ ] **Step 1: Write the failing test `tests/ui/router.test.tsx`**

```tsx
/** @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { RouterProvider, useNavigate, useRoute } from '../../src/router/Router';

function Harness() {
  const route = useRoute();
  const navigate = useNavigate();
  const depth = route.segments.length;
  return (
    <div>
      <span data-testid="hash">{route.segments.join('/')}</span>
      <button
        data-route-target="edge"
        onClick={() => navigate({ segments: ['map', 'edge', 'e1'], query: {} })}
      />
      {depth >= 3 && (
        <div data-panel-heading tabIndex={-1} data-testid="panel">
          <button
            data-route-target="fn"
            onClick={() => navigate({ segments: ['map', 'edge', 'e1', 'fn', 'f1'], query: {} })}
          />
        </div>
      )}
      {depth >= 5 && <div data-panel-heading tabIndex={-1} data-testid="panel2" />}
    </div>
  );
}

const renderApp = () =>
  render(
    <RouterProvider>
      <Harness />
    </RouterProvider>,
  );

beforeEach(() => {
  window.location.hash = '#/map';
});

describe('Escape closes exactly one layer', () => {
  it('pops one panel per press, not the whole stack', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(screen.getAllByRole('button')[0]);
    await user.click(screen.getByTestId('panel').querySelector('button')!);
    expect(screen.getByTestId('hash').textContent).toBe('map/edge/e1/fn/f1');

    await user.keyboard('{Escape}');
    expect(screen.getByTestId('hash').textContent).toBe('map/edge/e1');

    await user.keyboard('{Escape}');
    expect(screen.getByTestId('hash').textContent).toBe('map');
  });

  it('does nothing at a top-level view', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.keyboard('{Escape}');
    expect(screen.getByTestId('hash').textContent).toBe('map');
  });
});

describe('focus', () => {
  it('moves focus into an opened panel', async () => {
    const user = userEvent.setup();
    renderApp();
    await user.click(screen.getAllByRole('button')[0]);
    expect(document.activeElement).toBe(screen.getByTestId('panel'));
  });

  it('returns focus to the trigger when Escape closes the panel', async () => {
    const user = userEvent.setup();
    renderApp();
    const trigger = screen.getAllByRole('button')[0];
    await user.click(trigger);
    await user.keyboard('{Escape}');
    expect(document.activeElement).toBe(trigger);
  });
});
```

- [ ] **Step 2: Run to see it fail**

Expected: FAIL — module `../../src/router/Router` not found.

- [ ] **Step 3: Implement `src/router/Router.tsx`**

```tsx
import {
  createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState,
  type ReactNode,
} from 'react';
import { formatHash, parentRoute, parseHash, type Route } from './route';

type NavOptions = { replace?: boolean };
type RouterValue = { route: Route; navigate: (r: Route, o?: NavOptions) => void };

const RouterContext = createContext<RouterValue | null>(null);

export function useRoute(): Route {
  return useContext(RouterContext)!.route;
}
export function useNavigate(): (r: Route, o?: NavOptions) => void {
  return useContext(RouterContext)!.navigate;
}

export function RouterProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  // Depths this router pushed itself. Escape can then use history.back() —
  // which keeps history from growing — and fall back to a replacing
  // navigation for a visitor who arrived by deep link, whose first Back
  // press would otherwise leave the site.
  const pushedDepths = useRef<Set<number>>(new Set());
  const lastTrigger = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const navigate = useCallback((next: Route, opts?: NavOptions) => {
    lastTrigger.current = document.activeElement as HTMLElement | null;
    const hash = formatHash(next);
    if (opts?.replace) {
      window.history.replaceState(null, '', hash);
      setRoute(next);
      return;
    }
    pushedDepths.current.add(next.segments.length);
    window.location.hash = hash;
  }, []);

  // The ONLY Escape listener in the app. stopPropagation does not separate
  // listeners bound to the same target, so per-panel document listeners would
  // close every open panel at once and push several history entries.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      const parent = parentRoute(parseHash(window.location.hash));
      if (!parent) return;
      event.preventDefault();
      const current = parseHash(window.location.hash).segments.length;
      const trigger = lastTrigger.current;
      if (pushedDepths.current.has(current)) {
        pushedDepths.current.delete(current);
        window.history.back();
      } else {
        window.history.replaceState(null, '', formatHash(parent));
        setRoute(parent);
      }
      window.setTimeout(() => trigger?.focus(), 0);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  // Move focus into a panel when one opens, so keyboard users are not left
  // behind at the trigger while the content changes elsewhere.
  const depth = route.segments.length;
  const previousDepth = useRef(depth);
  useLayoutEffect(() => {
    if (depth > previousDepth.current) {
      const panels = document.querySelectorAll<HTMLElement>('[data-panel-heading]');
      panels[panels.length - 1]?.focus();
    }
    previousDepth.current = depth;
  }, [depth]);

  return (
    <RouterContext.Provider value={{ route, navigate }}>{children}</RouterContext.Provider>
  );
}
```

- [ ] **Step 4: Run the test**

Expected: PASS (4 tests). If `history.back()` proves asynchronous in jsdom, wait with `await screen.findByTestId(...)` rather than weakening the assertion.

- [ ] **Step 5: Break each behaviour (three separate breaks)**

1. Register a second Escape listener inside the `Harness` panel that also navigates to the parent. Expected: FAIL on `pops one panel per press` (both layers close at once) — this reproduces the exact bug the design rejects. Remove it.
2. Delete the focus-into-panel effect. Expected: FAIL on `moves focus into an opened panel`. Restore.
3. Delete the `trigger?.focus()` line. Expected: FAIL on `returns focus to the trigger`. Restore.

- [ ] **Step 6: Wire `App.tsx` to the provider (still no copy in code)**

```tsx
import { LangProvider } from './i18n/lang';
import { RouterProvider, useRoute } from './router/Router';
import { useState } from 'react';
import type { Lang } from './content/types';

function Shell() {
  const route = useRoute();
  return <main id="app" data-view={route.segments[0] ?? 'map'} />;
}

export function App() {
  const [lang, setLang] = useState<Lang>('en');
  return (
    <RouterProvider>
      <LangProvider lang={lang} setLang={setLang}>
        <Shell />
      </LangProvider>
    </RouterProvider>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add docs-site
git commit -m "feat(site): route-owned Escape, history discipline, focus return"
```

---

### Task 9: Diagram core — text wrapping and lane layout (pure functions)

**Files:**
- Create: `docs-site/src/diagram/wrapText.ts`, `docs-site/src/diagram/layout.ts`
- Create: `docs-site/tests/ui/diagram-layout.test.ts`

**Interfaces:**
- Produces:
  - `wrapText(text: string, maxWidthPx: number, fontSizePx: number): string[]`
  - `estimateTextWidth(text: string, fontSizePx: number): number`
  - `layoutGraph(input: LayoutInput): LayoutResult` where
    `LayoutInput = { nodes: {id, label, column}[], edges: {id, from, to, label}[], lang, box: {maxWidth, fontSize, padding, lineHeight}, columnGap: number }`
    and `LayoutResult = { boxes: Map<string, Box>, routes: EdgeRoute[], width: number, height: number }`,
    `Box = { id, x, y, w, h, lines: string[] }`,
    `EdgeRoute = { id, points: {x,y}[], labelX, labelY, lane: number }`

- [ ] **Step 1: Write the failing test `tests/ui/diagram-layout.test.ts`**

```ts
import { describe, expect, it } from 'vitest';
import { estimateTextWidth, wrapText } from '../../src/diagram/wrapText';
import { layoutGraph } from '../../src/diagram/layout';
import { systemEdges, systemNodes } from '../../src/content/load';

const BOX = { maxWidth: 180, fontSize: 13, padding: 10, lineHeight: 17 };

describe('wrapText', () => {
  it('breaks a long label into several lines', () => {
    const lines = wrapText('Ollama local inference daemon on 127.0.0.1', 180, 13);
    expect(lines.length).toBeGreaterThan(1);
  });

  it('never emits a line wider than the budget', () => {
    // SVG <text> does not wrap. An overflowing line runs outside its box and
    // over whatever sits beside it.
    for (const line of wrapText('Plugin subprocess over NDJSON stdio', 180, 13)) {
      expect(estimateTextWidth(line, 13)).toBeLessThanOrEqual(180);
    }
  });

  it('keeps a single unbreakable token rather than dropping it', () => {
    expect(wrapText('declaw_plugin_sdk.protocol', 40, 13)).toEqual(['declaw_plugin_sdk.protocol']);
  });
});

describe('layout in both languages', () => {
  for (const lang of ['en', 'vi'] as const) {
    it(`${lang}: every box is tall enough for its wrapped lines`, () => {
      const result = layoutGraph({
        nodes: systemNodes.map((n) => ({ id: n.id, label: n.label[lang], column: n.column })),
        edges: systemEdges.map((e) => ({ id: e.id, from: e.from, to: e.to, label: e.label[lang] })),
        box: BOX,
        columnGap: 220,
      });
      for (const box of result.boxes.values()) {
        expect(box.h).toBeGreaterThanOrEqual(box.lines.length * BOX.lineHeight + BOX.padding * 2);
        for (const line of box.lines) {
          expect(estimateTextWidth(line, BOX.fontSize)).toBeLessThanOrEqual(BOX.maxWidth);
        }
      }
    });
  }
});

describe('parallel edges', () => {
  const input = {
    nodes: [
      { id: 'a', label: 'A', column: 0 },
      { id: 'b', label: 'B', column: 1 },
    ],
    edges: [
      { id: 'e1', from: 'a', to: 'b', label: 'first' },
      { id: 'e2', from: 'a', to: 'b', label: 'second' },
      { id: 'e3', from: 'b', to: 'a', label: 'third (reverse)' },
    ],
    box: BOX,
    columnGap: 220,
  };

  it('gives every edge between the same pair its own lane', () => {
    const { routes } = layoutGraph(input);
    expect(new Set(routes.map((r) => r.lane)).size).toBe(routes.length);
  });

  it('never places two labels at the same point', () => {
    // Two edges in opposite directions both resolve to the source box centre
    // if labels are anchored there — one line, a pile of labels.
    const { routes } = layoutGraph(input);
    const seen = new Set(routes.map((r) => `${Math.round(r.labelX)},${Math.round(r.labelY)}`));
    expect(seen.size).toBe(routes.length);
  });

  it('places each label on its own routed segment, not at the source box', () => {
    const { routes, boxes } = layoutGraph(input);
    const a = boxes.get('a')!;
    for (const r of routes) {
      const atSourceCentre =
        Math.abs(r.labelX - (a.x + a.w / 2)) < 1 && Math.abs(r.labelY - (a.y + a.h / 2)) < 1;
      expect(atSourceCentre).toBe(false);
    }
  });

  it('demands a column gap wide enough for the lanes crossing it', () => {
    expect(() => layoutGraph({ ...input, columnGap: 40 })).toThrow(/column gap/i);
  });
});
```

- [ ] **Step 2: Run to see it fail**

Expected: FAIL — modules not found.

- [ ] **Step 3: Implement `src/diagram/wrapText.ts`**

```ts
/**
 * Width estimate for a glyph run, in px.
 *
 * Deliberately conservative: over-estimating pushes a break earlier, which is
 * survivable, while under-estimating overflows the box. Vietnamese diacritics
 * do not widen a glyph, but Vietnamese phrasing is longer than English, so
 * both languages must be laid out and checked.
 */
const WIDE = /[MWmw@%]/;
const NARROW = /[ijltfr.,:;'`!|]/;

export function estimateTextWidth(text: string, fontSizePx: number): number {
  let units = 0;
  for (const ch of text) {
    if (WIDE.test(ch)) units += 0.78;
    else if (NARROW.test(ch)) units += 0.32;
    else units += 0.55;
  }
  return units * fontSizePx;
}

/** Greedy wrap into lines that fit `maxWidthPx`. An unbreakable token is kept whole. */
export function wrapText(text: string, maxWidthPx: number, fontSizePx: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [''];
  const lines: string[] = [];
  let current = '';
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (estimateTextWidth(candidate, fontSizePx) <= maxWidthPx || current === '') {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines;
}
```

- [ ] **Step 4: Implement `src/diagram/layout.ts`**

```ts
import { estimateTextWidth, wrapText } from './wrapText';

export type BoxStyle = { maxWidth: number; fontSize: number; padding: number; lineHeight: number };
export type LayoutInput = {
  nodes: { id: string; label: string; column: number }[];
  edges: { id: string; from: string; to: string; label: string }[];
  box: BoxStyle;
  columnGap: number;
};
export type Box = { id: string; x: number; y: number; w: number; h: number; lines: string[] };
export type EdgeRoute = {
  id: string; points: { x: number; y: number }[]; labelX: number; labelY: number; lane: number;
};
export type LayoutResult = {
  boxes: Map<string, Box>; routes: EdgeRoute[]; width: number; height: number;
};

const LANE_SPACING = 26;
const ROW_GAP = 28;

/** Unordered pair key: two edges between the same nodes share lanes even in opposite directions. */
const pairKey = (a: string, b: string) => [a, b].sort().join('::');

export function layoutGraph(input: LayoutInput): LayoutResult {
  const { box, columnGap } = input;

  const lanesByPair = new Map<string, number>();
  for (const e of input.edges) {
    const key = pairKey(e.from, e.to);
    lanesByPair.set(key, (lanesByPair.get(key) ?? 0) + 1);
  }
  const maxLanes = Math.max(0, ...lanesByPair.values());
  const required = maxLanes * LANE_SPACING;
  if (columnGap < required) {
    throw new Error(
      `column gap ${columnGap}px is too narrow: ${maxLanes} lanes need at least ${required}px`,
    );
  }

  const columns = new Map<number, typeof input.nodes>();
  for (const node of input.nodes) {
    const list = columns.get(node.column) ?? [];
    list.push(node);
    columns.set(node.column, list);
  }

  const boxes = new Map<string, Box>();
  let width = 0;
  let height = 0;
  for (const [columnIndex, nodes] of [...columns.entries()].sort(([a], [b]) => a - b)) {
    let y = 0;
    for (const node of nodes) {
      const lines = wrapText(node.label, box.maxWidth, box.fontSize);
      const w =
        Math.min(box.maxWidth, Math.max(...lines.map((l) => estimateTextWidth(l, box.fontSize)))) +
        box.padding * 2;
      const h = lines.length * box.lineHeight + box.padding * 2;
      const x = columnIndex * (box.maxWidth + box.padding * 2 + columnGap);
      boxes.set(node.id, { id: node.id, x, y, w, h, lines });
      y += h + ROW_GAP;
      width = Math.max(width, x + w);
      height = Math.max(height, y);
    }
  }

  const laneCursor = new Map<string, number>();
  const routes: EdgeRoute[] = input.edges.map((edge) => {
    const from = boxes.get(edge.from)!;
    const to = boxes.get(edge.to)!;
    const key = pairKey(edge.from, edge.to);
    const lane = laneCursor.get(key) ?? 0;
    laneCursor.set(key, lane + 1);

    const forward = from.x <= to.x;
    const startX = forward ? from.x + from.w : from.x;
    const endX = forward ? to.x : to.x + to.w;
    const startY = from.y + from.h / 2;
    const endY = to.y + to.h / 2;
    // Each lane gets its own vertical corridor inside the gap, so parallel
    // edges never collapse into one line.
    const midX = startX + (endX - startX) / 2 + (lane - (lanesByPair.get(key)! - 1) / 2) * LANE_SPACING;

    const points = [
      { x: startX, y: startY },
      { x: midX, y: startY },
      { x: midX, y: endY },
      { x: endX, y: endY },
    ];
    // The label sits at the midpoint of THIS edge's own vertical corridor.
    // Anchoring at the source box centre gives every edge leaving that box the
    // same point, which is how a pile of overlapping labels happens.
    return { id: edge.id, points, labelX: midX, labelY: (startY + endY) / 2, lane };
  });

  return { boxes, routes, width, height: height + ROW_GAP };
}
```

- [ ] **Step 5: Run the tests**

Expected: PASS. The "both languages" tests need `systems.json` — if it does not exist yet, create it now with two nodes and one edge so the test has data; Task 11 fills it out.

- [ ] **Step 6: Break each behaviour (three breaks)**

1. In `layoutGraph`, set `midX` to `from.x + from.w / 2` for every edge. Expected: FAIL on `never places two labels at the same point` **and** `places each label on its own routed segment`. Restore.
2. Remove the `columnGap < required` throw. Expected: FAIL on `demands a column gap wide enough`. Restore.
3. In `wrapText`, return `[text]` unconditionally. Expected: FAIL on `breaks a long label into several lines` and on the per-language box tests. Restore.

- [ ] **Step 7: Commit**

```bash
git add docs-site
git commit -m "feat(site): SVG text wrapping and multi-lane edge routing"
```

---

### Task 10: Diagram renderer, companion list, dimming, and the diagram-labels guard

**Files:**
- Create: `docs-site/src/diagram/Diagram.tsx`, `docs-site/src/diagram/CompanionList.tsx`
- Create: `docs-site/tests/ui/diagram.test.tsx`, `docs-site/tests/guards/diagram-labels.test.ts`

**Interfaces:**
- Consumes: `layoutGraph`, `wrapText` (Task 9); `useT` (Task 7).
- Produces: `<Diagram nodes edges dimmed onSelect ariaKey />` and `<CompanionList nodes edges onSelect />`. `dimmed: Set<string>` names node ids to fade. Dimming is applied as **inline `opacity` on each node's parent `<g>`**.

- [ ] **Step 1: Write the failing test `tests/ui/diagram.test.tsx`**

```tsx
/** @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Diagram } from '../../src/diagram/Diagram';
import { LangProvider } from '../../src/i18n/lang';

const nodes = [
  { id: 'a', label: { en: 'Intake', vi: 'Cổng vào' }, column: 0, kind: 'port' as const },
  { id: 'b', label: { en: 'Sanitizer', vi: 'Bộ lọc' }, column: 1, kind: 'step' as const },
];
const edges = [
  { id: 'e1', from: 'a', to: 'b', label: { en: 'file content', vi: 'nội dung tệp' } },
];

const renderDiagram = (dimmed: Set<string>) =>
  render(
    <LangProvider lang="en" setLang={() => {}}>
      <Diagram nodes={nodes} edges={edges} dimmed={dimmed} onSelect={() => {}} />
    </LangProvider>,
  );

describe('dimming', () => {
  it('fades a dimmed node via inline opacity on its group', () => {
    // The class-only approach fails silently the moment anything writes inline
    // opacity on the same element. Asserting the computed inline value is the
    // only check that stays honest.
    renderDiagram(new Set(['a']));
    const group = document.querySelector('[data-node-group="a"]') as SVGGElement;
    expect(Number(group.style.opacity)).toBeLessThan(1);
  });

  it('leaves a matching node fully opaque', () => {
    renderDiagram(new Set(['a']));
    const group = document.querySelector('[data-node-group="b"]') as SVGGElement;
    expect(Number(group.style.opacity)).toBe(1);
  });
});

describe('the companion list is the keyboard surface', () => {
  it('offers a real button for every node', () => {
    renderDiagram(new Set());
    for (const node of nodes) {
      expect(screen.getByRole('button', { name: node.label.en })).toBeTruthy();
    }
  });

  it('offers a real button for every edge, carrying its label', () => {
    renderDiagram(new Set());
    expect(screen.getByRole('button', { name: /file content/ })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run to see it fail.** Expected: module not found.

- [ ] **Step 3: Implement `src/diagram/CompanionList.tsx`**

```tsx
import { useT } from '../i18n/lang';
import type { Loc } from '../content/types';

export type ListNode = { id: string; label: Loc; kind: string };
export type ListEdge = { id: string; from: string; to: string; label: Loc };

/**
 * The diagram's text equivalent, and its keyboard surface.
 *
 * It is always rendered — never a collapsed fallback — because a diagram that
 * is aria-hidden with an incomplete substitute is worse than no diagram: a
 * function list carries no edge labels and no gate branch labels, so all the
 * branching logic disappears. Building this from the same records as the SVG
 * makes losing a label impossible.
 */
export function CompanionList(props: {
  nodes: ListNode[];
  edges: ListEdge[];
  onSelect: (kind: 'node' | 'edge', id: string) => void;
}) {
  const t = useT();
  const labelOf = (id: string) => {
    const node = props.nodes.find((n) => n.id === id);
    return node ? t(node.label) : id;
  };
  return (
    <ul className="companion-list">
      {props.nodes.map((node) => (
        <li key={node.id}>
          <button type="button" onClick={() => props.onSelect('node', node.id)}>
            {t(node.label)}
          </button>
        </li>
      ))}
      {props.edges.map((edge) => (
        <li key={edge.id}>
          <button type="button" onClick={() => props.onSelect('edge', edge.id)}>
            {`${labelOf(edge.from)} \u2192 ${labelOf(edge.to)}: ${t(edge.label)}`}
          </button>
        </li>
      ))}
    </ul>
  );
}
```

Note the template literal is composed from content values plus an arrow glyph; guard 9's allowlist permits the punctuation, and no translatable word is introduced.

- [ ] **Step 4: Implement `src/diagram/Diagram.tsx`**

```tsx
import { useLayoutEffect, useRef, useState } from 'react';
import { useLang, useT } from '../i18n/lang';
import type { Loc } from '../content/types';
import { layoutGraph, type LayoutResult } from './layout';
import { CompanionList, type ListEdge, type ListNode } from './CompanionList';

const BOX = { maxWidth: 180, fontSize: 13, padding: 10, lineHeight: 17 };
const COLUMN_GAP = 220;
const DIM_OPACITY = 0.22;

export function Diagram(props: {
  nodes: (ListNode & { column: number })[];
  edges: ListEdge[];
  dimmed: Set<string>;
  onSelect: (kind: 'node' | 'edge', id: string) => void;
}) {
  const { lang } = useLang();
  const t = useT();
  const svgRef = useRef<SVGSVGElement>(null);
  const [layout, setLayout] = useState<LayoutResult>(() =>
    layoutGraph({
      nodes: props.nodes.map((n) => ({ id: n.id, label: n.label[lang], column: n.column })),
      edges: props.edges.map((e) => ({ id: e.id, from: e.from, to: e.to, label: e.label[lang] })),
      box: BOX,
      columnGap: COLUMN_GAP,
    }),
  );

  // Re-measure with the browser's real metrics. The estimator is a fallback
  // for jsdom, where getComputedTextLength() returns 0 — so the guard proves
  // internal consistency, and only a real browser proves text visually fits.
  useLayoutEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const texts = svg.querySelectorAll<SVGTextContentElement>('text tspan');
    let overflow = false;
    texts.forEach((node) => {
      const measured = node.getComputedTextLength?.() ?? 0;
      if (measured > BOX.maxWidth) overflow = true;
    });
    if (overflow) {
      setLayout(
        layoutGraph({
          nodes: props.nodes.map((n) => ({ id: n.id, label: n.label[lang], column: n.column })),
          edges: props.edges.map((e) => ({ id: e.id, from: e.from, to: e.to, label: e.label[lang] })),
          box: { ...BOX, maxWidth: BOX.maxWidth * 0.85 },
          columnGap: COLUMN_GAP,
        }),
      );
    }
  }, [lang, props.nodes, props.edges]);

  return (
    <div className="diagram">
      <div className="diagram__scroll">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${layout.width + 40} ${layout.height + 40}`}
          className="diagram__svg"
          role="presentation"
        >
          {layout.routes.map((route) => (
            <g key={route.id} data-edge-group={route.id}>
              <polyline
                points={route.points.map((p) => `${p.x},${p.y}`).join(' ')}
                className="diagram__edge"
              />
              <text x={route.labelX} y={route.labelY - 4} className="diagram__edge-label">
                {t(props.edges.find((e) => e.id === route.id)!.label)}
              </text>
            </g>
          ))}
          {[...layout.boxes.values()].map((box) => {
            const node = props.nodes.find((n) => n.id === box.id)!;
            return (
              // Dimming is inline opacity on the PARENT group. Two opacities
              // then multiply instead of one overwriting the other, which is
              // what breaks a `.dimmed` class the moment anything writes an
              // inline style onto the same element.
              <g
                key={box.id}
                data-node-group={box.id}
                style={{ opacity: props.dimmed.has(box.id) ? DIM_OPACITY : 1 }}
              >
                <rect x={box.x} y={box.y} width={box.w} height={box.h} rx={8}
                      className={`diagram__box diagram__box--${node.kind}`} />
                <text x={box.x + box.w / 2} y={box.y + BOX.padding + BOX.fontSize}
                      className="diagram__label" textAnchor="middle">
                  {box.lines.map((line, i) => (
                    <tspan key={line} x={box.x + box.w / 2} dy={i === 0 ? 0 : BOX.lineHeight}>
                      {line}
                    </tspan>
                  ))}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <CompanionList nodes={props.nodes} edges={props.edges} onSelect={props.onSelect} />
    </div>
  );
}
```

- [ ] **Step 5: Run the diagram tests.** Expected: PASS (4).

- [ ] **Step 6: Break the dimming and the companion list (two breaks)**

1. Replace the inline `style` with `className={props.dimmed.has(box.id) ? 'dimmed' : ''}`. Expected: FAIL on `fades a dimmed node via inline opacity`. This is the trap reproduced: with a class only, the assertion cannot see the effect, and neither could a user once a library wrote its own inline opacity. Restore.
2. Delete the `props.edges.map(...)` block from `CompanionList`. Expected: FAIL on `offers a real button for every edge`. Restore.

- [ ] **Step 7: Write `tests/guards/diagram-labels.test.ts`**

```ts
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

const detailsDir = path.join(CONTENT_DIR, 'details');
const details = readdirSync(detailsDir)
  .filter((f) => f.endsWith('.json'))
  .map((f) => ({ name: f, json: JSON.parse(readFileSync(path.join(detailsDir, f), 'utf8')) as { flows?: Flow[] } }));

const systems = JSON.parse(readFileSync(path.join(CONTENT_DIR, 'systems.json'), 'utf8'));
const machine = JSON.parse(readFileSync(path.join(CONTENT_DIR, 'machine.json'), 'utf8'));

const allFlows: { where: string; flow: Flow }[] = [
  ...details.flatMap((d) => (d.json.flows ?? []).map((flow) => ({ where: d.name, flow }))),
  { where: 'systems.json', flow: systems as Flow },
  { where: 'machine.json', flow: machine as Flow },
];

describe('every diagram is fully labelled in both languages', () => {
  for (const { where, flow } of allFlows) {
    for (const node of flow.nodes) {
      it(`${where}/${flow.id ?? ''} node ${node.id} is labelled`, () => {
        expect(node.label.en.trim().length).toBeGreaterThan(0);
        expect(node.label.vi.trim().length).toBeGreaterThan(0);
      });
    }
    for (const edge of flow.edges) {
      it(`${where}/${flow.id ?? ''} edge ${edge.id} is labelled`, () => {
        // An unlabelled edge is invisible to the companion list, which is the
        // whole keyboard/screen-reader surface. Gate branches especially: the
        // branching logic lives in the edge labels, nowhere else.
        expect(edge.label.en.trim().length).toBeGreaterThan(0);
        expect(edge.label.vi.trim().length).toBeGreaterThan(0);
      });
    }
    for (const gate of flow.nodes.filter((n) => n.kind === 'gate')) {
      it(`${where}/${flow.id ?? ''} gate ${gate.id} has labelled branches`, () => {
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
```

- [ ] **Step 8: Run it and break it**

Create `content/machine.json` and `content/systems.json` if absent (Tasks 11 and 14 fill them; a two-node stub is enough now). Blank an edge's `vi` label. Expected: FAIL on `edge ... is labelled`. Restore.

- [ ] **Step 9: Commit**

```bash
git add docs-site
git commit -m "feat(site): SVG diagram with parent-group dimming and an always-visible companion list"
```

---

### Task 11: Layer 1 — system map, contract panels, ownership table

**Files:**
- Create: `docs-site/content/systems.json`, `docs-site/content/ownership.json`
- Create: `docs-site/src/views/MapView.tsx`, `docs-site/src/views/ContractPanel.tsx`, `docs-site/src/views/OwnershipTable.tsx`
- Create: `docs-site/tests/ui/map.test.tsx`

**Interfaces:**
- Consumes: `Diagram` (Task 10), `useNavigate`/`useRoute` (Task 8), `systemNodes`/`systemEdges`/`stores` (Task 7).
- Produces: route `#/map` and `#/map/edge/<edgeId>`.

- [ ] **Step 1: Read the real contracts before writing a word about them**

```bash
sed -n '62,102p' declaw/brain/ollama_client.py
sed -n '9,30p' declaw_plugin_sdk/protocol.py
sed -n '31,60p' declaw_plugin_sdk/protocol.py
cat declaw/plugin_host/errors.py
grep -n "class .*SQLModel, table=True" -A 3 declaw/db/models.py
grep -rn "declaw_semantic\|declaw_documents" declaw/memory declaw/documents
grep -rn "plugin_state.json\|plugin_grants.json" declaw/plugin_host
```

Document only what these show. For the chat endpoint, verify what `langchain-ollama` actually calls before claiming a path:

```bash
grep -rn "api/chat" .venv/Lib/site-packages/langchain_ollama/ | head -5
```

If the path cannot be read, describe the edge as "via the langchain-ollama client" and omit the path rather than guessing.

- [ ] **Step 2: Write `content/systems.json`**

Nodes (`column` places them left to right): `user-cli` (0), `declaw-core` (1), `ollama` (2), `sqlite` (2), `chroma` (2), `keyring` (2), `plugin-proc` (2), `workspace-fs` (2), `policy-json` (2), `gateway-planned` (2, kind `planned`), `docker-planned` (2, kind `planned`).

Every edge carries a `contract` and a `source` quote. Worked example:

```json
{
  "id": "core-ollama-embed",
  "from": "declaw-core",
  "to": "ollama",
  "label": { "en": "embed chunks", "vi": "nhúng vector cho chunk" },
  "principles": ["P7"],
  "contract": {
    "transport": { "en": "HTTP, loopback only", "vi": "HTTP, chỉ loopback" },
    "method": "POST",
    "path": "/api/embed",
    "auth": { "en": "None — the daemon is local.", "vi": "Không có — daemon chạy cục bộ." },
    "request": { "en": "{ model: str, input: list[str] }", "vi": "{ model: str, input: list[str] }" },
    "response": { "en": "{ embeddings: list[list[float]] }, one vector per input, same order", "vi": "{ embeddings: list[list[float]] }, mỗi input một vector, đúng thứ tự" },
    "errors": [
      { "code": "404", "meaning": { "en": "Model not pulled. Ollama answers 404 for an unknown model.", "vi": "Model chưa được pull. Ollama trả 404 cho model lạ." } },
      { "code": "httpx.HTTPError", "meaning": { "en": "Daemon unreachable; health() reports it in-band instead of raising.", "vi": "Không kết nối được daemon; health() báo trong kết quả thay vì raise." } }
    ],
    "source": {
      "file": "declaw/brain/ollama_client.py",
      "start": 77,
      "end": 86,
      "anchor": "/api/embed",
      "note": { "en": "The only place this call is made.", "vi": "Nơi duy nhất gọi API này." }
    }
  }
}
```

Do the same for: `/api/version` and `/api/tags` (health), the plugin stdio edge (NDJSON, `describe`/`invoke`/`shutdown`, `MAX_FRAME_BYTES` = 32 MiB, the six `ErrorCode` values), SQLite, Chroma, keyring, the workspace filesystem, and the two `planned` edges which must state plainly that nothing is implemented.

- [ ] **Step 3: Write `content/ownership.json`**

One `store` entry per: `tasks`, `audit_events`, `episodes`, `indexed_documents` (SQLite tables); `declaw_semantic`, `declaw_documents` (Chroma); `plugin_state.json`, `plugin_grants.json`; the OS keyring namespace; the in-memory quarantine. Each names `owner` (a component id), `writers`, `readers`, a `lifetime` (persisted / wiped by `declaw memory wipe` / ephemeral) and an `enforcement` quote. This table is the thing new developers get wrong, so it must be sourced, not remembered.

- [ ] **Step 4: Write the failing test `tests/ui/map.test.tsx`**

```tsx
/** @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { App } from '../../src/App';
import { systemEdges } from '../../src/content/load';

beforeEach(() => {
  window.location.hash = '#/map';
});

describe('Layer 1', () => {
  it('opens the real contract when an edge is activated', async () => {
    const user = userEvent.setup();
    render(<App />);
    const edge = systemEdges.find((e) => e.contract.path === '/api/embed')!;
    await user.click(screen.getByRole('button', { name: new RegExp(edge.label.en) }));
    expect(window.location.hash).toContain(`edge/${edge.id}`);
    expect(screen.getByText('/api/embed')).toBeTruthy();
  });

  it('shows every declared error code for that contract', async () => {
    const user = userEvent.setup();
    render(<App />);
    const edge = systemEdges.find((e) => e.contract.path === '/api/embed')!;
    await user.click(screen.getByRole('button', { name: new RegExp(edge.label.en) }));
    for (const err of edge.contract.errors) {
      expect(screen.getByText(err.code)).toBeTruthy();
    }
  });
});
```

- [ ] **Step 5: Implement `MapView`, `ContractPanel`, `OwnershipTable`**

`ContractPanel` renders `data-panel-heading tabIndex={-1}` on its root so Task 8's focus effect finds it, reads `route.segments[2]` for the edge id, and renders transport/method/path/auth/request/response/errors plus the source quote with its `file:line`. `OwnershipTable` renders a `<table>` whose headers come from `ui.json`. `MapView` renders `<Diagram>` with `dimmed` empty and an `onSelect` that navigates to `#/map/edge/<id>`.

- [ ] **Step 6: Run, then break it**

Expected: PASS. Now delete the `errors.map(...)` render in `ContractPanel`. Expected: FAIL on `shows every declared error code`. Restore.

- [ ] **Step 7: Commit**

```bash
git add docs-site
git commit -m "feat(site): layer 1 system map with real contracts and the ownership table"
```

---

### Task 12: Layer 2 — component grid with phase and ticket filters

**Files:**
- Create: `docs-site/src/views/ComponentsView.tsx`
- Create: `docs-site/tests/ui/components-view.test.tsx`

**Interfaces:**
- Consumes: `components`, `tickets` (Task 7); route `#/components?phase=&ticket=`.
- Produces: each card carries `data-component-card="<id>"` and `data-dimmed="true|false"`.

- [ ] **Step 1: Write the failing test**

```tsx
/** @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { App } from '../../src/App';
import { components, tickets } from '../../src/content/load';

beforeEach(() => {
  window.location.hash = '#/components';
});

describe('Layer 2 grid', () => {
  it('shows a card for every component', () => {
    render(<App />);
    for (const c of components) {
      expect(document.querySelector(`[data-component-card="${c.id}"]`)).toBeTruthy();
    }
  });

  it('dims components a ticket does not touch, and only those', () => {
    const ticket = tickets.find((t) => t.creates.length > 0)!;
    window.location.hash = `#/components?ticket=${ticket.id}`;
    render(<App />);
    const related = new Set([...ticket.creates, ...ticket.modifies, ...ticket.traverses]);
    for (const c of components) {
      const card = document.querySelector(`[data-component-card="${c.id}"]`)!;
      expect(card.getAttribute('data-dimmed')).toBe(related.has(c.id) ? 'false' : 'true');
    }
  });
});
```

- [ ] **Step 2: Run to see it fail.** Expected: FAIL — no cards render.

- [ ] **Step 3: Implement `ComponentsView`**

Group cards by `group`; each card shows title, summary, module count, ticket chips, and links to `#/component/<id>`. Filter controls (phase, ticket) read and write `route.query` through `navigate`, so the filter is shareable by URL. Dimming uses the union of all three relations:

```tsx
const related = new Set([...ticket.creates, ...ticket.modifies, ...ticket.traverses]);
```

Include a comment stating why all three: `creates` alone leaves tickets owning nothing; `creates + modifies` renders a ticket's request as though it stops mid-pipeline, because a component it calls but never edited stays dark.

- [ ] **Step 4: Run.** Expected: PASS.

- [ ] **Step 5: Break it**

Change the union to `new Set(ticket.creates)`. Expected: FAIL on `dims components a ticket does not touch, and only those` — the traversed components come back dimmed. Restore.

- [ ] **Step 6: Commit**

```bash
git add docs-site
git commit -m "feat(site): layer 2 component grid with phase and ticket filters"
```

---

### Task 13: Layer 3 — component detail, deep links, tier guard

**Files:**
- Create: `docs-site/content/details/*.json` (one per component; Tier A gets `flows`)
- Create: `docs-site/src/views/DetailView.tsx`, `docs-site/scripts/gen-repo-json.mjs`
- Create: `docs-site/tests/ui/detail.test.tsx`, `docs-site/tests/guards/tier-structure.test.ts`

**Interfaces:**
- Consumes: `loadDetail` (Task 7), `Diagram` (Task 10).
- Produces: `githubUrl(file, start, end): string` in `src/content/links.ts`; route `#/component/<id>` and `#/component/<id>/fn/<fnId>`.

- [ ] **Step 1: Write `scripts/gen-repo-json.mjs`**

```js
// Deep links must be line-accurate, so they pin a commit SHA rather than a
// moving branch. CI passes the deployed SHA; locally we read HEAD.
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const sha =
  process.env.GITHUB_SHA ??
  execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();

writeFileSync(
  path.resolve(here, '../content/repo.json'),
  `${JSON.stringify({ owner: 'NgoHung0704', repo: 'DeClaw', sha }, null, 2)}\n`,
  'utf8',
);
console.log(`repo.json -> ${sha}`);
```

- [ ] **Step 2: Write `src/content/links.ts`**

```ts
import repo from '../../content/repo.json';

export function githubUrl(file: string, start?: number, end?: number): string {
  const base = `https://github.com/${repo.owner}/${repo.repo}/blob/${repo.sha}/${file}`;
  if (!start) return base;
  return `${base}#L${start}${end && end !== start ? `-L${end}` : ''}`;
}
```

- [ ] **Step 3: Write `tests/guards/tier-structure.test.ts`**

```ts
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { CONTENT_DIR } from './_repo';

const components = JSON.parse(
  readFileSync(path.join(CONTENT_DIR, 'components.json'), 'utf8'),
).components as { id: string; tier: 'A' | 'B'; detail?: string }[];

describe('tier structure', () => {
  for (const c of components) {
    it(`${c.id} has a detail file`, () => {
      expect(c.detail, `${c.id} declares no detail file`).toBeTruthy();
      expect(existsSync(path.join(CONTENT_DIR, 'details', `${c.detail}.json`))).toBe(true);
    });

    const detail = c.detail
      ? JSON.parse(readFileSync(path.join(CONTENT_DIR, 'details', `${c.detail}.json`), 'utf8'))
      : { flows: [], functions: [], why: [] };

    if (c.tier === 'A') {
      it(`${c.id} (tier A) declares a flow and embeds real code`, () => {
        // Structural, not numeric: no magic node count, so adding content is
        // never a failure — only removing the shape is.
        expect(detail.flows?.length ?? 0).toBeGreaterThan(0);
        expect(detail.snippets?.length ?? 0).toBeGreaterThan(0);
      });
    }

    it(`${c.id} documents at least one function and one reason`, () => {
      expect(detail.functions.length).toBeGreaterThan(0);
      expect(detail.why.length).toBeGreaterThan(0);
    });
  }
});
```

- [ ] **Step 4: Author the detail files**

For each component, capture real signatures rather than paraphrasing:

```bash
grep -n "^def \|^async def \|^class \|^    def \|^    async def " declaw/tools/registry.py
```

Every `why` entry cites a `source` quote whose `anchor` is text already in the code — a docstring line explaining the decision. Tier A components (`brain-loop`, `tool-registry`, `sanitizer`, `audit`, `plugin-host`, `plugin-sdk`, `documents`) each declare at least one `flow`. For `tool-registry` the flow **must be a gate**: a `gate` node splitting to a sanitizer branch and a confirmation branch, with audit wrapping both — matching `langchain_tools()`, which never composes the two.

- [ ] **Step 5: Write the failing test `tests/ui/detail.test.tsx`**

```tsx
/** @vitest-environment jsdom */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from '../../src/App';
import { githubUrl } from '../../src/content/links';

describe('Layer 3', () => {
  it('links a function to its exact lines on GitHub', async () => {
    window.location.hash = '#/component/tool-registry';
    render(<App />);
    await waitFor(() => expect(screen.getByRole('link', { name: /registry\.py/ })).toBeTruthy());
    const link = screen.getByRole('link', { name: /registry\.py/ }) as HTMLAnchorElement;
    expect(link.href).toContain('/blob/');
    expect(link.href).toMatch(/#L\d+/);
  });

  it('builds a deep link that pins a commit, not a branch', () => {
    expect(githubUrl('declaw/tools/registry.py', 105, 148)).toMatch(
      /\/blob\/[0-9a-f]{7,40}\/declaw\/tools\/registry\.py#L105-L148$/,
    );
  });
});
```

- [ ] **Step 6: Implement `DetailView`**

Renders: the component's title/summary, its flow(s) through `<Diagram>`, the function table (name, signature, `file:line` as a GitHub link), embedded snippets in `<pre><code>`, quotes with their notes, and why-cards each showing its source citation and any linked principles. A function row navigates to `#/component/<id>/fn/<fnId>`, opening a panel with `data-panel-heading`.

- [ ] **Step 7: Run, then break it**

Expected: PASS. Now change `githubUrl` to use `/blob/main/`. Expected: FAIL on `pins a commit, not a branch`. Restore.

Then delete `flows` from `details/tool-registry.json`. Expected: FAIL on `tier A declares a flow`. Restore.

- [ ] **Step 8: Commit**

```bash
git add docs-site
git commit -m "feat(site): layer 3 detail view with verbatim code and commit-pinned deep links"
```

---

### Task 14: The machine view

**Files:**
- Create: `docs-site/content/machine.json`, `docs-site/src/views/MachineView.tsx`
- Create: `docs-site/tests/ui/machine.test.tsx`

**Interfaces:**
- Consumes: `Diagram` (Task 10), `tickets` (Task 7). Route `#/machine?ticket=DCL-110`.
- Produces: `machine.json` shape `{ id, title, nodes, edges }` where each node carries `component?: string` linking a part to a component id.

- [ ] **Step 1: Write `content/machine.json`**

Ports: `port-prompt` (a user turn), `port-document` (a file entering the workspace). Parts, in the order the code actually applies them: `part-brain` (the think→tool→observe loop), `part-audit` (outermost wrapper), `gate-classification` (**a gate**), `part-confirmation` (non-READ branch), `part-sanitizer` (READ + external-content branch), `part-tool` (the tool itself), `part-plugin-host` (for plugin-backed tools). Exits: `exit-answer`, `exit-fs-write`, `exit-audit-db`, `exit-quarantine`, `exit-ollama` (the only network egress).

The `gate-classification` node must have two labelled outgoing edges — "non-READ → confirmation" and "READ + external content → sanitizer" — because `langchain_tools()` routes to exactly one of them and never composes both. Guard 7 from Task 10 enforces the labels.

- [ ] **Step 2: Write the failing test**

```tsx
/** @vitest-environment jsdom */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from '../../src/App';
import machine from '../../content/machine.json';
import { tickets } from '../../src/content/load';

const opacityOf = (id: string) =>
  Number((document.querySelector(`[data-node-group="${id}"]`) as SVGGElement).style.opacity);

describe('machine view ticket filter', () => {
  it('lights every part the ticket touches, including ones it only traverses', () => {
    const ticket = tickets.find((t) => t.traverses.length > 0)!;
    window.location.hash = `#/machine?ticket=${ticket.id}`;
    render(<App />);
    const related = new Set([...ticket.creates, ...ticket.modifies, ...ticket.traverses]);
    for (const node of machine.nodes) {
      if (!node.component) continue;
      const expected = related.has(node.component) ? 1 : 0;
      expect(opacityOf(node.id) === 1 ? 1 : 0).toBe(expected);
    }
  });

  it('draws the classification gate with more than one labelled exit', () => {
    // A chain here would misrepresent the code: confirmation and sanitizer are
    // mutually exclusive branches, not sequential stages.
    const exits = machine.edges.filter((e) => e.from === 'gate-classification');
    expect(exits.length).toBeGreaterThan(1);
    for (const exit of exits) {
      expect(exit.label.en.trim()).not.toBe('');
      expect(exit.label.vi.trim()).not.toBe('');
    }
  });
});
```

- [ ] **Step 3: Implement `MachineView`** — reads `?ticket`, computes the three-relation union, passes the complement as `dimmed` to `<Diagram>`.

- [ ] **Step 4: Run, then break it**

Expected: PASS. Now change the union to `creates + modifies` only. Expected: FAIL on `including ones it only traverses`. Restore.

- [ ] **Step 5: Commit**

```bash
git add docs-site
git commit -m "feat(site): machine view with three-relation ticket filter and a real classification gate"
```

---

### Task 15: The debt view

**Files:**
- Create: `docs-site/content/debt.json`, `docs-site/src/views/DebtView.tsx`
- Create: `docs-site/tests/ui/debt.test.tsx`

- [ ] **Step 1: Write `content/debt.json`, every item anchored**

At minimum, one item each for: the empty `gateway/` and `sandbox/` packages; Phase 3 deferred; the sanitizer's 38-point held-out detection gap; its measured French weakness; the unreachable p95 <500 ms target; unencrypted embedding vectors; the in-process-only egress monitor; `ensure_schema` without alembic stamping; episodic memory never populated; `with_memory` not wired into `build_brain`; the builtin-plugin auto-grant; `plugin.sig` signing only the manifest; retrieval quality unmeasured.

Anchor each to a real line. Verify before writing:

```bash
grep -n "embedding vectors are NOT encrypted" CLAUDE.md
grep -n "in-process observation only" CLAUDE.md
wc -c declaw/gateway/__init__.py declaw/sandbox/__init__.py
```

Example item:

```json
{
  "id": "debt-embeddings-unencrypted",
  "severity": "temporary",
  "title": { "en": "Embedding vectors are stored unencrypted", "vi": "Vector nhúng đang lưu không mã hoá" },
  "body": {
    "en": "Chunk text is Fernet-encrypted at rest, but the vectors are not: Chroma must compare them. Embedding inversion can approximate the original text, and Phase 8a widened the exposure from agent memories to client documents.",
    "vi": "Văn bản chunk được mã hoá Fernet khi lưu, nhưng vector thì không: Chroma phải so sánh chúng. Kỹ thuật đảo ngược embedding có thể tái tạo gần đúng văn bản gốc, và Phase 8a đã mở rộng phạm vi từ bộ nhớ agent sang tài liệu của khách hàng."
  },
  "components": ["memory", "documents"],
  "source": {
    "file": "CLAUDE.md",
    "start": 0,
    "end": 0,
    "anchor": "embedding vectors are NOT encrypted",
    "note": { "en": "Recorded as a Phase 12 consideration.", "vi": "Ghi nhận là hạng mục cho Phase 12." }
  }
}
```

Replace `start`/`end` with the real line number from `grep -n`.

- [ ] **Step 2: Write the test**

```tsx
/** @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from '../../src/App';
import { debt } from '../../src/content/load';

describe('debt view', () => {
  it('renders every debt item with its source citation', () => {
    window.location.hash = '#/debt';
    render(<App />);
    for (const item of debt) {
      expect(screen.getByText(item.title.en)).toBeTruthy();
      expect(screen.getByText(new RegExp(item.source.file.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))).toBeTruthy();
    }
  });

  it('links every debt item to at least one component that carries it', () => {
    for (const item of debt) {
      expect(item.components.length).toBeGreaterThan(0);
    }
  });
});
```

- [ ] **Step 3: Implement `DebtView`**, grouped by `severity`, each item showing body, affected components (links to Layer 2) and its `file:line` source link.

- [ ] **Step 4: Run, then break it** — delete the source rendering. Expected: FAIL on `with its source citation`. Restore.

- [ ] **Step 5: Prove the anchor keeps debt honest**

Edit `CLAUDE.md`, changing `embedding vectors are NOT encrypted` to `embedding vectors are encrypted`. Run `npx vitest run tests/guards/citations.test.ts`.
Expected: FAIL — the page now claims a debt its own source no longer supports. **Revert the CLAUDE.md edit.** This is the drift-checked-honesty property working.

- [ ] **Step 6: Commit**

```bash
git add docs-site
git commit -m "feat(site): debt view whose every claim is anchored to its source"
```

---

### Task 16: Styling, responsiveness, reduced motion

**Files:**
- Create: `docs-site/src/styles/tokens.css`, `layout.css`, `diagram.css`
- Modify: `docs-site/src/main.tsx` (import the stylesheets)

- [ ] **Step 1: Write `tokens.css`** — colour, spacing and type scales as custom properties, with a `prefers-color-scheme: dark` block. Body text must reach at least 4.5:1 against its background; diagram edge labels at least 4.5:1 too, since they are small.

- [ ] **Step 2: Write `layout.css`** — a sidebar-plus-content grid that collapses to a single column under 900px. Panels become full-width sheets under 700px. `.diagram__scroll { overflow-x: auto; }` so a wide diagram scrolls inside its own box instead of forcing the page sideways.

- [ ] **Step 3: Gate every transition behind reduced motion**

```css
@media (prefers-reduced-motion: no-preference) {
  .panel { transition: transform 160ms ease, opacity 160ms ease; }
  .diagram__box { transition: opacity 120ms linear; }
}
```

Never write a bare `transition` outside this block: the default must be no motion, not motion-with-an-opt-out.

- [ ] **Step 4: Verify visually at two widths, in a real browser**

```powershell
npm run dev
```

Open `http://localhost:5173/DeClaw/#/map`, then check: 1440px, and 360px via devtools. Look for text escaping its box, overlapping edge labels, and low-contrast labels — the guards cannot see any of these. Then set `prefers-reduced-motion: reduce` in devtools rendering settings and confirm nothing animates.

If a browser cannot be launched in this environment, say so explicitly in the final report instead of implying the inspection happened.

- [ ] **Step 5: Commit**

```bash
git add docs-site
git commit -m "feat(site): responsive layout, contrast tokens, reduced-motion default"
```

---

### Task 17: CI and GitHub Pages

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: CI

on:
  push:
    branches: [main, feat/phase-7-plugin-host]
  pull_request:

permissions:
  contents: read

jobs:
  python:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run mypy declaw declaw_plugin_sdk
      - run: uv run pytest

  docs-site:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: docs-site
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0    # guards read git history and git ls-files
      - uses: actions/setup-node@v4
        with:
          node-version-file: docs-site/.nvmrc
          cache: npm
          cache-dependency-path: docs-site/package-lock.json
      - run: npm ci
      - run: npm run guards
      - run: npm run build
        env:
          GITHUB_SHA: ${{ github.sha }}
      - uses: actions/upload-pages-artifact@v3
        with:
          path: docs-site/dist

  deploy:
    # Depends on docs-site only. The site's truthfulness is proven by the
    # guards; blocking publication on an unrelated Python failure is coupling
    # nobody asked for. A red python job still marks the commit.
    needs: docs-site
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Generate the lockfile from PowerShell and commit it**

```powershell
cd docs-site
npm install --package-lock-only
```

`npm ci` fails without `package-lock.json`, so it must be committed.

- [ ] **Step 3: Enable Pages in Actions mode**

```bash
gh api -X POST repos/NgoHung0704/DeClaw/pages -f build_type=workflow
```

If it returns 409 (already exists):

```bash
gh api -X PUT repos/NgoHung0704/DeClaw/pages -f build_type=workflow
```

- [ ] **Step 4: Run the full gate locally before pushing, exit codes unmasked**

```powershell
cd docs-site
npx vitest run
npm run build
cd ..
uv run ruff check .
uv run mypy declaw declaw_plugin_sdk
uv run pytest
```

Run each bare. Do not chain with `| tail` — the pipe returns `tail`'s status and a later `&&` would run after a failure.

- [ ] **Step 5: Commit and push**

```bash
git add .github docs-site/package-lock.json
git commit -m "ci: python gates, docs-site drift guards, and GitHub Pages deploy"
git push origin feat/phase-7-plugin-host
```

- [ ] **Step 6: Watch the run and report the real result**

```bash
gh run watch
```

If the deploy job is refused because the `github-pages` environment restricts deployments to protected branches, relax that policy:

```bash
gh api -X PUT repos/NgoHung0704/DeClaw/environments/github-pages -f 'deployment_branch_policy=null'
```

If GitHub still refuses, **report it** rather than silently switching the deployment to `main`.

- [ ] **Step 7: Confirm the published page**

```bash
gh api repos/NgoHung0704/DeClaw/pages --jq .html_url
```

Fetch that URL and confirm it serves the built page (expect `/DeClaw/`).

---

### Task 18: Acceptance sweep

**Files:** none — this task verifies.

- [ ] **Step 1: Confirm every guard has been seen red**

Re-read Tasks 1–15 and confirm each break-and-restore step was actually performed. Any guard never seen failing is unverified; break it now.

- [ ] **Step 2: Run the whole suite twice and compare counts**

```powershell
npx vitest run
npx vitest run
```

Identical counts both times. A count that moves between runs means a guard depends on filesystem or git ordering.

- [ ] **Step 3: Update `CLAUDE.md`**

Per the repo's working rules, add a section recording: the site's location, the ten guards and what each protects, the fact that CI now exists (it did not before), the Pages URL, and the accepted cost that shifting a documented line range turns CI red until `npm run sync:snippets` is run.

- [ ] **Step 4: Visual pass, honestly reported**

Desktop and 360px, both languages, reduced motion on. Switch to Vietnamese and read every view looking for leftover English (and the reverse). Confirm no text escapes a box and no two edge labels overlap.

- [ ] **Step 5: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the architecture site, its guards, and the new CI"
git push origin feat/phase-7-plugin-host
```

---

## Self-Review

**Spec coverage:** §4 stack → Task 1. §5 content model → Tasks 1, 6, 11, 13, 14, 15. §5.1 snippet/quote XOR → Task 2. §5.2 relations → Tasks 4, 6, 12, 14. §6 Layer 1 → Task 11; Layer 2 → Task 12; Layer 3 → Task 13; machine → Task 14. §7 diagram mechanics → Tasks 9, 10. §8 routing/keyboard/a11y → Tasks 8, 10, 16. §9 guards 1–10 → Tasks 2 (1,2), 3 (3), 1 (4), 4 (5,6), 10 (7), 5 (8,9), 13 (10). §10 CI → Task 17. §11 honest content → Task 15. §12 acceptance → Task 18, plus a break-and-restore step inside every task that adds a guard.

**Placeholder scan:** no TBD/TODO; every code step carries real code; no step says "similar to Task N".

**Type consistency:** `Loc`, `Quote`, `Snippet`, `Flow`, `Component`, `Ticket` are defined once in Task 7 and used unchanged afterwards. `layoutGraph` returns `{ boxes, routes, width, height }` in Task 9 and is consumed with those names in Task 10. `dimmed: Set<string>` is the same type in Tasks 10, 12 and 14. Ticket relations are **component ids** everywhere (Tasks 4, 6, 12, 14), never file paths.
