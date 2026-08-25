// Limit, stated so nobody over-trusts this: it is a lint over JSX shapes.
// A string smuggled through a helper function (e.g. label("Close")) evades it.
// It is a tripwire for the common mistake, not a proof of absence.
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

// The `>` of an arrow function is not the end of a JSX tag. Neutralising it
// first removes the whole false-positive class this guard hit on real code;
// the alternative was loosening the match until it caught nothing.
const stripArrows = (source: string) => source.replace(/=>/g, '==');

// Text between a tag close and a tag open: the `>` must end something
// tag-shaped, and the `<` must begin an element or a closing tag.
const JSX_TEXT = /(?<=[A-Za-z0-9"'}/])>([^<>{}]+)<(?=[A-Za-z/])/g;

// Generic type arguments (`useState<Route>(...)`) also put a `>` in front of
// code. Real UI copy never contains these characters, so anything that does is
// code caught between two elements, not a string somebody forgot to translate.
const LOOKS_LIKE_CODE = /[;()=]/;
const LITERAL_ATTR = /\s(?:aria-label|title|placeholder|alt)\s*=\s*"([^"]*)"/g;

describe('no user-visible string is written in code', () => {
  const files = tsxFiles(SRC);

  it('finds tsx files to scan', () => {
    expect(files.length).toBeGreaterThan(0);
  });

  for (const file of files) {
    const rel = path.relative(SRC, file).replace(/\\/g, '/');
    const source = readFileSync(file, 'utf8');

    it(`${rel} has no literal JSX text`, () => {
      const offenders = [...stripArrows(source).matchAll(JSX_TEXT)]
        .map((m) => m[1])
        .filter((t) => !MEANINGLESS.test(t) && !LOOKS_LIKE_CODE.test(t));
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
