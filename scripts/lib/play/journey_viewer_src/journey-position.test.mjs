import assert from 'node:assert/strict'
import test from 'node:test'
import {reconcileJourneyPosition} from './journey-position.mjs'

const story = (state, ids) => ({state, chapters: ids.map((id) => ({id}))})

test('initial active journeys start at the live head while recordings start at the beginning', () => {
  assert.equal(reconcileJourneyPosition({nextStory: story('active', ['a', 'b'])}), 1)
  assert.equal(reconcileJourneyPosition({nextStory: story('recorded', ['a', 'b'])}), 0)
})

test('a quiet refresh advances an unpinned live head to the newest call site', () => {
  assert.equal(reconcileJourneyPosition({
    previousStory: story('active', ['a', 'b']),
    nextStory: story('active', ['a', 'b', 'c']),
    replay: 1,
    quiet: true,
    followHead: true,
  }), 1)
})

test('a selected call site remains stable while the live journey grows', () => {
  assert.equal(reconcileJourneyPosition({
    previousStory: story('active', ['a', 'b']),
    nextStory: story('active', ['a', 'b', 'c']),
    replay: 1,
    selected: {siteId: 'b', sequence: 7},
    quiet: true,
  }), .5)
})

test('a frozen unselected position keeps its absolute journey stage', () => {
  assert.equal(reconcileJourneyPosition({
    previousStory: story('active', ['a', 'b', 'c']),
    nextStory: story('active', ['a', 'b', 'c', 'd']),
    replay: .5,
    quiet: true,
  }), 1 / 3)
})
