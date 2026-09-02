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

test('recorded exchanges dock on the windshield visor with request and response evidence', () => {
  const visor = readFileSync(new URL('./visor.jsx', import.meta.url), 'utf8')
  assert.match(world, /<Visor /)
  assert.doesNotMatch(world, /drive-events/)
  assert.match(visor, /hud-tag/)
  assert.match(visor, /hud-tethers/)
  assert.match(visor, /hud-reticle/)
  assert.match(visor, /title="REQUEST"/)
  assert.match(visor, /title="RESPONSE"/)
  assert.match(visor, /hud-pane-gauges/)
  assert.match(visor, /event\.key === 'Escape'/)
  assert.match(css, /\.hud-tag \{[\s\S]*?pointer-events: auto/)
  assert.match(css, /\.hud-pane \{[\s\S]*?pointer-events: auto/)
  assert.match(css, /--flow-ms/)
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

test('follow mode drives a scene-built cockpit that steers by the road', () => {
  const cockpit = readFileSync(new URL('./cockpit-elements.js', import.meta.url), 'utf8')
  assert.match(world, /createCockpit\(renderer/)
  assert.match(world, /camera\.add\(cockpit\)/)
  assert.match(world, /wheelAngleFromTangents\(direction, aheadTangent\)/)
  assert.match(world, /dialAngleForGear\(gearRef\.current\)/)
  assert.doesNotMatch(world, /drive-steering-wheel|drive-capability-shifter/)
  assert.match(cockpit, /TorusGeometry/)
  assert.match(cockpit, /MeshPhysicalMaterial/)
  assert.match(cockpit, /RoomEnvironment/)
  assert.match(cockpit, /knurl/)
  assert.match(cockpit, /transmission/)
  assert.match(cockpit, /dial-label-/)
  assert.doesNotMatch(world, /drive-gear-readout/)
  assert.match(cockpit, /'ADAPTER'/)
  assert.match(cockpit, /'BROWSER'/)
  assert.match(cockpit, /'SHELL'/)
  assert.match(css, /prefers-reduced-motion:[\s\S]*\.hud-tag/)
})
