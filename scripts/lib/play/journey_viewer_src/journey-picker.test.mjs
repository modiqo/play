import assert from 'node:assert/strict'
import test from 'node:test'

import {journeyActivityLabel, journeyKind, journeyPickerItems} from './journey-picker.mjs'

test('orders real journeys newest first and keeps the tutorial separate at the end', () => {
  const items = journeyPickerItems([
    {id: 'tutorial', tutorial: true, created_at: '2026-08-25T12:00:00Z'},
    {id: 'older', activity_epoch: 100},
    {id: 'newer', activity_epoch: 300},
    {id: 'middle', created_at: '1970-01-01T00:03:20Z'},
  ])
  assert.deepEqual(items.map((item) => item.id), ['newer', 'middle', 'older', 'tutorial'])
})

test('uses truthful journey classification tags', () => {
  assert.equal(journeyKind({journey_mode: 'live'}), 'LIVE')
  assert.equal(journeyKind({journey_mode: 'recorded'}), 'RECORDED')
  assert.equal(journeyKind({journey_mode: 'workspace'}), 'WORKSPACE')
  assert.equal(journeyKind({tutorial: true}), 'START HERE')
})

test('formats recent activity for quick scanning', () => {
  const now = 10_000_000
  assert.equal(journeyActivityLabel({activity_epoch: now / 1000 - 40}, now), 'JUST NOW')
  assert.equal(journeyActivityLabel({activity_epoch: now / 1000 - 180}, now), '3M AGO')
  assert.equal(journeyActivityLabel({activity_epoch: now / 1000 - 7200}, now), '2H AGO')
})
