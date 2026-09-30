# Recursive dependency trees

## docs-site/src/views/MapView.tsx
- docs-site/src/views/MapView.tsx
  - docs-site/src/content/load.ts
    - docs-site/content/components.json
    - docs-site/content/principles.json
    - docs-site/content/tickets.json
    - docs-site/content/ui.json
    - docs-site/src/content/types.ts
  - docs-site/src/i18n/lang.tsx
    - docs-site/src/content/types.ts (shared)
  - docs-site/src/diagram/SystemMap.tsx
    - docs-site/content/systems.json
    - docs-site/src/content/types.ts (shared)
    - docs-site/src/lib/motion.ts
    - docs-site/src/i18n/lang.tsx (shared)
    - docs-site/src/diagram/parts.tsx
      - docs-site/src/lib/motion.ts (shared)
      - docs-site/src/diagram/geometry.ts
      - docs-site/src/diagram/wrap.ts
    - docs-site/src/diagram/trunk.ts
      - docs-site/src/diagram/geometry.ts (shared)
    - docs-site/src/diagram/wrap.ts (shared)
    - docs-site/src/diagram/Plot.tsx
  - docs-site/src/diagram/CompanionList.tsx
    - docs-site/src/i18n/lang.tsx (shared)
    - docs-site/src/content/load.ts (shared)
    - docs-site/src/content/types.ts (shared)
  - docs-site/src/router/Router.tsx
    - docs-site/src/router/route.ts
  - docs-site/src/views/ContractPanel.tsx
    - docs-site/content/systems.json
    - docs-site/src/content/load.ts (shared)
    - docs-site/src/content/types.ts (shared)
    - docs-site/src/content/links.ts
      - docs-site/content/repo.json
    - docs-site/src/i18n/lang.tsx (shared)
    - docs-site/src/components/Panel.tsx
      - docs-site/src/lib/motion.ts (shared)
      - docs-site/src/i18n/lang.tsx (shared)
      - docs-site/src/content/load.ts (shared)
      - docs-site/src/router/Router.tsx (shared)
      - docs-site/src/router/route.ts (shared)
  - docs-site/src/views/OwnershipTable.tsx
    - docs-site/content/ownership.json
    - docs-site/src/content/load.ts (shared)
    - docs-site/src/content/types.ts (shared)
    - docs-site/src/content/links.ts (shared)
    - docs-site/src/i18n/lang.tsx (shared)

## docs-site/src/views/DetailView.tsx
- docs-site/src/views/DetailView.tsx
  - docs-site/src/content/load.ts
    - docs-site/content/components.json
    - docs-site/content/principles.json
    - docs-site/content/tickets.json
    - docs-site/content/ui.json
    - docs-site/src/content/types.ts
  - docs-site/src/content/links.ts
    - docs-site/content/repo.json
  - docs-site/src/i18n/lang.tsx
    - docs-site/src/content/types.ts (shared)
  - docs-site/src/diagram/Diagram.tsx
    - docs-site/src/i18n/lang.tsx (shared)
    - docs-site/src/content/types.ts (shared)
    - docs-site/src/diagram/geometry.ts
    - docs-site/src/diagram/parts.tsx
      - docs-site/src/lib/motion.ts
      - docs-site/src/diagram/geometry.ts (shared)
      - docs-site/src/diagram/wrap.ts
    - docs-site/src/diagram/CompanionList.tsx
      - docs-site/src/i18n/lang.tsx (shared)
      - docs-site/src/content/load.ts (shared)
      - docs-site/src/content/types.ts (shared)
    - docs-site/src/diagram/Plot.tsx
  - docs-site/src/components/Panel.tsx
    - docs-site/src/lib/motion.ts (shared)
    - docs-site/src/i18n/lang.tsx (shared)
    - docs-site/src/content/load.ts (shared)
    - docs-site/src/router/Router.tsx
      - docs-site/src/router/route.ts
    - docs-site/src/router/route.ts (shared)
  - docs-site/src/router/Router.tsx (shared)

## docs-site/src/views/MachineView.tsx
- docs-site/src/views/MachineView.tsx
  - docs-site/src/content/load.ts
    - docs-site/content/components.json
    - docs-site/content/principles.json
    - docs-site/content/tickets.json
    - docs-site/content/ui.json
    - docs-site/src/content/types.ts
  - docs-site/src/i18n/lang.tsx
    - docs-site/src/content/types.ts (shared)
  - docs-site/src/diagram/Machine.tsx
    - docs-site/content/machine.json
    - docs-site/src/content/load.ts (shared)
    - docs-site/src/content/types.ts (shared)
    - docs-site/src/lib/motion.ts
    - docs-site/src/i18n/lang.tsx (shared)
    - docs-site/src/diagram/trunk.ts
      - docs-site/src/diagram/geometry.ts
    - docs-site/src/diagram/parts.tsx
      - docs-site/src/lib/motion.ts (shared)
      - docs-site/src/diagram/geometry.ts (shared)
      - docs-site/src/diagram/wrap.ts
    - docs-site/src/diagram/wrap.ts (shared)
    - docs-site/src/diagram/Plot.tsx
  - docs-site/src/router/Router.tsx
    - docs-site/src/router/route.ts

## docs-site/src/views/ComponentsView.tsx
- docs-site/src/views/ComponentsView.tsx
  - docs-site/src/content/load.ts
    - docs-site/content/components.json
    - docs-site/content/principles.json
    - docs-site/content/tickets.json
    - docs-site/content/ui.json
    - docs-site/src/content/types.ts
  - docs-site/src/i18n/lang.tsx
    - docs-site/src/content/types.ts (shared)
  - docs-site/src/router/Router.tsx
    - docs-site/src/router/route.ts

## docs-site/src/views/PhasesView.tsx
- docs-site/src/views/PhasesView.tsx
  - docs-site/src/content/load.ts
    - docs-site/content/components.json
    - docs-site/content/principles.json
    - docs-site/content/tickets.json
    - docs-site/content/ui.json
    - docs-site/src/content/types.ts
  - docs-site/src/content/types.ts (shared)
  - docs-site/src/lib/motion.ts
  - docs-site/src/i18n/lang.tsx
    - docs-site/src/content/types.ts (shared)
  - docs-site/src/router/Router.tsx
    - docs-site/src/router/route.ts

## docs-site/src/views/DebtView.tsx
- docs-site/src/views/DebtView.tsx
  - docs-site/content/debt.json
  - docs-site/src/content/load.ts
    - docs-site/content/components.json
    - docs-site/content/principles.json
    - docs-site/content/tickets.json
    - docs-site/content/ui.json
    - docs-site/src/content/types.ts
  - docs-site/src/content/types.ts (shared)
  - docs-site/src/content/links.ts
    - docs-site/content/repo.json
  - docs-site/src/i18n/lang.tsx
    - docs-site/src/content/types.ts (shared)
  - docs-site/src/router/Router.tsx
    - docs-site/src/router/route.ts

## architecture-site/app.js
- architecture-site/app.js
  - architecture-site/content.js

Atlas also loads style.css and a generated snapshot.json.
