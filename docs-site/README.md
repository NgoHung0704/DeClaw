# DeClaw architecture explorer

This React/TypeScript site explains the repository. It is not the product Web UI
planned under `ui/` for Phase 9 and does not execute document actions.

Use the Node version in `.nvmrc`, then run from this directory:

```sh
npm ci
npm run guards
npm run build
npm run dev
```

`content/` contains authored explanations, translations, source citations and
ticket relations. `scripts/gen-repo-json.mjs` generates the ignored commit metadata
used for source links. `npm run sync:snippets` refreshes quoted code; review the
result before committing. Guards check coverage, paths, quoted snippets, i18n and
cross-references; they do not establish that every prose claim matches runtime
behavior. Ticket labels include historical wording and are not a completion gate.

`dist/`, `node_modules/`, `content/repo.json` and `*.tsbuildinfo` are generated and
must stay out of Git. `.github/workflows/ci.yml` builds and publishes this site.

The separate [Atlas](../architecture-site/README.md) has an independent build and
publication workflow. See the [documentation index](../docs/README.md) for current
status, decisions and handoff guidance before using either viewer as context.
