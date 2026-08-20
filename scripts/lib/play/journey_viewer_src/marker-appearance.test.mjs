import assert from 'node:assert/strict'
import test from 'node:test'
import {plaqueIsVisible, updateMarkerAppearance} from './marker-appearance.mjs'

function classList() {
  const values = new Set()
  return {toggle: (name, enabled) => enabled ? values.add(name) : values.delete(name), contains: (name) => values.has(name)}
}

test('updates selected bead, halo, and embedded index', () => {
  const marker = {
    bead: {material: {}, scale: {setScalar(value) { this.value = value }}},
    halo: {material: {}, scale: {setScalar(value) { this.value = value }}},
    indexRoot: {classList: classList()},
  }
  updateMarkerAppearance(marker, {selected: true, proximity: true, pulse: .8, frozen: false})
  assert.equal(marker.bead.material.opacity, .72)
  assert.ok(marker.bead.material.emissiveIntensity > .018)
  assert.equal(marker.halo.material.opacity, 1)
  assert.ok(marker.bead.scale.value > 1)
  assert.equal(marker.indexRoot.classList.contains('selected'), true)
})

test('keeps the selected bead legible while suppressing future and unselected beads', () => {
  const marker = () => ({
    bead: {material: {}, scale: {setScalar() {}}},
    halo: {material: {}, scale: {setScalar() {}}},
    indexRoot: {classList: classList()},
  })
  const selected = marker()
  const muted = marker()
  const future = marker()
  updateMarkerAppearance(selected, {selected: true, muted: true})
  updateMarkerAppearance(muted, {proximity: true, muted: true})
  updateMarkerAppearance(future, {future: true})
  assert.equal(selected.bead.material.opacity, .72)
  assert.equal(selected.halo.material.opacity, 1)
  assert.equal(muted.bead.material.opacity, .05)
  assert.equal(muted.halo.material.opacity, .015)
  assert.equal(future.bead.material.opacity, .035)
  assert.equal(future.halo.material.opacity, .008)
  assert.equal(muted.indexRoot.classList.contains('muted'), true)
  assert.equal(future.indexRoot.classList.contains('future'), true)
})

test('does not require removed or optional marker attachments', () => {
  const marker = {bead: {material: {}, scale: {setScalar() {}}}, halo: {material: {}, scale: {setScalar() {}}}}
  assert.doesNotThrow(() => updateMarkerAppearance(marker, {proximity: true, pulse: .4}))
  assert.equal(marker.floorOperation, undefined)
})

test('tolerates a partial marker during scene replacement', () => {
  assert.doesNotThrow(() => updateMarkerAppearance({bead: {}}, {proximity: false}))
  assert.doesNotThrow(() => updateMarkerAppearance(null))
})

test('reveals an expanded evidence plaque only after explicit selection', () => {
  assert.equal(plaqueIsVisible({isCurrent: true, playing: true}), false)
  assert.equal(plaqueIsVisible({isCurrent: true, playing: false}), false)
  assert.equal(plaqueIsVisible({isCurrent: true, playing: true, frozen: true}), false)
  assert.equal(plaqueIsVisible({isCurrent: false, playing: true, selected: true}), true)
})
