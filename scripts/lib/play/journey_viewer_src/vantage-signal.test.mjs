import assert from 'node:assert/strict'
import test from 'node:test'

import {VANTAGE_SIGNAL_COLORS, vantageSignal} from './vantage-signal.mjs'

test('healthy progress is green by default', () => {
  assert.deepEqual(vantageSignal(
    {kind: 'effect', status: 'satisfied'},
    [{status: 'succeeded'}, {status: 'succeeded'}],
  ), {kind: 'healthy', color: VANTAGE_SIGNAL_COLORS.healthy})
})

test('authority gates and unobserved blockers are orange', () => {
  assert.equal(vantageSignal({kind: 'authority'}, []).kind, 'caution')
  assert.equal(vantageSignal({kind: 'blocker', status: 'failed'}, []).kind, 'caution')
})

test('a failed operation in the vantage bead cluster is red', () => {
  assert.deepEqual(vantageSignal(
    {kind: 'blocker', status: 'failed'},
    [{status: 'succeeded'}, {status: 'failed'}],
  ), {kind: 'error', color: VANTAGE_SIGNAL_COLORS.error})
})

test('a minority error rate is orange', () => {
  assert.deepEqual(vantageSignal(
    {kind: 'effect', status: 'satisfied'},
    [{status: 'succeeded'}, {status: 'succeeded'}, {status: 'succeeded'}, {status: 'failed'}],
  ), {kind: 'caution', color: VANTAGE_SIGNAL_COLORS.caution})
})

test('the signal returns to green at the next healthy vantage', () => {
  const failed = vantageSignal({kind: 'effect'}, [{status: 'failed'}])
  const recovered = vantageSignal({kind: 'recovery'}, [{status: 'succeeded'}])
  assert.equal(failed.kind, 'error')
  assert.equal(recovered.kind, 'healthy')
})
