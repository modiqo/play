import assert from 'node:assert/strict'
import test from 'node:test'
import {adjacentExperienceScale, defaultExperienceScale, markerScaleForExperience, storedExperienceScale} from './experience-scale.mjs'

test('defaults a compact viewport to readable large text', () => {
  assert.equal(defaultExperienceScale(1366, 768), 1.15)
  assert.equal(defaultExperienceScale(1920, 1080), 1)
})

test('accepts only supported persisted scale levels', () => {
  assert.equal(storedExperienceScale('1.3'), 1.3)
  assert.equal(storedExperienceScale('1.27'), null)
})

test('moves through scale levels without crossing the bounds', () => {
  assert.equal(adjacentExperienceScale(1.15, 1), 1.3)
  assert.equal(adjacentExperienceScale(1, -1), 1)
  assert.equal(adjacentExperienceScale(1.45, 1), 1.45)
})

test('grows world markers more gently and compensates for a short screen', () => {
  const standard = markerScaleForExperience(1.3, 1920, 1080)
  const compact = markerScaleForExperience(1.3, 1280, 720)
  assert.ok(standard > 1 && standard < 1.3)
  assert.ok(compact > standard)
  assert.ok(compact <= 1.3)
})
