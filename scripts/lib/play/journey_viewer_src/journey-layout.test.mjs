import assert from 'node:assert/strict'
import test from 'node:test'
import {buildAtlas} from './atlas-model.js'
import {journeyCoordinates} from './journey-layout.mjs'

const chapters = [
  {id: 'intent', order: 0, kind: 'intent', title: 'Intent'},
  {id: 'effect', order: 1, kind: 'effect', title: 'Effect'},
  {id: 'evidence', order: 2, kind: 'evidence', title: 'Evidence'},
]

test('Follow coordinates preserve one ordered embodied route', () => {
  const coordinates = journeyCoordinates(chapters)
  assert.equal(Math.abs(coordinates[0].z), 0)
  assert.equal(coordinates[1].z, -21)
  assert.equal(coordinates[2].z, -42)
})

test('Atlas compacts long journeys into a serpentine terrain without reordering sites', () => {
  const denseChapters = Array.from({length: 24}, (_, order) => ({
    id: `site-${order}`, order, kind: 'phase', title: `Site ${order}`,
  }))
  const atlas = buildAtlas({chapters: denseChapters}, {sites: {}})
  assert.equal(atlas.sites.length, denseChapters.length)
  assert.ok(new Set(atlas.sites.map((site) => site.row)).size > 1)
  assert.deepEqual(atlas.sites.map((site) => site.id), denseChapters.map((site) => site.id))
  assert.ok(atlas.bounds.maxY - atlas.bounds.minY < 200)
})

test('Atlas projects operations as chronological beads and natural thread segments', () => {
  const records = [
    {sequence: 1, tokens: 80, duration_ms: 20},
    {sequence: 2, tokens: 1600, duration_ms: 500},
    {sequence: 3, tokens: 240, duration_ms: 75},
  ]
  const atlas = buildAtlas({chapters}, {sites: {intent: records}})
  assert.equal(atlas.beads.length, 3)
  assert.equal(atlas.threads.length, 2)
  assert.equal(atlas.halos.length, 3)
  assert.ok(atlas.beads[1].radius > atlas.beads[0].radius)
  assert.equal(atlas.threads[0].path.length, 15)
  assert.deepEqual(atlas.threads[0].path[0], atlas.beads[0].center)
  assert.deepEqual(atlas.threads[0].path.at(-1), atlas.beads[1].center)
})
