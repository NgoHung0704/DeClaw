# Tokens
Atlas: background #f7f9f8; surface white; ink #20362e; green #168167; muted #6b7d75; line #e0e7e2. Manrope headings, DM Sans body, 224px sidebar, 7–12px radii. Breakpoints 1250/900/640px. Dark and reduced motion supported. No existing logo image asset.
## `docs-site/src/styles/tokens.css`
```
/* Blueprint ground: deep navy, a fine technical grid, one signal colour.
 *
 * Light values sit on bare :root so a page with no stated preference still has
 * a complete palette. Dark is the primary look and is applied both by
 * prefers-color-scheme and by an explicit data-theme, so the toggle wins in
 * both directions. */
:root {
  --bg: #f6f7f9;
  --bg-raised: #ffffff;
  --bg-sunken: #eceef2;
  --grid-line: #e2e6ec;

  --line: #ccd3dd;
  --line-soft: #e2e6ec;

  --ink: #101620;
  --ink-muted: #47536a;
  --ink-faint: #6b7789;

  --signal: #0b6e63;
  --signal-soft: #dff2ef;
  --signal-line: #46a99b;

  --warn: #9a5b00;
  --warn-soft: #fbf0dd;
  --danger: #a02020;
  --danger-soft: #fbe6e6;

  --scrim: rgb(16 22 32 / 0.34);
  --glow: none;

  --font-display: "JetBrains Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
  --font-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-code: "JetBrains Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;

  /* One type scale for the whole site. Every size on the page comes from this
     ladder — mixing ad-hoc rem values is what makes a page look like it was
     assembled by three people who never spoke. */
  --step--2: clamp(0.69rem, 0.67rem + 0.08vw, 0.74rem);
  --step--1: clamp(0.79rem, 0.77rem + 0.1vw, 0.85rem);
  --step-0: clamp(0.94rem, 0.91rem + 0.16vw, 1rem);
  --step-1: clamp(1.12rem, 1.05rem + 0.34vw, 1.3rem);
  --step-2: clamp(1.35rem, 1.2rem + 0.75vw, 1.8rem);
  --step-3: clamp(1.7rem, 1.4rem + 1.5vw, 2.6rem);

  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.5rem;
  --space-6: 2rem;
  --space-8: 3rem;
  --space-10: 4.5rem;

  --radius: 10px;
  --radius-sm: 6px;
  --grid-size: 26px;

  --dur-fast: 140ms;
  --dur: 240ms;
  --dur-slow: 620ms;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) {
    --bg: #080d16;
    --bg-raised: #0d1520;
    --bg-sunken: #050810;
    --grid-line: #101c2b;

    --line: #1e3348;
    --line-soft: #142334;

    --ink: #dce7f2;
    --ink-muted: #9db1c6;
    --ink-faint: #7c8ea4;

    --signal: #3ae0c2;
    --signal-soft: #102b2a;
    --signal-line: #1f7f72;

    --warn: #f0aa4d;
    --warn-soft: #2a2014;
    --danger: #ff8a8a;
    --danger-soft: #2b1416;

    --scrim: rgb(2 5 10 / 0.66);
    --glow: 0 0 18px rgb(58 224 194 / 0.22);
  }
}

:root[data-theme='dark'] {
  --bg: #080d16;
  --bg-raised: #0d1520;
  --bg-sunken: #050810;
  --grid-line: #101c2b;

  --line: #1e3348;
  --line-soft: #142334;

  --ink: #dce7f2;
  --ink-muted: #9db1c6;
  --ink-faint: #7c8ea4;

  --signal: #3ae0c2;
  --signal-soft: #102b2a;
  --signal-line: #1f7f72;

  --warn: #f0aa4d;
  --warn-soft: #2a2014;
  --danger: #ff8a8a;
  --danger-soft: #2b1416;

  --scrim: rgb(2 5 10 / 0.66);
  --glow: 0 0 18px rgb(58 224 194 / 0.22);
}

```

## `docs-site/src/styles/layout.css`
```
*,
*::before,
*::after {
  box-sizing: border-box;
}

* {
  margin: 0;
}

html {
  -webkit-text-size-adjust: 100%;
  scroll-behavior: smooth;
}

/* The grid is a background image on body: nothing to draw, measure or keep in
   sync as the page grows. */
body {
  min-height: 100dvh;
  background-color: var(--bg);
  background-image:
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: var(--grid-size) var(--grid-size);
  color: var(--ink);
  font-family: var(--font-body);
  font-size: var(--step-0);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
}

h1,
h2,
h3,
h4 {
  font-family: var(--font-display);
  font-weight: 600;
  line-height: 1.18;
  letter-spacing: -0.02em;
}

h1 { font-size: var(--step-2); }
h2 { font-size: var(--step-2); }
h3 { font-size: var(--step-1); }
h4 { font-size: var(--step-0); }

code,
pre {
  font-family: var(--font-code);
  font-size: var(--step--1);
}

a { color: var(--signal); text-underline-offset: 3px; }

:focus-visible {
  outline: 2px solid var(--signal);
  outline-offset: 3px;
  border-radius: 3px;
}

.skip { position: absolute; left: -9999px; }
.skip:focus {
  left: var(--space-4);
  top: var(--space-4);
  z-index: 20;
  background: var(--bg-raised);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--signal);
  border-radius: var(--radius-sm);
}

/* ---- masthead ---------------------------------------------------------- */

.masthead {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) clamp(var(--space-4), 4vw, var(--space-8));
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg) 86%, transparent);
  backdrop-filter: blur(10px);
}
.masthead__title h1 { font-size: var(--step-1); }
.masthead__title p {
  margin-top: 2px;
  color: var(--ink-faint);
  font-size: var(--step--1);
  max-width: 60ch;
}
.masthead__controls { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; }

.nav, .grid, .modules, .node-notes, .debt__list, .tickets, .legend, .functions,
.quotes, .why, .ownership__notes, .contract__errors, .contract__principles,
.why__principles, .companion__list, .phases, .phase__tickets {
  list-style: none;
  margin: 0;
  padding: 0;
}

.nav { display: flex; flex-wrap: wrap; gap: 2px; }

.nav__button, .langswitch__button, .button, .chip, .card__button,
.companion__button, .functions__name, .panel__close {
  font: inherit;
  font-family: var(--font-display);
  font-size: var(--step--1);
  color: var(--ink-muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease-out),
    background-color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.nav__button:hover, .langswitch__button:hover, .button:hover, .chip:hover,
.companion__button:hover {
  color: var(--ink);
  background: var(--bg-raised);
  border-color: var(--line);
}
.nav__button[aria-current='page'], .langswitch__button[aria-pressed='true'] {
  color: var(--signal);
  background: var(--signal-soft);
  border-color: var(--signal-line);
}
.langswitch { display: flex; gap: 2px; }

main { padding: clamp(var(--space-5), 4vw, var(--space-8)); }

.view {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  max-width: 1400px;
  margin: 0 auto;
}
.view > section { display: flex; flex-direction: column; gap: var(--space-3); }
.lede { color: var(--ink-muted); max-width: 72ch; }

/* ---- filters ----------------------------------------------------------- */

.filters { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: end; }
.filters__field { display: flex; flex-direction: column; gap: var(--space-1); }
.filters__field > span {
  font-family: var(--font-display);
  font-size: var(--step--2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.filters__field select {
  font: inherit;
  font-size: var(--step--1);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  border: 1px solid var(--line);
  background: var(--bg-raised);
  color: var(--ink);
  max-width: min(90vw, 34rem);
}

/* ---- component grid ---------------------------------------------------- */

.group { display: flex; flex-direction: column; gap: var(--space-3); }
.group__title {
  font-family: var(--font-display);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-size: var(--step--2);
  color: var(--ink-faint);
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.group__title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--line-soft);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 20rem), 1fr));
  gap: var(--space-3);
}
.card {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-raised);
  transition: border-color var(--dur) var(--ease-out), transform var(--dur) var(--ease-out);
}
.card:hover { border-color: var(--signal-line); }
.card__button {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  text-align: left;
  width: 100%;
  height: 100%;
  padding: var(--space-4);
  font-family: var(--font-body);
  font-size: var(--step-0);
}
.card__title { font-family: var(--font-display); font-weight: 600; color: var(--ink); }
.card__summary { color: var(--ink-muted); font-size: var(--step--1); }
.card__meta {
  font-family: var(--font-display);
  font-size: var(--step--2);
  color: var(--ink-faint);
  letter-spacing: 0.04em;
}

/* ---- phases ------------------------------------------------------------ */

.phases { display: flex; flex-direction: column; }
.phase { display: grid; grid-template-columns: 28px 1fr; gap: var(--space-4); }
.phase__rail { position: relative; display: flex; justify-content: center; }
.phase__rail::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--line);
}
.phase:first-child .phase__rail::before { top: 14px; }
.phase:last-child .phase__rail::before { bottom: calc(100% - 14px); }
.phase__dot {
  position: relative;
  margin-top: 8px;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--bg);
  border: 2px solid var(--signal);
  box-shadow: var(--glow);
}
.phase__body { padding-bottom: var(--space-6); display: flex; flex-direction: column; gap: var(--space-3); }
.phase__head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-3); }
.phase__number {
  font-family: var(--font-display);
  font-size: var(--step-2);
  color: var(--signal);
  line-height: 1;
}
.phase__title { flex: 1; min-width: 12rem; }
.phase__count {
  font-family: var(--font-display);
  font-size: var(--step--2);
  color: var(--ink-faint);
}
.phase__tickets { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.phase__components { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; }
.phase__label { font-size: var(--step--2); color: var(--ink-faint); font-family: var(--font-display); }

.chip {
  font-size: var(--step--2);
  padding: 3px var(--space-2);
  border-color: var(--line-soft);
  background: var(--bg-raised);
}
.chip[data-status='done'] { border-color: var(--signal-line); color: var(--signal); }
.chip--quiet { color: var(--ink-faint); }

/* ---- tables and prose -------------------------------------------------- */

.table-scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius); }
.ownership__table { border-collapse: collapse; width: 100%; min-width: 52rem; font-size: var(--step--1); }
.ownership__table th, .ownership__table td {
  padding: var(--space-3);
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--line-soft);
}
.ownership__table thead th {
  font-family: var(--font-display);
  font-size: var(--step--2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  background: var(--bg-sunken);
}
.ownership__table tbody tr:hover { background: var(--bg-raised); }
.ownership__notes, .node-notes { display: grid; gap: var(--space-2); font-size: var(--step--1); }
.ownership__notes li, .node-notes li { display: grid; grid-template-columns: 15rem 1fr; gap: var(--space-3); }
.ownership__notes strong, .node-notes strong { font-family: var(--font-display); color: var(--ink); }
.ownership__notes span, .node-notes span { color: var(--ink-muted); }

.modules { display: grid; gap: var(--space-1); }
.link { color: var(--signal); }
.mono { font-family: var(--font-code); font-size: var(--step--1); overflow-wrap: anywhere; }

.functions__item {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--line-soft);
}
.functions__name {
  justify-self: start;
  padding: 0;
  color: var(--ink);
  font-weight: 600;
  border: 0;
  border-bottom: 1px solid var(--signal-line);
  border-radius: 0;
}
.functions__signature { color: var(--ink-muted); overflow-wrap: anywhere; }

.snippet { display: flex; flex-direction: column; gap: var(--space-2); margin-bottom: var(--space-5); }
.snippet figcaption { color: var(--ink-muted); font-size: var(--step--1); }
.snippet__code {
  margin: 0;
  padding: var(--space-4);
  background: var(--bg-sunken);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow-x: auto;
  line-height: 1.55;
}

.quotes li, .why__card {
  border-left: 2px solid var(--signal-line);
  padding: var(--space-1) 0 var(--space-1) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.why { display: flex; flex-direction: column; gap: var(--space-5); }
.why__source, .debt__source, .contract__source { color: var(--ink-faint); font-size: var(--step--1); }
.why__principles { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.why__principles li {
  font-size: var(--step--2);
  color: var(--ink-faint);
  border: 1px solid var(--line-soft);
  border-radius: 999px;
  padding: 2px var(--space-2);
}

/* ---- debt -------------------------------------------------------------- */

.debt__group { display: flex; flex-direction: column; gap: var(--space-3); }
.debt__list { display: grid; gap: var(--space-3); grid-template-columns: repeat(auto-fill, minmax(min(100%, 26rem), 1fr)); }
.debt__item {
  border: 1px solid var(--line);
  border-left-width: 3px;
  border-radius: var(--radius);
  padding: var(--space-4);
  background: var(--bg-raised);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.debt__item[data-severity='unbuilt'] { border-left-color: var(--danger); }
.debt__item[data-severity='unvalidated'] { border-left-color: var(--warn); }
.debt__item[data-severity='temporary'] { border-left-color: var(--signal-line); }
.debt__affects { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; font-size: var(--step--1); }

.tickets, .legend { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.legend { flex-direction: column; gap: var(--space-1); font-size: var(--step--1); color: var(--ink-muted); }

/* ---- panel ------------------------------------------------------------- */

.panel__scrim {
  position: fixed;
  inset: 0;
  z-index: 30;
  background: var(--scrim);
  backdrop-filter: blur(2px);
}
.panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 31;
  width: min(38rem, 100vw);
  background: var(--bg-raised);
  border-left: 1px solid var(--line);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.panel__bar {
  position: sticky;
  top: 0;
  display: flex;
  gap: var(--space-4);
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4);
  border-bottom: 1px solid var(--line);
  background: var(--bg-raised);
}
.panel__title { font-size: var(--step-1); }
.panel__body { padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-3); }
.panel__section {
  font-family: var(--font-display);
  font-size: var(--step--2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  margin-top: var(--space-3);
}

.contract__row {
  display: grid;
  grid-template-columns: 9rem 1fr;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--line-soft);
}
.contract__row dt { color: var(--ink-faint); font-size: var(--step--1); font-family: var(--font-display); }
.contract__row dd { margin: 0; overflow-wrap: anywhere; }
.contract__errors { display: grid; gap: var(--space-2); }
.contract__errors li {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-2);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  background: var(--bg-sunken);
}
.contract__code { font-family: var(--font-code); color: var(--danger); font-size: var(--step--1); }
.contract__principles { display: flex; flex-wrap: wrap; gap: var(--space-2); font-size: var(--step--1); color: var(--ink-faint); }

@media (max-width: 900px) {
  .phase { grid-template-columns: 20px 1fr; }
  .ownership__notes li, .node-notes li { grid-template-columns: 1fr; gap: var(--space-1); }
  .contract__row { grid-template-columns: 1fr; }
  .panel { width: 100vw; }
}

.partlist { display: flex; flex-direction: column; gap: var(--space-2); }
.partlist__title {
  font-family: var(--font-display);
  font-size: var(--step--2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.partlist__hint { font-size: var(--step--1); color: var(--ink-faint); }
.partlist__items { display: flex; flex-wrap: wrap; gap: var(--space-2); list-style: none; margin: 0; padding: 0; }
.partlist__items .chip[aria-current='true'] {
  color: var(--signal);
  border-color: var(--signal);
  background: var(--signal-soft);
}

```

## `docs-site/src/styles/diagram.css`
```
.diagram {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 20rem);
  gap: var(--space-4);
  align-items: start;
}

/* ---- plot -------------------------------------------------------------- */

/* No frame, no viewport, no controls. The drawing sits on the page and scales
   with its column; it only scrolls sideways below the width where its own
   labels stop being legible. */
.plot {
  overflow-x: auto;
  overflow-y: hidden;
}
.plot__svg {
  display: block;
  width: 100%;
  height: auto;
  min-width: 720px;
  overflow: visible;
}

/* ---- nodes ------------------------------------------------------------- */

.node__shape {
  fill: var(--bg-raised);
  stroke: var(--node-line, var(--ink-faint));
  stroke-width: 1.5;
  /* Without this a 1.5px border becomes 0.9px at 60% zoom and a dark-on-dark
     outline simply stops being visible. */
  vector-effect: non-scaling-stroke;
  transition: stroke var(--dur-fast) var(--ease-out), fill var(--dur-fast) var(--ease-out);
}
.node__label {
  fill: var(--ink);
  font-family: var(--font-body);
  font-size: 12.5px;
  font-weight: 500;
}

.node--core .node__shape,
.node--port .node__shape { fill: var(--signal-soft); --node-line: var(--signal); }
.node--external .node__shape { --node-line: var(--signal-line); }
.node--gate .node__shape { fill: var(--warn-soft); --node-line: var(--warn); }
.node--exit .node__shape { fill: var(--bg-sunken); --node-line: var(--ink-faint); }
.node--planned .node__shape {
  fill: transparent;
  --node-line: var(--ink-faint);
  stroke-dasharray: 6 5;
  opacity: 0.75;
}
.node--planned .node__label { fill: var(--ink-faint); }

.node--interactive { cursor: pointer; }
.node--interactive:hover .node__shape,
.node--interactive:focus-visible .node__shape {
  --node-line: var(--signal);
  stroke-width: 2.2;
  filter: drop-shadow(var(--glow));
}
.node--interactive:focus { outline: none; }

/* ---- edges ------------------------------------------------------------- */

.edge { color: var(--ink-faint); }
.edge__line {
  stroke: var(--ink-faint);
  stroke-width: 1.4;
  vector-effect: non-scaling-stroke;
  transition: stroke var(--dur-fast) var(--ease-out);
}
.edge__label {
  fill: var(--ink-faint);
  font-family: var(--font-display);
  font-size: 10.5px;
  paint-order: stroke;
  stroke: var(--bg-sunken);
  stroke-width: 3.5px;
  stroke-linejoin: round;
}
.edge--interactive { cursor: pointer; }
.edge--interactive:hover { color: var(--signal); }
.edge--interactive:hover .edge__line { stroke: var(--signal); stroke-width: 2; }
.edge--interactive:hover .edge__label { fill: var(--signal); }

/* ---- companion list ---------------------------------------------------- */

.companion {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-raised);
  padding: var(--space-3);
  max-height: clamp(24rem, 56vh, 40rem);
  overflow-y: auto;
}
.companion__title {
  font-family: var(--font-display);
  font-size: var(--step--2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.companion__hint {
  margin: var(--space-1) 0 var(--space-3);
  font-size: var(--step--2);
  color: var(--ink-faint);
}
.companion__list { display: grid; gap: 2px; }
.companion__button {
  width: 100%;
  text-align: left;
  font-family: var(--font-body);
  padding: var(--space-2);
}
.companion__button--edge { color: var(--ink-faint); font-size: var(--step--2); }

@media (max-width: 1100px) {
  .diagram { grid-template-columns: 1fr; }
  .companion { max-height: none; }
}

/* Motion is opt-in, never opt-out: reduced motion strips it everywhere,
   including anything a library writes inline. */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}

/* ---- the machine ------------------------------------------------------- */

.chassis__shape {
  fill: color-mix(in srgb, var(--bg-raised) 60%, transparent);
  stroke: var(--signal-line);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
  stroke-dasharray: 2 6;
  stroke-linecap: round;
}
.chassis__label {
  fill: var(--signal);
  font-family: var(--font-display);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.slot__shape {
  fill: var(--bg-sunken);
  stroke: var(--ink-faint);
  stroke-width: 1.4;
  vector-effect: non-scaling-stroke;
}
.slot--port .slot__shape { fill: var(--signal-soft); stroke: var(--signal-line); }
.slot__label { fill: var(--ink); font-family: var(--font-body); font-size: 12px; }

.wire {
  fill: none;
  stroke: var(--ink-faint);
  stroke-width: 1.4;
  vector-effect: non-scaling-stroke;
}
.wire--bus { stroke: var(--signal-line); stroke-width: 2; }
.wire--in { stroke: var(--signal-line); }
.wire__label {
  fill: var(--ink-faint);
  font-family: var(--font-display);
  font-size: 10.5px;
  paint-order: stroke;
  stroke: var(--bg-sunken);
  stroke-width: 4px;
  stroke-linejoin: round;
}

.part { cursor: pointer; }
.part:focus { outline: none; }
.part__shape {
  fill: var(--bg-raised);
  stroke: var(--line);
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
  transition: stroke var(--dur-fast) var(--ease-out);
}
.part:hover .part__shape,
.part:focus-visible .part__shape {
  stroke: var(--signal);
  stroke-width: 2.4;
  filter: drop-shadow(var(--glow));
}
.part__shape--open { fill: var(--bg-sunken); stroke: var(--signal); stroke-width: 1.8; }
.part__label { fill: var(--ink); font-family: var(--font-body); font-size: 13px; }
.part__count {
  fill: var(--ink-faint);
  font-family: var(--font-display);
  font-size: 10px;
  letter-spacing: 0.08em;
}
.part__open-title {
  fill: var(--ink);
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
}
.part__open-note { fill: var(--ink-muted); font-family: var(--font-body); font-size: 12px; }

.subpart__shape {
  fill: var(--bg-raised);
  stroke: var(--line-soft);
  stroke-width: 1.2;
  vector-effect: non-scaling-stroke;
}
.subpart__label {
  fill: var(--ink-muted);
  font-family: var(--font-code);
  font-size: 11px;
}

.part__back { cursor: pointer; }
.part__back rect {
  fill: var(--bg-raised);
  stroke: var(--line);
  stroke-width: 1.2;
  vector-effect: non-scaling-stroke;
}
.part__back text {
  fill: var(--ink-muted);
  font-family: var(--font-display);
  font-size: 11px;
}
.part__back:hover rect { stroke: var(--signal); }
.part__back:hover text { fill: var(--signal); }

.partdetail { display: flex; flex-direction: column; gap: var(--space-3); }

/* ---- grouped bands ----------------------------------------------------- */

.band__shape {
  fill: color-mix(in srgb, var(--bg-raised) 45%, transparent);
  stroke: var(--line-soft);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.band__label {
  fill: var(--ink-faint);
  font-family: var(--font-display);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.band--g-planned .band__shape { stroke-dasharray: 5 5; }
.band--g-isolation .band__shape { stroke: var(--signal-line); }

```

## `architecture-site/style.css`
```
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;450;500;550;600;650;700&family=Manrope:wght@400;500;600;650;700;750;800&display=swap');
:root{--bg:#f7f9f8;--surface:#fff;--soft:#f0f5f2;--ink:#20362e;--muted:#6b7d75;--line:#e0e7e2;--green:#168167;--green-soft:#e6f4ed;--shadow:0 5px 24px #193f2510;--sidebar:224px;color-scheme:light;font-family:'DM Sans',system-ui,sans-serif;color:var(--ink);background:var(--bg);font-synthesis:none}
:root[data-theme=dark]{--bg:#111b17;--surface:#18241e;--soft:#1c2e25;--ink:#e5eee8;--muted:#a0b5a8;--line:#304438;--green:#68d6ac;--green-soft:#203e30;--shadow:0 5px 24px #0003;color-scheme:dark}
*{box-sizing:border-box}body{margin:0}button,input,select{font:inherit}button,a,input,select{touch-action:manipulation}button{color:inherit;cursor:pointer}button:disabled{opacity:.4;cursor:default}button{border:0;background:none}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,pre:focus-visible{outline:3px solid var(--green);outline-offset:4px}a{color:inherit;text-decoration:none}h1,h2,h3,p{margin:0}h1,h2,h3{font-family:Manrope,'DM Sans',sans-serif}p{line-height:1.7}code,pre{font-family:'Cascadia Code',Consolas,monospace}.icon{width:20px;height:20px;flex:none;vertical-align:middle}button .icon{pointer-events:none}.sidebar{position:fixed;inset:0 auto 0 0;width:var(--sidebar);background:var(--surface);border-right:1px solid var(--line);display:flex;flex-direction:column;padding:32px 19px;z-index:5}.wordmark{display:flex;align-items:center;gap:11px;font-family:Manrope,sans-serif;font-size:25px;font-weight:800;letter-spacing:-1px;padding:0 9px}.brand-symbol{background:#214f3d;color:#e8fff1;width:39px;height:43px;border-radius:13px 13px 17px 5px;display:grid;place-items:center}.brand-symbol .icon{width:25px;height:25px}.brand-sub{display:block;letter-spacing:3.8px;font-family:'DM Sans',sans-serif;font-size:9px;font-weight:600;margin-top:0;color:var(--muted)}.workspace-label{margin:34px 0 33px;padding:12px;border:1px solid var(--line);border-radius:8px;font-size:12px;display:flex;align-items:center;gap:8px}.status-dot{display:inline-block;width:6px;height:6px;flex:none;background:var(--green);border-radius:50%;box-shadow:0 0 0 3px var(--green-soft)}.version{margin-left:auto;color:var(--muted);font-size:10px}.nav-caption{font-size:9px;letter-spacing:1.6px;color:var(--muted);margin:0 12px 13px}.sidebar nav{display:grid;gap:7px}.nav-link{display:flex;align-items:center;gap:11px;padding:12px;font-size:12px;font-weight:550;text-align:left;border-radius:7px;line-height:1.4}.nav-link .icon{width:17px;height:17px;color:var(--muted)}.nav-link.active{background:var(--green-soft);color:var(--green)}.nav-link.active .icon{color:var(--green)}.nav-link:hover{background:var(--soft)}.sidebar-bottom{margin-top:auto}.local-note{border-top:1px solid var(--line);padding:22px 6px;display:flex;gap:10px}.local-note>.icon{color:var(--green);width:19px}.local-note strong{display:block;font-size:11px;font-weight:550}.local-note span{font-size:9px;color:var(--muted);display:block;margin-top:5px}.sidebar-meta{display:flex;justify-content:space-between;padding:3px 6px;color:var(--muted);font-size:9px}.shell{margin-left:var(--sidebar)}.topbar{height:76px;border-bottom:1px solid var(--line);padding:0 42px;display:flex;align-items:center;justify-content:space-between;background:var(--surface)}.breadcrumb{display:flex;gap:13px;align-items:center;font-size:11px;color:var(--muted)}.breadcrumb strong{color:var(--ink);font-weight:500}.breadcrumb .icon{width:12px}.header-actions{display:flex;align-items:center;gap:13px}.icon-button{display:inline-flex;align-items:center;justify-content:center;padding:8px;border-radius:6px}.icon-button>span{position:absolute;clip-path:inset(50%);width:1px;height:1px;overflow:hidden}.icon-button:hover{background:var(--soft)}.icon-button .icon{width:17px;height:17px}.language{display:flex;align-items:center;gap:7px;border:1px solid var(--line);padding:5px 8px;border-radius:6px;font-size:11px}.language select{border:0;background:transparent;padding:3px;max-width:105px;color:var(--ink)}main{max-width:1540px;padding:42px 42px 0;margin:auto}.hero{display:flex;align-items:center;justify-content:space-between;margin:0 0 33px;gap:35px}.eyebrow{display:flex;align-items:center;gap:9px;font-size:9px;letter-spacing:1.7px;font-weight:650;color:var(--green);text-transform:uppercase;margin-bottom:15px}h1{font-size:clamp(30px,3vw,46px);font-weight:650;line-height:1.22;letter-spacing:-1.8px}.hero-description{max-width:590px;margin-top:17px;font-size:12px;color:var(--muted);line-height:1.8}.hero-right{display:flex;flex-direction:column;gap:15px;align-items:center;flex:none;padding-top:30px}.primary,.secondary{display:inline-flex;align-items:center;justify-content:center;gap:10px;border-radius:7px;padding:12px 17px;font-size:11px;font-weight:550;line-height:1.4}.primary{background:#217c60;color:white;box-shadow:0 3px 6px #163c2212}.primary:hover{background:#17694f}.primary .icon{width:15px;height:15px}.secondary{border:1px solid var(--line);background:var(--surface)}.secondary:hover{background:var(--soft)}.verified{display:flex;align-items:center;gap:5px;font-size:9px;color:var(--muted)}.verified .icon{width:12px;height:12px;color:var(--green)}.map-card{border:1px solid var(--line);border-radius:12px;background:var(--surface);box-shadow:var(--shadow);overflow:hidden}.section-bar{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:21px 24px;border-bottom:1px solid var(--line)}h2{font-size:15px;font-weight:650;letter-spacing:-.25px}.section-bar p{font-size:10px;color:var(--muted);margin-top:7px;max-width:480px}.section-bar code{font-size:11px;display:block;color:var(--muted);margin-top:8px}.segmented{display:flex;border:1px solid var(--line);background:var(--soft);border-radius:7px;padding:3px;flex:none}.segmented button{font-size:10px;padding:7px 11px;border-radius:5px}.segmented .selected{background:var(--surface);box-shadow:0 1px 4px #0001;color:var(--green)}.map-surface{position:relative;background-color:var(--bg);background-image:radial-gradient(var(--line) 1px,transparent 1px);background-size:17px 17px}.map-scroll{overflow:auto;padding:0;scrollbar-width:thin;scrollbar-color:var(--line) transparent}.graph-scaler{position:relative;margin:0 auto}.graph-world{position:relative;width:1060px;height:625px;transform-origin:top left}.machine-boundary{position:absolute;top:19px;left:30px;font-size:8px;letter-spacing:1.5px;color:var(--muted);display:flex;align-items:center;gap:7px}.machine-boundary .icon{width:12px;height:12px}.process-boundary{position:absolute;left:271px;top:43px;width:518px;height:551px;border:1px dashed #7dab9270;border-radius:13px;background:#6dba8610}.process-boundary>span{position:absolute;bottom:7px;left:20px;font-size:8px;color:var(--muted)}.wires{position:absolute;inset:0;pointer-events:none}.wire{fill:none;stroke:#8ba49b;stroke-width:1.5}.wire.live{stroke:#138769;stroke-width:2.5;stroke-dasharray:7 5}.node{position:absolute;width:218px;height:94px;background:var(--surface);border:1px solid var(--line);border-radius:9px;box-shadow:0 3px 8px #163d2410;text-align:left;padding:11px 13px;z-index:1;display:block}.node:hover{border-color:var(--green);box-shadow:0 5px 16px #163d2420;transform:translateY(-3px)}.node-top{display:flex;align-items:center;gap:8px}.node-icon{width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center;background:var(--green-soft);color:var(--green);border-radius:7px;flex:none}.node-icon .icon{width:17px;height:17px}.node-title{font-size:11px;font-weight:650;line-height:1.2}.node-chevron{width:11px;height:11px;margin-left:auto;color:var(--muted)}.node-subtitle{display:block;margin-top:5px;color:var(--muted);font-size:9px;line-height:1.3;white-space:nowrap;text-overflow:ellipsis;overflow:hidden}.node-tech{display:flex;align-items:center;gap:5px;font-size:8px;color:var(--muted);margin-top:7px}.node-tech i{width:4px;height:4px;border-radius:50%;background:#8bbca2}.node.safety .node-icon,.component-card.safety .node-icon{background:#eeeaf7;color:#86709e}.node.runtime .node-icon,.component-card.runtime .node-icon{background:#eaf0f6;color:#6383a4}.node.entry .node-icon,.component-card.entry .node-icon{background:#f9eddc;color:#a8874f}.node.illuminated{border:2px solid var(--green);box-shadow:0 0 0 4px var(--green-soft),0 5px 15px #16816718}.node.dimmed{opacity:.36}.column-label{position:absolute;bottom:8px;width:218px;text-align:center;font-size:8px;letter-spacing:.6px;color:var(--muted)}.context-note{position:absolute;left:25px;top:520px;width:710px;font-size:11px;line-height:1.8;color:var(--muted)}.map-bottom{padding:10px 18px;display:flex;justify-content:space-between;align-items:center;gap:15px;border-top:1px solid var(--line);background:var(--surface)}.map-bottom>span{font-size:9px;display:flex;align-items:center;gap:8px;color:var(--muted)}.map-bottom>span .icon{width:12px;height:12px}.zoom{display:flex;align-items:center;gap:4px;background:var(--surface);border:1px solid var(--line);border-radius:6px}.zoom>span{font-size:9px;min-width:31px;text-align:center}.zoom .icon-button{padding:6px}.zoom .icon{width:13px;height:13px}.map-footer{padding:15px 22px;display:flex;align-items:center;gap:22px;border-top:1px solid var(--line)}.badge{display:inline-flex;align-items:center;gap:6px;font-size:9px;color:var(--green);white-space:nowrap}.badge i{width:5px;height:5px;background:var(--green);border-radius:50%}.planned-note{display:flex;align-items:center;gap:7px;font-size:9px;color:var(--muted);line-height:1.6}.planned-dot{height:6px;width:6px;border:1px dashed var(--muted);border-radius:50%;flex:none}.below-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:20px;margin-top:20px}.explain-card,.journey-promo{border:1px solid var(--line);border-radius:9px;padding:20px;display:flex;align-items:flex-start;gap:13px;background:var(--surface);text-align:left}.explain-card>.icon{width:17px;height:17px;color:var(--green);margin-top:2px}.explain-card h3{font-size:11px}.explain-card p{font-size:10px;color:var(--muted);margin-top:7px}.journey-promo{align-items:center;background:var(--green-soft)}.promo-icon{width:40px;height:40px;background:var(--surface);display:grid;place-items:center;border-radius:9px;flex:none;color:var(--green)}.journey-promo strong{font-size:12px;display:block}.journey-promo small{display:block;color:var(--muted);font-size:10px;line-height:1.6;margin-top:7px}.journey-promo>.icon{margin-left:auto;color:var(--green);width:17px}.contracts{margin-top:24px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}.contracts summary{cursor:pointer;font-size:12px;padding:18px}.contracts summary>span{margin-left:10px;color:var(--muted)}.connection-list{display:grid;gap:0}.connection-row{display:flex;align-items:center;gap:16px;width:100%;padding:14px 18px;text-align:left;border-top:1px solid var(--line);font-size:11px}.connection-row>span{display:flex;align-items:center;gap:8px;color:var(--muted);flex:1;flex-wrap:wrap}.connection-row .icon{width:13px;height:13px}.connection-row strong{font-size:10px;max-width:35%;font-weight:500}.connection-row:hover{background:var(--soft)}footer{display:flex;justify-content:space-between;gap:15px;border-top:1px solid var(--line);margin-top:35px;padding:20px 0;font-size:9px;color:var(--muted)}.page-heading{margin-bottom:30px}.page-heading h1{font-size:34px;letter-spacing:-1.3px}.page-heading>p:last-child{max-width:700px;font-size:12px;color:var(--muted);margin-top:14px}.journey-tabs{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:20px}.journey-tabs button{padding:10px 14px;border:1px solid var(--line);border-radius:7px;background:var(--surface);font-size:11px}.journey-tabs button.selected{background:var(--green-soft);border-color:var(--green);color:var(--green)}.flow-controls{display:flex;gap:8px;align-items:center}.stepper{display:flex;overflow:auto;border-bottom:1px solid var(--line);padding:16px 22px;gap:14px;scrollbar-width:thin}.step{display:flex;align-items:center;gap:8px;flex:1;min-width:126px;text-align:left}.step>span{width:25px;height:25px;display:grid;place-items:center;border:1px solid var(--line);border-radius:50%;font-size:9px;flex:none;color:var(--muted)}.step strong{font-size:9px;font-weight:500;line-height:1.5;color:var(--muted)}.step.active>span{background:var(--green);border-color:var(--green);color:var(--surface)}.step.active strong{color:var(--green);font-weight:650}.step.complete>span{background:var(--green-soft);border-color:var(--green-soft);color:var(--green)}.step.complete .icon{width:13px}.flow-explanation{padding:24px;display:grid;grid-template-columns:1.1fr 1fr;gap:35px;border-top:1px solid var(--line)}.flow-explanation .eyebrow{margin-bottom:7px;font-size:8px}.flow-explanation h3{font-size:17px}.flow-explanation p{font-size:11px;margin-top:10px;color:var(--muted)}.step-contract{border-left:1px solid var(--line);padding-left:28px;display:flex;flex-direction:column;justify-content:center;gap:12px;min-width:0}.step-contract>span{font-size:10px;color:var(--green)}.step-contract code{font-size:11px;line-height:1.6;overflow-wrap:anywhere}.text-button{color:var(--green);display:inline-flex;gap:8px;align-items:center;font-size:10px;align-self:flex-start;padding:0}.text-button .icon{width:14px}.flow-pagination{padding:0 24px 22px;display:flex;justify-content:space-between}.directory-toolbar{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:24px;font-size:11px;color:var(--muted)}.search-field{display:flex;align-items:center;gap:10px;background:var(--surface);padding:11px 13px;border:1px solid var(--line);border-radius:7px;width:min(370px,65%)}.search-field .icon{width:15px;height:15px}.search-field input{min-width:0;width:100%;background:transparent;border:0;font-size:11px;color:var(--ink)}.component-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.component-card{padding:23px;background:var(--surface);border:1px solid var(--line);border-radius:10px;text-align:left;position:relative}.component-card:hover{border-color:var(--green);transform:translateY(-3px);box-shadow:var(--shadow)}.component-card>.node-icon{width:35px;height:35px;margin-bottom:21px}.component-card>.badge{position:absolute;right:19px;top:30px;color:var(--muted);font-size:9px}.component-card h2{font-size:16px}.component-card p{font-size:11px;color:var(--muted);margin-top:10px;min-height:36px}.component-card code{display:block;font-size:9px;margin-top:15px;color:var(--muted)}.card-link{display:flex;align-items:center;justify-content:space-between;margin-top:24px;border-top:1px solid var(--line);padding-top:14px;font-size:10px;color:var(--green)}.card-link .icon{width:15px}.empty{padding:40px;color:var(--muted);grid-column:1/-1}.lesson-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.lesson{border:1px solid var(--line);border-radius:11px;background:var(--surface);padding:28px;text-align:left}.lesson-number{font-family:Manrope,sans-serif;font-size:40px;letter-spacing:-2px;color:var(--green);opacity:.6}.lesson h2{margin-top:23px;font-size:18px}.lesson p{margin-top:12px;color:var(--muted);font-size:12px}.lesson>.icon{margin-top:24px;color:var(--green)}.lesson:hover{border-color:var(--green);box-shadow:var(--shadow)}.guide-note{display:flex;gap:18px;margin-top:25px;padding:26px;background:var(--green-soft);border-radius:10px}.guide-note>.icon{color:var(--green)}.guide-note h3{font-size:14px}.guide-note p{font-size:12px;color:var(--muted);margin-top:10px}.skip{position:fixed;top:-60px;left:12px;z-index:99;background:var(--surface);padding:12px}.skip:focus{top:10px}
dialog{border:0;border-left:1px solid var(--line);margin:0 0 0 auto;padding:0;width:min(680px,94vw);height:100dvh;max-height:100dvh;max-width:100vw;background:var(--surface);color:var(--ink);box-shadow:-15px 0 80px #10261c22;overflow:hidden}dialog[open]{display:flex;flex-direction:column}dialog::backdrop{background:#0b201a65;backdrop-filter:blur(3px)}.dialog-top{display:flex;justify-content:space-between;align-items:center;padding:18px 25px;border-bottom:1px solid var(--line);color:var(--muted);font-size:10px;flex:none}.detail-identity{display:flex;gap:15px;align-items:center;padding:29px 28px 24px;flex:none}.detail-identity>.node-icon{width:48px;height:48px}.detail-identity>.node-icon .icon{width:26px;height:26px}.detail-identity .eyebrow{font-size:8px;margin-bottom:7px}.detail-identity h2{font-size:24px;letter-spacing:-.8px;line-height:1.3}.detail-identity code{font-size:10px;color:var(--muted);display:block;margin-top:8px}.detail-tabs{display:flex;border-bottom:1px solid var(--line);padding:0 20px;overflow:auto;flex:none}.detail-tabs button{font-size:10px;padding:15px 11px;border-bottom:2px solid transparent;white-space:nowrap}.detail-tabs button.active{border-color:var(--green);color:var(--green)}.detail-body{padding:29px 28px;overflow:auto;flex:1}.detail-description{font-size:14px;line-height:1.9}.detail-body h3{font-size:14px;margin-bottom:14px}.detail-body .eyebrow{font-size:9px}.io-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:28px 0}.io-grid>div{padding:17px;background:var(--soft);border-radius:8px}.io-grid span{font-size:10px;font-weight:650;color:var(--green)}.io-grid p{font-size:12px;margin-top:10px}.rule{display:flex;gap:12px;background:var(--green-soft);border:1px solid var(--line);border-radius:8px;padding:18px;margin:23px 0}.rule>.icon{color:var(--green);width:19px}.rule h3{font-size:11px;margin-bottom:8px}.rule p{font-size:12px;line-height:1.8}.internal-flow{display:grid;gap:15px;margin:22px 0}.internal-step{position:relative;display:flex;align-items:center;gap:13px;border:1px solid var(--line);padding:17px;border-radius:8px;background:var(--soft)}.internal-step:not(:last-child):after{content:'↓';position:absolute;top:100%;left:30px;font-size:13px;color:var(--green)}.internal-flow.branching{grid-template-columns:1fr 1fr}.internal-flow.branching .internal-step:after{content:none}.internal-flow.branching .internal-step:first-child,.internal-flow.branching .internal-step:last-child:nth-child(4){grid-column:1/-1}.internal-step>span{color:var(--green);font-family:monospace;font-size:12px}.internal-step strong{font-size:12px;font-weight:500;line-height:1.6}.file-row{display:flex;gap:9px;align-items:center;padding:13px 0;border-bottom:1px solid var(--line);font-family:monospace;font-size:11px;width:100%;text-align:left;color:var(--green);overflow-wrap:anywhere}.file-row span{min-width:0}.file-row:hover{background:var(--soft)}.file-row .icon{width:15px}.muted{font-size:12px;color:var(--muted)}.file-select{display:block;margin:20px 0}.file-select select{padding:12px;width:100%;border:1px solid var(--line);border-radius:6px;background:var(--soft);color:var(--ink);font-family:monospace;font-size:11px}.source-meta{font-size:9px;color:var(--muted);display:flex;justify-content:space-between;gap:12px;overflow-wrap:anywhere;margin:10px 0}.source-code{font-size:10px;line-height:1.8;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:12px 0;overflow:auto;tab-size:4}.code-line{display:block;min-height:18px;padding-right:15px}.line-number{display:inline-block;width:40px;padding-right:12px;text-align:right;color:var(--muted);user-select:none;opacity:.7}.edge-endpoints{display:flex;align-items:center;gap:14px;margin-bottom:26px}.endpoint{background:var(--soft);border:1px solid var(--line);padding:15px;display:flex;align-items:center;gap:9px;border-radius:8px;font-size:12px;flex:1;text-align:left}.endpoint:hover{border-color:var(--green)}.endpoint .icon{color:var(--green);width:18px}.contract-fields dt{font-size:10px;color:var(--green);margin:24px 0 10px}.contract-fields dd{margin:0;font-size:13px;line-height:1.8;overflow-wrap:anywhere}.contract-fields dd code{font-size:12px}.detail-body>.connection-list .connection-row{padding:18px 0;flex-wrap:wrap}.detail-body>.connection-list .connection-row>span{flex-basis:100%}.detail-body>.connection-list .connection-row strong{max-width:90%}#toast{position:fixed;bottom:25px;left:50%;transform:translateX(-50%);z-index:100;color:white;background:#235a45;padding:13px 20px;border-radius:8px;font-size:12px;opacity:0;pointer-events:none}#toast.visible{opacity:1}
@media(min-width:1550px){main{padding-top:48px}.hero{margin-bottom:40px}.hero-description{font-size:14px}.section-bar p{font-size:12px}.node-title{font-size:12px}.nav-link{font-size:13px}}
@media(max-width:1250px){:root{--sidebar:195px}main{padding:32px 25px 0}.topbar{padding:0 25px}.hero{gap:20px}.hero-right{align-items:flex-end}.hero-description{max-width:450px}.section-bar{padding:18px}.section-bar p{max-width:350px}.map-footer{align-items:flex-start;flex-direction:column;gap:10px}.component-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.below-grid{grid-template-columns:1fr 1fr}.journey-promo{padding:17px}.hero-right .primary{padding:11px 13px}}
@media(max-width:900px){:root{--sidebar:175px}.sidebar{padding:24px 12px}.wordmark{font-size:22px;padding:0}.nav-link{padding:11px 8px;font-size:11px;gap:8px}.nav-link .icon{width:15px}.hero{display:block}.hero-right{flex-direction:row;align-items:center;justify-content:space-between;padding-top:22px}.section-bar{flex-wrap:wrap;gap:14px}.section-bar p{max-width:100%}.hero-description{max-width:100%}.below-grid{grid-template-columns:1fr}.flow-explanation{grid-template-columns:1fr;gap:20px}.step-contract{border-left:0;border-top:1px solid var(--line);padding:16px 0 0}.lesson-grid{grid-template-columns:1fr}.page-heading h1{font-size:29px}.map-bottom>span{max-width:55%;line-height:1.6}}
@media(max-width:640px){:root{--sidebar:0px}.sidebar{position:sticky;inset:0 0 auto;width:100%;height:auto;padding:12px 16px;border-right:0;border-bottom:1px solid var(--line);display:block}.wordmark{font-size:19px;gap:8px;display:inline-flex}.brand-symbol{width:29px;height:32px;border-radius:9px}.brand-symbol .icon{width:21px}.brand-sub{font-size:7px;letter-spacing:2.4px}.workspace-label,.nav-caption,.sidebar-bottom{display:none}.sidebar nav{display:flex;gap:4px;overflow-x:auto;margin-top:12px;justify-content:space-between}.nav-link{font-size:10px;padding:9px 7px;gap:5px;white-space:nowrap;justify-content:center}.nav-link .icon{width:13px;height:13px}.topbar{height:55px;padding:0 17px}.breadcrumb{font-size:9px;gap:6px}.header-actions{gap:4px}.language{font-size:10px;padding:3px 4px}.language select{max-width:85px;font-size:10px}.header-actions>.icon-button{padding:6px}main{padding:27px 16px 0}.hero{margin-bottom:24px}h1{font-size:34px}.eyebrow{font-size:8px}.hero-description{font-size:12px}.hero-right{gap:12px;align-items:flex-start}.verified{font-size:8px;margin-top:10px;max-width:130px;line-height:1.6}.section-bar{padding:17px 14px}.section-bar h2{font-size:14px}.section-bar p{font-size:10px}.segmented{width:100%}.segmented button{flex:1}.map-bottom{padding:8px 10px;gap:10px}.map-bottom>span{font-size:8px}.map-bottom>span .icon{display:none}.map-footer{padding:14px}.graph-scaler{margin:0}.planned-note{font-size:9px}.component-grid{grid-template-columns:1fr}.directory-toolbar{flex-direction:column;align-items:stretch;gap:15px}.search-field{width:100%;max-width:100%}.page-heading h1{font-size:28px}.page-heading>p:last-child{font-size:12px}.journey-tabs{gap:6px}.journey-tabs button{font-size:10px;padding:9px 10px}.stepper{padding:15px 12px}.flow-explanation{padding:20px 16px}.flow-pagination{padding:0 16px 18px}.flow-controls .primary{font-size:10px}.flow-controls{margin-left:auto}.lesson{padding:23px}footer{font-size:8px;flex-wrap:wrap}.detail-identity{padding:22px 18px}.detail-identity h2{font-size:21px}.detail-body{padding:23px 18px}.detail-tabs{padding:0 10px}.detail-tabs button{font-size:9px;padding:13px 9px}.io-grid{grid-template-columns:1fr}.edge-endpoints{gap:8px}.endpoint{padding:11px;font-size:11px}.internal-flow.branching{grid-template-columns:1fr}.internal-flow.branching .internal-step{grid-column:1}.dialog-top{padding:14px 18px}dialog{width:96vw}.source-code{font-size:9px}}
@media(prefers-reduced-motion:no-preference){button,a{transition:background .18s,border-color .18s,box-shadow .18s,transform .22s,opacity .22s}.wire.live{animation:dash 1.2s linear infinite}.node{transition:opacity .4s,box-shadow .4s,transform .22s,border-color .4s}dialog[open]{animation:panel-in .3s cubic-bezier(.2,.8,.2,1)}dialog[open]::backdrop{animation:fade-in .25s}.page-heading,.hero{animation:rise .4s ease-out}.flow-explanation{animation:fade-in .25s}.graph-world{transition:transform .25s}#toast{transition:opacity .2s}@keyframes dash{to{stroke-dashoffset:-24}}@keyframes panel-in{from{transform:translateX(60px);opacity:0}to{transform:translateX(0);opacity:1}}@keyframes fade-in{from{opacity:0}to{opacity:1}}@keyframes rise{from{transform:translateY(8px);opacity:0}to{transform:translateY(0);opacity:1}}}

```