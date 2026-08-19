# Journey viewer architecture

The browser bundle has one composition root and six behavior boundaries:

- `main.jsx` mounts the application.
- `app.jsx` composes modes, panels, and the active renderer.
- `use-journey-runtime.js` owns workspace loading, live snapshots, evidence fetches, and replay state.
- `semantics.js`, `format.js`, and `api.js` contain shared vocabulary and pure infrastructure.
- `atlas-model.js` deterministically projects a journey into atlas geometry; `atlas.jsx` renders it with Deck.gl.
- `world-elements.js` builds semantic landmarks and callouts; `world-navigation.js` owns frozen-vantage input and camera math; `world.jsx` owns scene lifecycle and the Three.js render loop.
- `panels.jsx` contains explanatory overlays and frozen-vantage controls.

Keep data projection independent of rendering. New semantic categories belong in `semantics.js`; new geometry belongs in the relevant model/elements module; network and playback changes belong in the runtime hook. `app.jsx` should remain declarative.

Build the checked-in browser artifact with `npm run build:journey-viewer`, then synchronize the plugin payload with `./scripts/bin/package-plugin`.
