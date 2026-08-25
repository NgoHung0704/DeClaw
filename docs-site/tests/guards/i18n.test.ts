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
