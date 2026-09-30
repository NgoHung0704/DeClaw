# DeClaw Atlas

An interactive, English / French / Vietnamese architecture explorer built from the DeClaw source tree. English is the default. This is a standalone replacement experience; the original `docs-site` remains available.

Live owner-private site: https://declaw-architecture-atlas.ngoanhhungbhmt2k4.chatgpt.site

Design canvas: https://superdesign.dev/teams/a77a34bb-1dee-4e15-b282-bf601cf2c568/projects/191fb8ed-f726-49f3-96dd-053d99ccbb9c

## Run

Requires Node.js 20+; no npm dependencies are needed.

```sh
cd architecture-site
npm run build
npm test
npm run dev
```

Open http://127.0.0.1:4173. Rebuild after Python source changes to refresh the read-only source snapshot.

## Content and interaction

- `content.js`: translated component responsibilities, input/output contracts, five guided journeys, and onboarding lessons.
- `app.js`: context/component views, flow playback, module search, native accessible detail dialogs, source inspection, shareable hash routes and themes.
- `style.css`: responsive layout, semantic colors, SVG connections and reduced-motion support.
- `scripts/build.mjs`: copies static assets and packages explicitly selected Python source plus module inventories. It reads the current Git commit ID but does not package environment files, credentials, client documents, or Git history.
- `dist/`: deployable static output. No backend and no AI execution.

The graph describes modules within the Python core and separate local dependencies. It does not claim a microservices deployment. Gateway, Tauri and Docker shell execution are explicitly marked as planned. Guided journeys are explanatory simulations, not execution telemetry.

The source snapshot records the repository HEAD used at build time; uncommitted Python edits, if present, are included from the working tree. Review/rebuild this snapshot with architecture changes. Module descriptions and journey semantics are authored content and require review; a passing reference test cannot prove prose semantics.

## Publishing

The site is intended for owner-private ChatGPT Sites publication. `.openai/hosting.json` records the returned project ID after creation. Publish only the static app and its curated source snapshot, never the parent repository or its secrets. Each published version must correspond to the exact source commit pushed to the Sites source repository.

The accepted hosting manifest uses `static: {"directory": "dist"}`. The publication repository in `.publish/` contains `.openai/hosting.json` and the built `dist/` assets. Package a Git archive from the pushed commit, then save and deploy that exact commit with the Sites private deployment operation. Keep deployment metadata in `.openai/deployment.json`, outside the strict hosting manifest. The credential helper reads a short-lived token without console echo and never saves it to disk or Git configuration.

Validation: five Node content/geometry/reference tests plus a Chromium interaction run covering all five journeys, three languages, source drilldown, search, context expansion, deep links, mobile layout, themes and reduced motion. Browser screenshots live in ignored `.verification/`. The deployment service confirmed publication succeeded.
