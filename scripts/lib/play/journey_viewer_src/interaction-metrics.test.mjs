import assert from 'node:assert/strict'
import test from 'node:test'
import {interactionDurationArc, interactionRadius} from './interaction-metrics.mjs'

test('bead volume is determined purely by tokens', () => {
  assert.equal(interactionRadius({tokens: 800, duration_ms: 5}), interactionRadius({tokens: 800, duration_ms: 50000}))
  assert.ok(interactionRadius({tokens: 1600}) > interactionRadius({tokens: 80}))
})

test('halo sweep is determined by the duration footprint', () => {
  assert.ok(interactionDurationArc({durationWidth: .72}) > interactionDurationArc({durationWidth: .3}))
  assert.equal(interactionDurationArc({durationWidth: .72, tokens: 1}), interactionDurationArc({durationWidth: .72, tokens: 9000}))
})
