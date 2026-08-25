import assert from 'node:assert/strict'
import test from 'node:test'

import {PLAYBACK_DEPARTURE_MS, playbackProgress} from './playback-clock.mjs'

test('acknowledges departure briefly and then moves before the first dwell', () => {
  assert.deepEqual(playbackProgress({elapsedMs: 0}), {
    progress: 0,
    departing: true,
    complete: false,
  })
  assert.equal(playbackProgress({elapsedMs: PLAYBACK_DEPARTURE_MS + 100}).departing, false)
  assert.ok(playbackProgress({elapsedMs: PLAYBACK_DEPARTURE_MS + 100}).progress > 0)
})

test('holds only after arriving at a site', () => {
  const options = {intervals: 2, travelMs: 1000, dwellMs: 500, departureMs: 200}
  assert.equal(playbackProgress({...options, elapsedMs: 1200}).progress, .5)
  assert.equal(playbackProgress({...options, elapsedMs: 1450}).progress, .5)
  assert.ok(playbackProgress({...options, elapsedMs: 1800}).progress > .5)
})

test('completes after the final arrival dwell', () => {
  const result = playbackProgress({intervals: 2, travelMs: 1000, dwellMs: 500, departureMs: 200, elapsedMs: 3200})
  assert.deepEqual(result, {progress: 1, departing: false, complete: true})
})

test('resuming a partial route continues its current travel segment', () => {
  const result = playbackProgress({from: .25, intervals: 2, travelMs: 1000, dwellMs: 500, departureMs: 0, elapsedMs: 100})
  assert.equal(result.progress, .3)
})
