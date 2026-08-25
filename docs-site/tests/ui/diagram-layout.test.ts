import { describe, expect, it } from 'vitest';
import { estimateTextWidth, wrapText } from '../../src/diagram/wrapText';
import { layoutGraph } from '../../src/diagram/layout';
import { loadDetail } from '../../src/content/load';
import type { Lang } from '../../src/content/types';

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

describe('layout of a real flow in both languages', () => {
  const detail = loadDetail('tool-registry')!;
  const flow = detail.flows[0];

  for (const lang of ['en', 'vi'] as Lang[]) {
    it(`${lang}: every box is tall enough for its wrapped lines and none overflow`, () => {
      const result = layoutGraph({
        nodes: flow.nodes.map((n, i) => ({ id: n.id, label: n.label[lang], column: i })),
        edges: flow.edges.map((e) => ({
          id: e.id,
          from: e.from,
          to: e.to,
          label: e.label[lang],
        })),
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
