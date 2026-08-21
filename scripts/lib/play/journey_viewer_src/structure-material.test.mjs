import assert from 'node:assert/strict'
import test from 'node:test'
import {material, STRUCTURE_COLORS} from './world-elements.js'

test('semantic structures use a dark blue-slate palette under scene lighting', () => {
  assert.deepEqual(STRUCTURE_COLORS, {
    pale: 0x40555c,
    soft: 0x30444b,
    dark: 0x203137,
  })

  const surface = material()
  assert.equal(surface.color.getHex(), STRUCTURE_COLORS.soft)
  assert.equal(surface.roughness, .88)
  assert.equal(surface.metalness, .035)
  assert.equal(surface.emissiveIntensity, .045)
  assert.equal(surface.dithering, true)
  surface.dispose()
})
