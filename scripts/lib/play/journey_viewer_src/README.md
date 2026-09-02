# Journey viewer architecture

The browser bundle has one composition root and six behavior boundaries:

- `main.jsx` mounts the application.
- `app.jsx` composes modes, panels, and the active renderer.
- `use-journey-runtime.js` owns workspace loading, live snapshots, evidence fetches, and replay state.
- `semantics.js`, `format.js`, and `api.js` contain shared vocabulary and pure infrastructure.
- `atlas-model.js` preserves the canonical stage and evidence projection. `atlas-city-plan.mjs` deterministically places a navigable skyline around that route, and `atlas.jsx` renders the city, route, position marker, and pickable evidence in Three.js.
- `temporal-corridor.mjs` remains the renderer-independent chronology model used by Atlas.
- `drive-world-plan.mjs` projects every stage onto one deterministic road. `drive-world-elements.js` builds lane geometry, route lighting, semantic road infrastructure, and constant-sized exchange markers. `world.jsx` owns the stable chase camera, scene lifecycle, and fixed teaching HUD.
- `panels.jsx` contains explanatory overlays and frozen-vantage controls.
- `steering-model.mjs` turns route tangents into wheel angle and gears into dial detents; `cockpit-elements.js` builds the procedural wheel, dial, dash, and visor glass as a child of the camera; `render-quality.mjs` picks the GPU tier that gates refractive glass and bloom.
- `visor-layout.mjs` docks recorded exchanges as chips and `exchange-tree.mjs` projects redacted payloads into foldable rows; `visor.jsx` paints chips, tethers to lane beads, and the unfolded request and response pane.

Keep data projection independent of rendering. New semantic categories belong in `semantics.js`; new spatial rules belong in a pure model such as `temporal-corridor.mjs`; renderer-specific geometry belongs in the relevant elements module. Network and playback changes belong in the runtime hook. `app.jsx` should remain declarative.

Build the checked-in browser artifact with `npm run build:journey-viewer`, then synchronize the plugin payload with `./scripts/bin/package-plugin`.
