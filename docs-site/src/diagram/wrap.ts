/**
 * SVG <text> does not wrap. An overflowing line runs outside its box and over
 * whatever sits beside it, so labels are broken into lines here and emitted as
 * <tspan>s.
 *
 * Width is estimated in characters rather than pixels: box widths are authored,
 * the font is known, and a character budget survives a font-size change far
 * better than a pixel table does.
 */
const AVG_CHAR_PX = 6.6;

export function charBudget(boxWidth: number, padding = 22): number {
  return Math.max(6, Math.floor((boxWidth - padding * 2) / AVG_CHAR_PX));
}

export function wrapLabel(text: string, budget: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [''];
  const lines: string[] = [];
  let current = '';
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= budget || current === '') current = candidate;
    else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines;
}
