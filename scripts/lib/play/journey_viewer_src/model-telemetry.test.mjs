import assert from 'node:assert/strict'
import test from 'node:test'

import {
  estimatedContextProgress,
  formatModelCost,
  playbackModelTelemetry,
  recordedModelPrefix,
  summarizeModelRecords,
} from './model-telemetry.mjs'

test('summarizes embodied input/output and outcomes', () => {
  assert.deepEqual(summarizeModelRecords([
    {input_tokens: 90, output_tokens: 10, estimated_cost_usd: .001, status: 'succeeded'},
    {input_tokens: 30, output_tokens: 20, estimated_cost_usd: .002, status: 'failed'},
  ]), {
    input_tokens: 120,
    output_tokens: 30,
    cost_usd: .003,
    count: 2,
    success: 1,
    error: 1,
  })
})

test('does not invent a partial cost when one event is unpriced', () => {
  assert.equal(summarizeModelRecords([
    {input_tokens: 2, output_tokens: 1, estimated_cost_usd: .001},
    {input_tokens: 2, output_tokens: 1, estimated_cost_usd: null},
  ]).cost_usd, null)
  assert.equal(formatModelCost(null), '—')
})

test('reveals exact recorded operations and adds them to the reached journey prefix', () => {
  const sites = {
    one: [{input_tokens: 100, output_tokens: 10, estimated_cost_usd: .001, status: 'succeeded'}],
    two: [
      {input_tokens: 40, output_tokens: 4, estimated_cost_usd: .002, status: 'succeeded'},
      {input_tokens: 60, output_tokens: 6, estimated_cost_usd: .003, status: 'failed'},
    ],
  }
  assert.deepEqual(recordedModelPrefix(sites.two, 1), {
    input_tokens: 40, output_tokens: 4, cost_usd: .002, count: 1, success: 1, error: 0,
  })
  const snapshot = playbackModelTelemetry([{id: 'one'}, {id: 'two'}], sites, 1, 1)
  assert.equal(snapshot.site.input_tokens, 40)
  assert.equal(snapshot.journey.input_tokens, 140)
  assert.equal(snapshot.journey.count, 2)
})

test('counts the Play runtime in telemetry without presenting it as a site exchange', () => {
  const runtime = [
    {input_tokens: 12, output_tokens: 3, estimated_cost_usd: .001, status: 'succeeded'},
  ]
  const snapshot = playbackModelTelemetry([{id: 'intent'}], {intent: []}, 0, 0, runtime)
  assert.deepEqual(snapshot.site, {
    input_tokens: 0, output_tokens: 0, cost_usd: 0, count: 0, success: 0, error: 0,
  })
  assert.deepEqual(snapshot.journey, {
    input_tokens: 12, output_tokens: 3, cost_usd: .001, count: 1, success: 1, error: 0,
  })
})

test('estimates context-cycle progress without claiming an observed compaction', () => {
  assert.deepEqual(estimatedContextProgress(
    {input_tokens: 225, output_tokens: 75},
    {compaction_at_tokens: 240},
  ), {
    captured_tokens: 300,
    used_tokens: 60,
    remaining_tokens: 180,
    consumed_percent: 25,
    remaining_percent: 75,
    estimated_compactions: 1,
  })
})
