import assert from 'node:assert/strict'
import test from 'node:test'
import {plaqueIsVisible, temporalNeighborhood, updateMarkerAppearance} from './marker-appearance.mjs'

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

test('highlights only the canonical predecessor and successor around a selected bead', () => {
  const markers = [58, 59, 60, 61, 62, 63].map((sequence) => ({sequence}))

  const focus = temporalNeighborhood(markers, 60)

  assert.equal(focus.selectedIndex, 2)
  assert.deepEqual(focus.markerRelations, [null, 'previous', 'current', 'next', null, null])
  assert.deepEqual(focus.segmentRelations, [null, 'previous', 'next', null, null])
})

test('gives adjacent time beads less emphasis than the selected bead', () => {
  const marker = () => ({
    bead: {material: {}, scale: {setScalar(value) { this.value = value }}},
    halo: {material: {}, scale: {setScalar() {}}},
    indexRoot: {classList: classList()},
  })
  const selected = marker()
  const previous = marker()
  const next = marker()
  updateMarkerAppearance(selected, {selected: true})
  updateMarkerAppearance(previous, {temporalRelation: 'previous'})
  updateMarkerAppearance(next, {temporalRelation: 'next'})

  assert.ok(previous.bead.material.opacity < selected.bead.material.opacity)
  assert.ok(next.bead.material.opacity < selected.bead.material.opacity)
  assert.ok(previous.bead.material.opacity < next.bead.material.opacity)
  assert.equal(previous.indexRoot.classList.contains('temporal-previous'), true)
  assert.equal(next.indexRoot.classList.contains('temporal-next'), true)
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

test('reveals request and response affordances after arrival or explicit selection', () => {
  assert.equal(plaqueIsVisible({isCurrent: true, inTransit: true}), false)
  assert.equal(plaqueIsVisible({isCurrent: true, inTransit: false}), true)
  assert.equal(plaqueIsVisible({isCurrent: false, inTransit: false}), false)
  assert.equal(plaqueIsVisible({isCurrent: false, inTransit: true, selected: true}), true)
})
