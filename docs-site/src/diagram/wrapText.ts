/**
 * Width estimate for a glyph run, in px.
 *
 * Deliberately conservative: over-estimating pushes a break earlier, which is
 * survivable, while under-estimating overflows the box. Vietnamese diacritics
 * do not widen a glyph, but Vietnamese phrasing is longer than English, so
 * both languages must be laid out and checked.
 *
 * Honest limit: the layout and the guard share this estimator, so a test using
 * it proves internal consistency, not that text visually fits. Real metrics
 * come from getComputedTextLength() in a browser; jsdom returns 0.
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
