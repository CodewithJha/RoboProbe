# T-086a/b — Shared Field Notebook components

Implements FR-DSH-008 and NFR-ACC-001; issues #166 and #167.

The public exports are in `web/src/components/index.ts`. Components do not fetch data or own global
application state. Their caller supplies labels, physical values, route context and actions.

- `ConditionStrip` retains normalized values, labels, highlight indices and size from doc 13 §6;
  optional `formatted` values provide physical-unit descriptions. A Radix tooltip opens on keyboard
  focus or pointer hover. Bars clamp invalid geometry, and missing readings are named unavailable.
- `VerdictNotch` pairs PASS/FAIL/INVALID words with a circle/cross/diamond and the existing semantic
  colours. `RobustnessBar` exposes a centered ARIA meter, clamps finite values, and reports non-finite
  readings as unavailable rather than zero.
- `SpecimenTag` is a React Router link with its id, verdict and label in its accessible name. Its
  optional condition control is a sibling, avoiding nested interactive elements. Pass `to` for
  campaign-scoped mode routes; otherwise its default mode route is `/modes/:id`.
- `Spine` uses TanStack Virtual and one listbox tab stop; arrows/Home/End select a run and scroll it
  into view. The active option remains mounted for `aria-activedescendant` even outside the viewport.
- `StatTable` uses semantic table/caption/header cells, stable numeric sorting, `aria-sort`, aligned
  tabular numbers and explicit units. Above 200 rows it uses TanStack Virtual; a bounded first-paint
  window handles unmeasured viewports. A 10,000-row dataset mounts only a small row window.
- `EmptyState` shows caller-owned next-action copy and either a link or callback button.

## Component settings

`web/src/components/config.ts` is the typed configuration surface for viewport rows, overscan,
virtualisation threshold and tooltip delay. Tick/row dimensions and tooltip motion duration derive
from existing tokens; no service settings or environment variables are added. Mathematical SVG
coordinates remain local to their glyphs.

## Verification

Unit tests cover all seven components, keyboard tooltip/selection behavior, sorting stability,
bounded DOM size and unavailable values. The aggregate axe test disables the colour-contrast rule
because jsdom does not lay out CSS; token contrast is already covered by the project's theme tests.
Rendered browser and production-exclusion evidence is recorded in the PR description.

`ComponentGallery` is available only through the foundation router's `import.meta.env.DEV` gated
`/dev/components` route. It must not be exported by the production component barrel.
