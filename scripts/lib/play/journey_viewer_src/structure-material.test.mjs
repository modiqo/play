import assert from 'node:assert/strict'
import test from 'node:test'
import {material, STRUCTURE_COLORS} from './world-elements.js'

test('semantic structures use the island stone palette under scene lighting', () => {
  assert.deepEqual(STRUCTURE_COLORS, {
    pale: 0xc99a59,
    soft: 0x6f5843,
    dark: 0x263a3b,
  })

  const surface = material()
  assert.equal(surface.color.getHex(), STRUCTURE_COLORS.soft)
  assert.equal(surface.roughness, .84)
  assert.equal(surface.metalness, .025)
  assert.equal(surface.emissiveIntensity, .025)
  assert.equal(surface.dithering, true)
  assert.equal(surface.flatShading, true)
  surface.dispose()
})
