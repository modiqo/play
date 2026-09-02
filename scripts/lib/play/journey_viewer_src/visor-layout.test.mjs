import assert from 'node:assert/strict'
import test from 'node:test'
import {
  CHIP_GAP, CHIP_WIDTH, FAMILY_TONES, UNKNOWN_TONE, approachState, chipPosture, chipStatus,
  chipTone, exchangeFlowMs, latencySweepDeg, stepSequence, tokenShare, visorChips,
} from './visor-layout.mjs'

const record = (sequence, extra = {}) => ({sequence, operation: `op-${sequence}`, status: 'succeeded', duration_ms: 120, tokens: 100, ...extra})

test('tone follows capability family, then modality, then unknown', () => {
  assert.equal(chipTone({capability: {family: 'browser'}}), FAMILY_TONES.browser)
  assert.equal(chipTone({modality: 'shell'}), FAMILY_TONES.proc)
  assert.equal(chipTone({modality: 'call'}), FAMILY_TONES.adapter)
  assert.equal(chipTone({}), UNKNOWN_TONE)
})

test('posture marks destructive writes as hazards', () => {
  assert.deepEqual(chipPosture({effect_profile: {posture: 'write', destructive: true}}), {posture: 'write', destructive: true, hazard: true, writes: true})
  assert.equal(chipPosture({effect_profile: {posture: 'read'}}).hazard, false)
  assert.equal(chipPosture({effect: 'read'}).posture, 'read')
})

test('status collapses to ok, error, live, or unknown', () => {
  assert.equal(chipStatus({status: 'ok'}), 'ok')
  assert.equal(chipStatus({status: 'failed'}), 'error')
  assert.equal(chipStatus({status: 'running'}), 'live')
  assert.equal(chipStatus({}), 'unknown')
})

test('latency sweep is log scaled and bounded', () => {
  assert.equal(latencySweepDeg(0), 0)
  assert.ok(latencySweepDeg(50) > 6 && latencySweepDeg(50) < latencySweepDeg(5000))
  assert.equal(latencySweepDeg(10_000_000), 300)
})

test('token share is relative to the largest exchange at the site', () => {
  const records = [record(1, {tokens: 50}), record(2, {tokens: 200})]
  assert.equal(tokenShare(records[0], records), .25)
  assert.equal(tokenShare(records[1], records), 1)
  assert.equal(tokenShare({tokens: 0}, []), 0)
})

test('packet flow time always reads and never drags', () => {
  assert.equal(exchangeFlowMs(0), 420)
  assert.ok(exchangeFlowMs(300) > 420)
  assert.equal(exchangeFlowMs(1e9), 2600)
})

test('chips dock centred in sequence order with stable slot geometry', () => {
  const layout = visorChips([record(3), record(1), record(2)], {viewportWidth: 1600})
  assert.deepEqual(layout.chips.map((chip) => chip.sequence), [1, 2, 3])
  assert.deepEqual(layout.chips.map((chip) => chip.ordinal), [1, 2, 3])
  const span = 3 * CHIP_WIDTH + 2 * CHIP_GAP
  assert.equal(layout.chips[0].x, -span / 2)
  assert.equal(layout.chips[2].x, -span / 2 + 2 * (CHIP_WIDTH + CHIP_GAP))
  assert.equal(layout.hiddenBefore + layout.hiddenAfter, 0)
})

test('an overflowing site keeps the selected chip inside the docked window', () => {
  const records = Array.from({length: 12}, (_, i) => record(i + 1))
  const layout = visorChips(records, {viewportWidth: 1280, selectedSequence: 11})
  assert.ok(layout.capacity < 12)
  assert.ok(layout.chips.some((chip) => chip.sequence === 11 && chip.selected))
  assert.equal(layout.total, 12)
  assert.equal(layout.hiddenBefore + layout.chips.length + layout.hiddenAfter, 12)
})

test('keyboard stepping wraps and starts from the nearest end', () => {
  const records = [record(1), record(2), record(3)]
  assert.equal(stepSequence(records, null, 1), 1)
  assert.equal(stepSequence(records, null, -1), 3)
  assert.equal(stepSequence(records, 3, 1), 1)
  assert.equal(stepSequence(records, 1, -1), 3)
  assert.equal(stepSequence([], 1, 1), null)
})

test('approach eases from the horizon to the dock', () => {
  assert.equal(approachState(1), 0)
  assert.equal(approachState(0), 1)
  assert.equal(approachState(-1), 1)
  const mid = approachState(.275)
  assert.ok(mid > .4 && mid < .6)
  assert.equal(approachState(Number.NaN), 1)
})
