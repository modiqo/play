import assert from 'node:assert/strict'
import test from 'node:test'
import {plaqueIsVisible, updateMarkerAppearance} from './marker-appearance.mjs'

test('updates current tower and edge materials', () => {
  const marker = {
    tower: {material: {}, scale: {y: 0}},
    edge: {material: {}},
  }
  updateMarkerAppearance(marker, {selected: true, proximity: true, pulse: .8, frozen: false})
  assert.equal(marker.tower.material.opacity, .52)
  assert.ok(marker.tower.material.emissiveIntensity > .025)
  assert.ok(marker.edge.material.opacity === 1)
  assert.ok(marker.tower.scale.y > 1)
})

test('does not require removed or optional marker attachments', () => {
  const marker = {tower: {material: {}, scale: {y: 1}}, edge: {material: {}}}
  assert.doesNotThrow(() => updateMarkerAppearance(marker, {proximity: true, pulse: .4}))
  assert.equal(marker.floorOperation, undefined)
})

test('tolerates a partial marker during scene replacement', () => {
  assert.doesNotThrow(() => updateMarkerAppearance({tower: {}}, {proximity: false}))
  assert.doesNotThrow(() => updateMarkerAppearance(null))
})

test('reveals evidence plaques only at a settled vantage or explicit selection', () => {
  assert.equal(plaqueIsVisible({isCurrent: true, playing: true}), false)
  assert.equal(plaqueIsVisible({isCurrent: true, playing: false}), true)
  assert.equal(plaqueIsVisible({isCurrent: true, playing: true, frozen: true}), true)
  assert.equal(plaqueIsVisible({isCurrent: false, playing: true, selected: true}), true)
})
