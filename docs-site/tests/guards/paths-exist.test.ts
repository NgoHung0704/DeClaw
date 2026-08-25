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
