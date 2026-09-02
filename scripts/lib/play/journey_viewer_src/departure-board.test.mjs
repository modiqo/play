import assert from 'node:assert/strict'
import test from 'node:test'
import {boardAvailability, boardFacts, boardSectionFor, boardSections, departureCountdown, nextJourneys, siteLadder} from './departure-board.mjs'

const now = Date.parse('2026-09-02T20:00:00Z')
const item = (id, extra = {}) => ({id, intent: id, graph_ready: true, projectable: true, workspace_available: true, nodes: 4, edges: 3, commands: 2, activity_epoch: now / 1000 - 60, ...extra})

test('items land in live, recorded, workspace, or tutorial sections', () => {
  assert.equal(boardSectionFor({journey_mode: 'live'}), 'live')
  assert.equal(boardSectionFor({journey_mode: 'workspace'}), 'workspace')
  assert.equal(boardSectionFor({journey_mode: 'recorded'}), 'recorded')
  assert.equal(boardSectionFor({tutorial: true, journey_mode: 'tutorial'}), 'tutorial')
})

test('sections keep board order, drop empties, and sort newest first inside', () => {
  const sections = boardSections([
    item('old', {activity_epoch: now / 1000 - 7200}),
    item('tutorial', {tutorial: true, journey_mode: 'tutorial'}),
    item('new', {activity_epoch: now / 1000 - 10}),
    item('live', {journey_mode: 'live', active_recently: true}),
  ])
  assert.deepEqual(sections.map((section) => section.id), ['live', 'recorded', 'tutorial'])
  assert.deepEqual(sections[1].items.map((entry) => entry.id), ['new', 'old'])
})

test('availability distinguishes drivable, buildable, and dead journeys', () => {
  assert.deepEqual(boardAvailability({graph_ready: true}), {ready: true, label: 'DRIVE'})
  assert.deepEqual(boardAvailability({projectable: true}), {ready: true, label: 'BUILD MAP · DRIVE'})
  assert.deepEqual(boardAvailability({workspace_available: true}), {ready: false, label: 'NO PLAY JOURNEY'})
  assert.deepEqual(boardAvailability({}), {ready: false, label: 'NO EVIDENCE'})
})

test('facts carry counts, kind, recency, and live state', () => {
  const facts = boardFacts(item('x', {journey_mode: 'live', active_recently: true}), now)
  assert.equal(facts.kind, 'LIVE')
  assert.equal(facts.activity, '1M AGO')
  assert.equal(facts.sites, 4)
  assert.equal(facts.exchanges, 2)
  assert.equal(facts.live, true)
  assert.equal(facts.ready, true)
})

test('the site ladder caps what it draws and reports the overflow honestly', () => {
  assert.deepEqual(siteLadder(5), {shown: 5, overflow: 0})
  assert.deepEqual(siteLadder(40), {shown: 14, overflow: 26})
  assert.deepEqual(siteLadder(0), {shown: 0, overflow: 0})
})

test('next journeys offer live first, skip the current one, and end with the tutorial', () => {
  const next = nextJourneys([
    item('current'),
    item('tutorial', {tutorial: true, journey_mode: 'tutorial'}),
    item('live', {journey_mode: 'live'}),
    item('dead', {graph_ready: false, projectable: false}),
    item('recent'),
  ], 'current', 3)
  assert.deepEqual(next.map((entry) => entry.id), ['live', 'recent', 'tutorial'])
})

test('a live journey being tracked departs without a countdown', () => {
  assert.equal(departureCountdown({live: true, tracking: true}), 0)
  assert.equal(departureCountdown({live: true, tracking: false}), 3)
  assert.equal(departureCountdown({}), 3)
})
