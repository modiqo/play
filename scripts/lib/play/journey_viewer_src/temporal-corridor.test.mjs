import assert from 'node:assert/strict'
import test from 'node:test'
import {layoutTemporalCorridor} from './temporal-corridor.mjs'

const at = (milliseconds) => new Date(Date.UTC(2026, 7, 19, 18, 0, 0, milliseconds)).toISOString()

test('orders canonical indexes left to right on the frontage timeline', () => {
  const layout = layoutTemporalCorridor([
    {sequence: 18, timestamp: at(900), duration_ms: 10},
    {sequence: 16, timestamp: at(0), duration_ms: 200},
    {sequence: 17, timestamp: at(300), duration_ms: 20},
  ])
  assert.equal(layout.orientation, 'frontage-timeline')
  assert.deepEqual(layout.points.map((point) => point.sequence), [16, 17, 18])
  assert.ok(layout.points[0].x < layout.points[1].x)
  assert.ok(layout.points[1].x < layout.points[2].x)
  assert.equal(layout.points[0].baseZ, layout.points[2].baseZ)
  assert.equal(layout.points[0].deltaLabel, 'START')
  assert.equal(layout.points[1].deltaLabel, '+300 ms')
})

test('clusters towers behind the timeline and uses depth only for overlap', () => {
  const layout = layoutTemporalCorridor([
    {sequence: 1, timestamp: at(0), duration_ms: 500},
    {sequence: 2, timestamp: at(100), duration_ms: 100},
    {sequence: 3, timestamp: at(700), duration_ms: 20},
  ])
  assert.deepEqual(layout.points.map((point) => point.lane), [0, 1, 0])
  assert.equal(layout.points[0].z, layout.points[2].z)
  assert.ok(layout.points[1].z < layout.points[0].z)
  assert.ok(layout.points.every((point) => point.z < point.baseZ))
})

test('falls back to stable sequence spacing when timestamps are unavailable', () => {
  const layout = layoutTemporalCorridor([
    {sequence: 3, duration_ms: 30},
    {sequence: 1, duration_ms: 10},
    {sequence: 2, duration_ms: 20},
  ])
  assert.deepEqual(layout.points.map((point) => point.sequence), [1, 2, 3])
  assert.deepEqual(layout.points.map((point) => point.lane), [0, 0, 0])
  assert.ok(layout.points[0].x < layout.points[1].x && layout.points[1].x < layout.points[2].x)
  assert.ok(layout.points.every((point) => Number.isFinite(point.x) && Number.isFinite(point.z)))
})

test('keeps long delays visible without allowing one delay to consume the frontage', () => {
  const layout = layoutTemporalCorridor([
    {sequence: 1, timestamp: at(0), duration_ms: 10},
    {sequence: 2, timestamp: at(10), duration_ms: 10},
    {sequence: 3, timestamp: '2026-08-19T18:10:00.000Z', duration_ms: 10},
  ])
  const shortStep = layout.points[1].x - layout.points[0].x
  const longStep = layout.points[2].x - layout.points[1].x
  assert.ok(longStep > shortStep)
  assert.ok(longStep < shortStep * 4)
})

test('keeps the complete canonical index set in the projection', () => {
  const records = Array.from({length: 24}, (_, index) => ({sequence: index + 1, duration_ms: index + 2}))
  const layout = layoutTemporalCorridor(records)
  assert.deepEqual(layout.points.map((point) => point.sequence), records.map((record) => record.sequence))
  assert.equal(layout.points.length, 24)
  assert.equal(layout.spine.length, 2)
  assert.ok(layout.exit.x - layout.entrance.x < 11)
})

test('keeps a small interaction set clustered at the vantage frontage', () => {
  const layout = layoutTemporalCorridor([
    {sequence: 15, duration_ms: 10},
    {sequence: 16, duration_ms: 10},
  ])
  assert.ok(layout.points[1].x - layout.points[0].x <= 1.1)
  assert.ok(Math.abs(layout.points[0].x + layout.points[1].x) < .001)
})
