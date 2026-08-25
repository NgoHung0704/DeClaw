import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { CONTENT_DIR } from './_repo';

type Detail = {
  flows?: { id: string; nodes: unknown[]; edges: unknown[] }[];
  snippets?: unknown[];
  functions: unknown[];
  why: unknown[];
};

const components = (
  JSON.parse(readFileSync(path.join(CONTENT_DIR, 'components.json'), 'utf8')) as {
    components: { id: string; tier: 'A' | 'B'; detail?: string }[];
  }
).components;

describe('tier structure', () => {
  for (const c of components) {
    it(`${c.id} has a detail file`, () => {
      expect(c.detail, `${c.id} declares no detail file`).toBeTruthy();
      expect(existsSync(path.join(CONTENT_DIR, 'details', `${c.detail}.json`))).toBe(true);
    });

    const detailPath = path.join(CONTENT_DIR, 'details', `${c.detail}.json`);
    const detail: Detail = existsSync(detailPath)
      ? (JSON.parse(readFileSync(detailPath, 'utf8')) as Detail)
      : { functions: [], why: [] };

    if (c.tier === 'A') {
      it(`${c.id} (tier A) declares a flow and embeds real code`, () => {
        // Structural, not numeric: no magic node count, so adding content is
        // never a failure — only removing the shape is.
        expect(detail.flows?.length ?? 0, `${c.id} is tier A with no flow`).toBeGreaterThan(0);
        expect(detail.snippets?.length ?? 0, `${c.id} is tier A with no code`).toBeGreaterThan(0);
      });
    }

    it(`${c.id} documents at least one function and one reason`, () => {
      expect(detail.functions.length, `${c.id} documents no function`).toBeGreaterThan(0);
      expect(detail.why.length, `${c.id} gives no reason`).toBeGreaterThan(0);
    });
  }
});
