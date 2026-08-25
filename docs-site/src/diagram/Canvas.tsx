import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ui } from '../content/load';
import { useT } from '../i18n/lang';

// Below this the labels stop being readable, so the camera stops shrinking
// and the reader pans instead. A diagram nobody can read is not a diagram.
const MIN_SCALE = 0.72;
const MAX_SCALE = 2.4;
const STEP = 0.2;

type View = { scale: number; x: number; y: number };

/**
 * A pan-and-zoom window onto a diagram.
 *
 * The drawing keeps its authored size and the camera moves over it. Scaling the
 * SVG down to fit its container instead is what turns a readable diagram into
 * unreadable grey hair — the box gets smaller but the labels shrink with it.
 *
 * Wheel-zoom is deliberately Ctrl/⌘-gated: hijacking a plain wheel inside a
 * long page traps the reader, who is usually trying to scroll past the diagram
 * rather than into it.
 */
export function Canvas(props: {
  width: number;
  height: number;
  children: ReactNode;
  label: string;
}) {
  const t = useT();
  const frameRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>({ scale: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);

  const fit = useCallback(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const scale = Math.min(
      MAX_SCALE,
      (frame.clientWidth - 32) / props.width,
      (frame.clientHeight - 32) / props.height,
    );
    const safe = Math.max(MIN_SCALE, scale);
    setView({
      scale: safe,
      x: (frame.clientWidth - props.width * safe) / 2,
      y: (frame.clientHeight - props.height * safe) / 2,
    });
  }, [props.width, props.height]);

  useEffect(() => {
    fit();
  }, [fit]);

  const zoomBy = (delta: number) => {
    const frame = frameRef.current;
    if (!frame) return;
    setView((v) => {
      const next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.scale + delta));
      const ratio = next / v.scale;
      // Keep the centre of the frame fixed while zooming, so the reader does
      // not lose the part they were looking at.
      const cx = frame.clientWidth / 2;
      const cy = frame.clientHeight / 2;
      return { scale: next, x: cx - (cx - v.x) * ratio, y: cy - (cy - v.y) * ratio };
    });
  };

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      zoomBy(event.deltaY > 0 ? -STEP / 2 : STEP / 2);
    };
    frame.addEventListener('wheel', onWheel, { passive: false });
    return () => frame.removeEventListener('wheel', onWheel);
  }, []);

  return (
    <div className="canvas">
      <div
        ref={frameRef}
        className="canvas__frame"
        role="group"
        aria-label={props.label}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          drag.current = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y };
          (event.target as Element).setPointerCapture?.(event.pointerId);
        }}
        onPointerMove={(event) => {
          const d = drag.current;
          if (!d) return;
          setView((v) => ({
            ...v,
            x: d.vx + (event.clientX - d.x),
            y: d.vy + (event.clientY - d.y),
          }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerLeave={() => {
          drag.current = null;
        }}
      >
        <div
          className="canvas__stage"
          style={{
            width: props.width,
            height: props.height,
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          }}
        >
          {props.children}
        </div>
      </div>

      <div className="canvas__controls">
        <button type="button" className="canvas__button" onClick={() => zoomBy(STEP)}>
          {t(ui.canvas.zoomIn)}
        </button>
        <button type="button" className="canvas__button" onClick={() => zoomBy(-STEP)}>
          {t(ui.canvas.zoomOut)}
        </button>
        <button type="button" className="canvas__button" onClick={fit}>
          {t(ui.canvas.fit)}
        </button>
        <span className="canvas__hint">{t(ui.canvas.hint)}</span>
      </div>
    </div>
  );
}
