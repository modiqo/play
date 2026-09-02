import assert from 'node:assert/strict'
import test from 'node:test'
import {
  DIAL_DETENTS, WHEEL_LIMIT_DEG, dampAngle, detentEase, dialAngleForGear,
  headingDeltaDeg, wheelAngleFromTangents, wheelMicroCorrectionDeg,
} from './steering-model.mjs'

test('a straight road leaves the wheel centred', () => {
  const ahead = {x: 0, z: -1}
  assert.equal(headingDeltaDeg(ahead, ahead), 0)
  assert.equal(wheelAngleFromTangents(ahead, ahead), 0)
})

test('a right-hand bend turns the wheel clockwise and a left-hand bend anticlockwise', () => {
  const ahead = {x: 0, z: -1}
  const right = {x: Math.sin(10 * Math.PI / 180), z: -Math.cos(10 * Math.PI / 180)}
  const left = {x: -right.x, z: right.z}
  assert.ok(wheelAngleFromTangents(ahead, right) > 0)
  assert.ok(wheelAngleFromTangents(ahead, left) < 0)
  assert.ok(Math.abs(wheelAngleFromTangents(ahead, right) - 32) < 1)
})

test('wheel angle is clamped to a plausible hand movement', () => {
  const ahead = {x: 0, z: -1}
  const hairpin = {x: 1, z: 0}
  assert.equal(wheelAngleFromTangents(ahead, hairpin), WHEEL_LIMIT_DEG)
  assert.equal(wheelAngleFromTangents(hairpin, ahead), -WHEEL_LIMIT_DEG)
})

test('heading delta wraps across the -Z seam', () => {
  const a = {x: -0.01, z: 1}
  const b = {x: 0.01, z: 1}
  assert.ok(Math.abs(headingDeltaDeg(a, b)) < 2)
})

test('damping converges monotonically and never overshoots', () => {
  let angle = 0
  let previous = 0
  for (let step = 0; step < 60; step += 1) {
    angle = dampAngle(angle, 40, 1 / 60, 6)
    assert.ok(angle >= previous && angle <= 40)
    previous = angle
  }
  assert.ok(angle > 39)
  assert.equal(dampAngle(10, 40, 0), 10)
})

test('micro corrections exist only while moving and stay within two degrees', () => {
  assert.equal(wheelMicroCorrectionDeg(3.2, false), 0)
  for (let t = 0; t < 30; t += 0.37) assert.ok(Math.abs(wheelMicroCorrectionDeg(t, true)) <= 2.2)
})

test('dial detents map gears and neutral rests at the centre', () => {
  assert.equal(dialAngleForGear('call'), DIAL_DETENTS.call)
  assert.equal(dialAngleForGear('shell'), DIAL_DETENTS.shell)
  assert.equal(dialAngleForGear(''), DIAL_DETENTS.drive)
  assert.equal(dialAngleForGear(undefined), DIAL_DETENTS.drive)
})

test('detent easing starts at rest, overshoots once, and settles at one', () => {
  assert.equal(detentEase(0), 0)
  assert.equal(detentEase(1), 1)
  const peak = Math.max(...Array.from({length: 50}, (_, i) => detentEase(i / 49)))
  assert.ok(peak > 1 && peak < 1.4)
})
