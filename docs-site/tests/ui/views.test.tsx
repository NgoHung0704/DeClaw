/** @vitest-environment jsdom */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { App } from '../../src/App';
import { components, tickets } from '../../src/content/load';
import type { Ticket } from '../../src/content/types';

// Computed from the ticket's own fields, deliberately NOT via the app's
// relatedComponents helper: sharing that helper would make this test agree
// with the implementation by construction and never catch a narrowed union.
const expectedRelated = (t: Ticket) =>
  new Set([...t.creates, ...t.modifies, ...t.traverses]);
import { githubUrl } from '../../src/content/links';
import systemsJson from '../../content/systems.json';
import machineJson from '../../content/machine.json';
import debtJson from '../../content/debt.json';
import type { DebtItem, SystemEdge } from '../../src/content/types';

const systemEdges = (systemsJson as unknown as { edges: SystemEdge[] }).edges;
type MachineContent = {
  parts: { id: string; component: string; label: { en: string; vi: string }; subparts: { path: string }[] }[];
};
const machine = machineJson as unknown as MachineContent;
const debt = (debtJson as unknown as { items: DebtItem[] }).items;

beforeEach(() => {
  window.location.hash = '#/map';
});

describe('Layer 1 — system map', () => {
  it('opens the real contract when an edge is activated', async () => {
    const user = userEvent.setup();
    render(<App />);
    const edge = systemEdges.find((e) => e.contract.path === '/api/embed')!;
    // Scoped to the drawing: the same edge is also a button in the companion
    // list, so an unscoped query matches both and proves neither.
    const svg = within(document.querySelector('.plot__svg') as unknown as HTMLElement);
    await user.click(svg.getByRole('button', { name: edge.label.en }));
    expect(window.location.hash).toContain(`edge/${edge.id}`);
    expect(screen.getByText('/api/embed')).toBeTruthy();
  });

  it('shows every declared failure mode for that contract', async () => {
    const user = userEvent.setup();
    render(<App />);
    const edge = systemEdges.find((e) => e.contract.path === '/api/embed')!;
    const svg = within(document.querySelector('.plot__svg') as unknown as HTMLElement);
    await user.click(svg.getByRole('button', { name: edge.label.en }));
    for (const err of edge.contract.errors) {
      expect(screen.getByText(err.code)).toBeTruthy();
    }
  });
});

describe('Layer 2 — component grid', () => {
  it('shows a card for every component', () => {
    window.location.hash = '#/components';
    render(<App />);
    for (const c of components) {
      expect(document.querySelector(`[data-component-card="${c.id}"]`)).toBeTruthy();
    }
  });

  it('dims components a ticket does not touch, and only those', () => {
    const ticket = tickets.find((t) => t.traverses.length > 0)!;
    window.location.hash = `#/components?ticket=${ticket.id}`;
    render(<App />);
    const related = expectedRelated(ticket);
    for (const c of components) {
      const card = document.querySelector(`[data-component-card="${c.id}"]`)!;
      expect(card.getAttribute('data-dimmed'), `${c.id} for ${ticket.id}`).toBe(
        related.has(c.id) ? 'false' : 'true',
      );
    }
  });
});

describe('Layer 3 — component detail', () => {
  it('links a function to its exact lines on GitHub', async () => {
    window.location.hash = '#/component/tool-registry';
    render(<App />);
    const link = screen.getAllByRole('link', { name: /registry\.py:\d+/ })[0] as HTMLAnchorElement;
    expect(link.href).toContain('/blob/');
    expect(link.href).toMatch(/#L\d+/);
  });

  it('builds a deep link that pins a commit, not a branch', () => {
    expect(githubUrl('declaw/tools/registry.py', 105, 148)).toMatch(
      /\/blob\/[0-9a-f]{7,40}\/declaw\/tools\/registry\.py#L105-L148$/,
    );
  });

  it('embeds the real code for a tier A component', () => {
    window.location.hash = '#/component/tool-registry';
    render(<App />);
    expect(screen.getByText(/ToolClass\.READ/)).toBeTruthy();
  });
});

describe('the machine', () => {
  const opacityOf = (id: string) =>
    Number((document.querySelector(`[data-part-group="${id}"]`) as SVGGElement).style.opacity);

  it('lights every part the ticket touches, including ones it only traverses', () => {
    const ticket = tickets.find((t) => t.traverses.length > 0)!;
    window.location.hash = `#/machine?ticket=${ticket.id}`;
    render(<App />);
    const related = expectedRelated(ticket);
    for (const part of machine.parts) {
      const lit = opacityOf(part.id) === 1;
      expect(lit, `${part.id} (${part.component}) for ${ticket.id}`).toBe(
        related.has(part.component),
      );
    }
  });

  it('opens only the clicked part, and can go back', async () => {
    const user = userEvent.setup();
    window.location.hash = '#/machine';
    render(<App />);
    const part = machine.parts[0];
    // Before opening, every part is on show.
    expect(document.querySelectorAll('[data-part-group]').length).toBe(machine.parts.length);

    await user.click(screen.getByRole('button', { name: part.label.en }));
    expect(window.location.hash).toContain(`part=${part.id}`);
    // Opening replaces the whole board with that part's own pieces, rather
    // than adding detail beside the others. The old board animates out, so
    // this waits for the transition instead of racing it.
    await waitFor(() =>
      expect(document.querySelectorAll('[data-part-group]').length).toBe(0),
    );
    expect(screen.getAllByText(part.subparts[0].path).length).toBeGreaterThan(0);
  });

  it('gives every part real modules to open', () => {
    for (const part of machine.parts) {
      expect(part.subparts.length, part.id).toBeGreaterThan(0);
    }
  });
});

describe('what is owed', () => {
  it('renders every debt item with its source citation', () => {
    window.location.hash = '#/debt';
    render(<App />);
    for (const item of debt) {
      expect(screen.getByText(item.title.en)).toBeTruthy();
      expect(
        screen.getAllByText(new RegExp(item.source.file.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
          .length,
      ).toBeGreaterThan(0);
    }
  });

  it('links every debt item to at least one component that carries it', () => {
    for (const item of debt) {
      expect(item.components.length, item.id).toBeGreaterThan(0);
    }
  });
});

describe('language', () => {
  it('renders Vietnamese when the hash asks for it', () => {
    window.location.hash = '#/map?lang=vi';
    render(<App />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Kiến trúc DeClaw');
  });

  it('renders English by default', () => {
    window.location.hash = '#/map';
    render(<App />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('DeClaw Architecture');
  });
});
