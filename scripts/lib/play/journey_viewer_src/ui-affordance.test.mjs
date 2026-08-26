import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'

const css = readFileSync(new URL('../journey_viewer/viewer.css', import.meta.url), 'utf8')
const app = readFileSync(new URL('./app.jsx', import.meta.url), 'utf8')
const world = readFileSync(new URL('./world.jsx', import.meta.url), 'utf8')

test('dense route landmarks keep large click targets and semantic labels', () => {
  const markers = css.match(/\.chapter-markers button \{(?<body>[\s\S]*?)\n\}/)?.groups?.body || ''
  assert.match(markers, /width: 28px/)
  assert.match(markers, /height: 28px/)
  assert.match(app, /marker-current-label/)
  assert.match(app, /marker-cluster/)
})

test('recorded exchanges expose compact non-italic request and response controls', () => {
  assert.match(world, /drive-event-flow/)
  assert.match(world, />REQ</)
  assert.match(world, />RES</)
  assert.match(world, />INSPECT</)
  assert.match(css, /\.drive-event-action > em \{[^}]*font-style: normal/)
})

test('the footer keeps archive counts out of the persistent driving controls', () => {
  const footer = app.match(/<footer>(?<body>[\s\S]*?)<\/footer>/)?.groups?.body || ''
  assert.doesNotMatch(footer, /canonical_nodes|INTERACTIONS|graph_generation/)
  assert.match(footer, /replay-track/)
  assert.match(footer, /replay-position/)
})

test('journey switching is a labelled header file picker, not a footer control', () => {
  const header = app.match(/<header>(?<body>[\s\S]*?)<\/header>/)?.groups?.body || ''
  const footer = app.match(/<footer>(?<body>[\s\S]*?)<\/footer>/)?.groups?.body || ''
  assert.match(header, /journey-picker-trigger/)
  assert.match(header, />JOURNEYS</)
  assert.doesNotMatch(footer, /JOURNEYS/)
  assert.match(app, /NEWEST FIRST/)
  assert.match(app, /journey-kind/)
})

test('the stage card carries the primary playback control', () => {
  assert.match(world, /drive-primary-play/)
  assert.match(world, /PLAY ROUTE/)
  assert.match(world, /PAUSE ROUTE/)
  assert.match(app, /onTogglePlayback=\{togglePlayback\}/)
  const control = css.match(/\.drive-primary-play \{(?<body>[\s\S]*?)\n\}/)?.groups?.body || ''
  assert.match(control, /min-height: 52px/)
  assert.match(control, /pointer-events: auto/)
})

test('the driving cluster remains shallow enough to preserve the road scene', () => {
  const dashboard = css.match(/\.drive-dashboard \{(?<body>[\s\S]*?)\n\}/)?.groups?.body || ''
  assert.match(dashboard, /min-height: 72px/)
  assert.match(dashboard, /background: transparent/)
  assert.doesNotMatch(dashboard, /border: 1px/)
  assert.match(world, /drive-dashboard-clearance/)
  assert.doesNotMatch(world, /drive-stage-instrument/)
})

test('follow mode presents a centered wheel and animated capability shifter', () => {
  assert.match(world, /drive-steering-wheel/)
  assert.match(world, /drive-capability-shifter/)
  assert.match(world, /Capability gear:/)
  assert.match(world, /ADAPTER/)
  assert.match(world, /BROWSER/)
  assert.match(world, /SHELL/)
  assert.match(css, /@keyframes drive-steering-correction/)
  assert.match(css, /transition: transform 680ms cubic-bezier/)
  assert.match(css, /\.drive-shift-option b \{[^}]*font-size: 15px/)
  assert.match(css, /\.drive-shift-option small \{[^}]*font-size: 9px/)
  assert.match(css, /prefers-reduced-motion:[\s\S]*\.drive-steering-wheel/)
})
