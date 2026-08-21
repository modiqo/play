import assert from 'node:assert/strict'
import test from 'node:test'
import {adaptiveRenderPixelRatio, COMPOSER_SAMPLES} from './render-quality.mjs'

test('uses full Retina density on a compact journey viewport', () => {
  assert.equal(adaptiveRenderPixelRatio(2, 1366, 768), 2)
  assert.equal(COMPOSER_SAMPLES, 4)
})

test('caps excessive device density at two', () => {
  assert.equal(adaptiveRenderPixelRatio(3, 1280, 720), 2)
})

test('reduces density when a large canvas would exceed the backing-pixel budget', () => {
  const ratio = adaptiveRenderPixelRatio(2, 2560, 1440)
  assert.ok(ratio > 1 && ratio < 1.3)
  assert.ok(2560 * 1440 * ratio * ratio <= 5_500_001)
})
