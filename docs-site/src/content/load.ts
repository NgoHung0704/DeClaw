import componentsJson from '../../content/components.json';
import principlesJson from '../../content/principles.json';
import ticketsJson from '../../content/tickets.json';
import uiJson from '../../content/ui.json';
import type { Component, Detail, Loc, Principle, Ticket } from './types';

export const components = (componentsJson as { components: Component[] }).components;
export const tickets = (ticketsJson as unknown as { tickets: Ticket[] }).tickets;
export const principles = (principlesJson as { principles: Principle[] }).principles;
export const ui = uiJson as unknown as Record<string, Record<string, Loc>>;

export const componentById = new Map(components.map((c) => [c.id, c]));
export const ticketById = new Map(tickets.map((t) => [t.id, t]));
export const principleById = new Map(principles.map((p) => [p.id, p]));

/** Every component that a ticket creates, modifies, or merely passes through. */
export function relatedComponents(ticket: Ticket): Set<string> {
  return new Set([...ticket.creates, ...ticket.modifies, ...ticket.traverses]);
}

const detailModules = import.meta.glob('../../content/details/*.json', { eager: true });

export function loadDetail(name: string): Detail | undefined {
  const key = `../../content/details/${name}.json`;
  const mod = detailModules[key] as { default: Detail } | undefined;
  return mod?.default;
}
