import assert from 'node:assert/strict'
import test from 'node:test'

import {formatModelCost, summarizeModelRecords} from './model-telemetry.mjs'

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
