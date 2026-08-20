import assert from 'node:assert/strict'
import test from 'node:test'
import {journeyVisibilityWindow, reconcileJourneyPosition} from './journey-position.mjs'

const story = (state, ids) => ({state, chapters: ids.map((id) => ({id}))})

test('every selected journey starts at the beginning', () => {
  assert.equal(reconcileJourneyPosition({nextStory: story('active', ['a', 'b'])}), 0)
  assert.equal(reconcileJourneyPosition({nextStory: story('recorded', ['a', 'b'])}), 0)
})

test('an explicit live-head refresh advances from any unpinned position', () => {
  assert.equal(reconcileJourneyPosition({
    previousStory: story('active', ['a', 'b']),
    nextStory: story('active', ['a', 'b', 'c']),
    replay: 0,
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

test('long journeys retain only nearby history and one future preview', () => {
  assert.deepEqual(journeyVisibilityWindow(47, 32), {start: 28, end: 33})
  assert.deepEqual(journeyVisibilityWindow(12, 8), {start: 0, end: 9})
})
