import assert from 'node:assert/strict'
import test from 'node:test'
import {buildAtlasCityPlan, sampleAtlasCityRoute} from './atlas-city-plan.mjs'

const atlas = {
  semanticPath: [[0, 0, 0], [20, 0, 0], [20, 20, 0]],
  sites: [
    {id: 'one', center: [0, 0, 0]},
    {id: 'two', center: [20, 0, 0]},
    {id: 'three', center: [20, 20, 0]},
  ],
  bounds: {minX: 0, maxX: 20, minY: 0, maxY: 20},
}

test('builds a deterministic skyline around the canonical route', () => {
  assert.deepEqual(buildAtlasCityPlan(atlas, 'same'), buildAtlasCityPlan(atlas, 'same'))
})

test('keeps buildings clear of route and stage plazas', () => {
  const plan = buildAtlasCityPlan(atlas, 'clearance')
  assert.ok(plan.buildings.length > 20)
  for (const building of plan.buildings) {
    assert.ok(plan.sites.every((site) => Math.hypot(building.x - site.world[0], building.z - site.world[2]) >= 4.4))
  }
})

test('samples a finite forward position and heading', () => {
  const plan = buildAtlasCityPlan(atlas, 'sample')
  for (const progress of [0, .25, .5, .75, 1]) {
    const sample = sampleAtlasCityRoute(plan.route, progress)
    assert.ok(sample.position.every(Number.isFinite))
    assert.ok(sample.tangent.every(Number.isFinite))
  }
})
