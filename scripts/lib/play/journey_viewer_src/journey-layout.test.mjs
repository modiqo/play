import assert from 'node:assert/strict'
import test from 'node:test'
import {buildAtlas} from './atlas-model.js'
import {journeyCoordinates} from './journey-layout.mjs'

const chapters = [
  {id: 'intent', order: 0, kind: 'intent', title: 'Intent'},
  {id: 'effect', order: 1, kind: 'effect', title: 'Effect'},
  {id: 'evidence', order: 2, kind: 'evidence', title: 'Evidence'},
]

test('Atlas uses the same canonical vantage coordinates as Follow', () => {
  const expected = journeyCoordinates(chapters)
  const atlas = buildAtlas({chapters}, {edges: []}, {sites: {}})
  assert.deepEqual(
    atlas.sites.map((site) => site.center),
    expected.map((point) => [point.x, point.z, .42]),
  )
})

test('Atlas projects operations as chronological beads and natural thread segments', () => {
  const records = [
    {sequence: 1, tokens: 80, duration_ms: 20},
    {sequence: 2, tokens: 1600, duration_ms: 500},
    {sequence: 3, tokens: 240, duration_ms: 75},
  ]
  const atlas = buildAtlas({chapters}, {edges: []}, {sites: {intent: records}})
  assert.equal(atlas.beads.length, 3)
  assert.equal(atlas.threads.length, 2)
  assert.equal(atlas.halos.length, 3)
  assert.ok(atlas.beads[1].radius > atlas.beads[0].radius)
  assert.equal(atlas.threads[0].path.length, 15)
  assert.deepEqual(atlas.threads[0].path[0], atlas.beads[0].center)
  assert.deepEqual(atlas.threads[0].path.at(-1), atlas.beads[1].center)
})
