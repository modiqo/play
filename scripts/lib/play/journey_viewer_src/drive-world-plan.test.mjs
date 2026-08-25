import assert from 'node:assert/strict'
import test from 'node:test'
import {buildDriveWorldPlan, sampleDriveRoute} from './drive-world-plan.mjs'

const chapters = [
  {id: 'intent', kind: 'intent'},
  {id: 'decision', kind: 'decision'},
  {id: 'capability', kind: 'capability'},
  {id: 'authority', kind: 'authority'},
]

test('builds the same road for the same Play', () => {
  const first = buildDriveWorldPlan({journey_key: 'same', chapters})
  const second = buildDriveWorldPlan({journey_key: 'same', chapters})
  assert.deepEqual(first, second)
})

test('keeps stages ordered with driving clearance', () => {
  const plan = buildDriveWorldPlan({journey_key: 'ordered', chapters})
  plan.sites.slice(1).forEach((site, index) => {
    assert.ok(site.z < plan.sites[index].z)
    assert.ok(Math.hypot(site.x - plan.sites[index].x, site.z - plan.sites[index].z) >= 20)
  })
})

test('samples a finite forward heading at every stage', () => {
  const plan = buildDriveWorldPlan({journey_key: 'heading', chapters})
  plan.sites.forEach((_site, index) => {
    const sample = sampleDriveRoute(plan, index)
    assert.ok([sample.x, sample.y, sample.z, sample.tangent.x, sample.tangent.z].every(Number.isFinite))
    assert.ok(sample.tangent.z <= 0)
  })
})
