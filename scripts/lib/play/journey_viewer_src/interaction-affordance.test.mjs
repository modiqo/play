import assert from 'node:assert/strict'
import test from 'node:test'

import {interactionStateLabel} from './interaction-affordance.mjs'

test('uses a known capability interface instead of unknown access posture', () => {
  assert.equal(interactionStateLabel({
    status: 'succeeded',
    effect_profile: {posture: 'unknown'},
    capability: {interface: 'cli'},
  }), 'CLI · SUCCEEDED')
})

test('recognizes a CLI operation when structured interface data is absent', () => {
  assert.equal(interactionStateLabel({operation: 'efflet CLI', status: 'succeeded'}), 'CLI · SUCCEEDED')
})

test('falls back to recorded without inventing an interface', () => {
  assert.equal(interactionStateLabel({operation: 'Rote memory', status: 'succeeded'}), 'RECORDED · SUCCEEDED')
})
