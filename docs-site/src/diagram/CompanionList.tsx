import { useT } from '../i18n/lang';
import { ui } from '../content/load';
import type { Loc } from '../content/types';

export type ListNode = { id: string; label: Loc; kind: string };
export type ListEdge = { id: string; from: string; to: string; label: Loc };

/**
 * The diagram's text equivalent, and its keyboard surface.
 *
 * It is always rendered — never a collapsed fallback — because a diagram that
 * is aria-hidden with an incomplete substitute is worse than no diagram: a
 * function list carries no edge labels and no gate branch labels, so all the
 * branching logic disappears. Building this from the same records as the SVG
 * makes losing a label impossible.
 */
export function CompanionList(props: {
  nodes: ListNode[];
  edges: ListEdge[];
  onSelect: (kind: 'node' | 'edge', id: string) => void;
  dimmed?: Set<string>;
}) {
  const t = useT();
  const labelOf = (id: string) => {
    const node = props.nodes.find((n) => n.id === id);
    return node ? t(node.label) : id;
  };
  return (
    <div className="companion">
      <h3 className="companion__title">{t(ui.diagram.companionTitle)}</h3>
      <p className="companion__hint">{t(ui.diagram.companionHint)}</p>
      <ul className="companion__list">
        {props.nodes.map((node) => (
          <li key={node.id}>
            <button
              type="button"
              className="companion__button"
              data-kind={node.kind}
              data-dimmed={props.dimmed?.has(node.id) ? 'true' : 'false'}
              onClick={() => props.onSelect('node', node.id)}
            >
              {t(node.label)}
            </button>
          </li>
        ))}
        {props.edges.map((edge) => (
          <li key={edge.id}>
            <button
              type="button"
              className="companion__button companion__button--edge"
              onClick={() => props.onSelect('edge', edge.id)}
            >
              {`${labelOf(edge.from)} → ${labelOf(edge.to)}: ${t(edge.label)}`}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
