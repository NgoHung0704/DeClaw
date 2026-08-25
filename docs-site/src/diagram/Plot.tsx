import type { ReactNode } from 'react';

/**
 * A diagram, drawn straight onto the page.
 *
 * No frame and no zoom controls: a bordered viewport turned every diagram into
 * a small window you had to drive, and driving it was the thing that made the
 * page tiring. The drawing scales with the column instead, and only scrolls
 * sideways below the width where its labels stop being legible.
 */
export function Plot(props: { width: number; height: number; label: string; children: ReactNode }) {
  return (
    <div className="plot" role="group" aria-label={props.label}>
      <svg
        className="plot__svg"
        viewBox={`0 0 ${props.width} ${props.height}`}
        preserveAspectRatio="xMidYMid meet"
        role="presentation"
      >
        {props.children}
      </svg>
    </div>
  );
}
