import { describe, expect, it } from 'vitest';
import { allContentFiles, sliceLines } from './_repo';

type Citation = {
  file: string;
  start: number;
  end: number;
  code?: string;
  anchor?: string;
  where: string;
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
