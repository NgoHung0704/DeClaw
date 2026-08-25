/** @vitest-environment jsdom */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Diagram } from '../../src/diagram/Diagram';
import { LangProvider } from '../../src/i18n/lang';

const nodes = [
  { id: 'a', label: { en: 'Intake', vi: 'Cổng vào' }, kind: 'port', x: 0, y: 0, w: 180, h: 60 },
  { id: 'b', label: { en: 'Sanitizer', vi: 'Bộ lọc' }, kind: 'step', x: 320, y: 0, w: 180, h: 60 },
];
const edges = [{ id: 'e1', from: 'a', to: 'b', label: { en: 'file content', vi: 'nội dung tệp' } }];

const renderDiagram = (dimmed: Set<string>) =>
  render(
    <LangProvider lang="en" setLang={() => {}}>
      <Diagram nodes={nodes} edges={edges} dimmed={dimmed} onSelect={() => {}} label="test" />
    </LangProvider>,
  );

describe('dimming', () => {
  it('fades a dimmed node via inline opacity on its group', () => {
    // The class-only approach fails silently the moment anything writes inline
    // opacity on the same element. Asserting the computed inline value is the
    // only check that stays honest.
    renderDiagram(new Set(['a']));
    const group = document.querySelector('[data-node-group="a"]') as SVGGElement;
    // An empty style.opacity would coerce to 0 and pass a naive `< 1` check,
    // so require an explicit inline value before comparing it.
    expect(group.style.opacity, 'no inline opacity was set').not.toBe('');
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
    // Scoped to the companion list on purpose: the SVG node is now a focusable
    // button too, so an unscoped query matches both and proves neither.
    const list = within(document.querySelector('.companion') as HTMLElement);
    for (const node of nodes) {
      expect(list.getByRole('button', { name: node.label.en })).toBeTruthy();
    }
  });

  it('offers a real button for every edge, carrying its label', () => {
    renderDiagram(new Set());
    expect(screen.getByRole('button', { name: /file content/ })).toBeTruthy();
  });

  it('names both endpoints on the edge button, so direction is readable', () => {
    renderDiagram(new Set());
    expect(screen.getByRole('button', { name: /Intake → Sanitizer: file content/ })).toBeTruthy();
  });
});
