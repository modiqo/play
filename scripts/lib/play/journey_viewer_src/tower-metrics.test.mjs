import assert from 'node:assert/strict'
import test from 'node:test'
import {towerHeight, towerWidth} from './tower-metrics.mjs'

test('tower height is determined purely by tokens', () => {
  assert.equal(towerHeight({tokens: 800, duration_ms: 5}), towerHeight({tokens: 800, duration_ms: 50000}))
  assert.ok(towerHeight({tokens: 1600}) > towerHeight({tokens: 80}))
})

test('tower width is determined by the duration footprint', () => {
  assert.equal(towerWidth({durationWidth: .72}, .3), .72)
  assert.equal(towerWidth({durationWidth: .22}, .3), .3)
})
