import assert from 'node:assert/strict'
import test from 'node:test'
import {WORLD_MODEL_KINDS, worldSpec} from './world-vocabulary.js'

test('every world-model primitive carries a concrete example', () => {
  assert.equal(WORLD_MODEL_KINDS.length, 14)
  for (const kind of WORLD_MODEL_KINDS) {
    assert.ok(worldSpec(kind).example?.length > 12, `${kind} needs an example`)
  }
})

test('the reference carries one Notion-page example across the model', () => {
  assert.match(worldSpec('intent').example, /Notion/i)
  assert.match(worldSpec('decision').example, /MCP.*browser.*cli/i)
  assert.match(worldSpec('artifact').example, /Notion page URL/i)
})
