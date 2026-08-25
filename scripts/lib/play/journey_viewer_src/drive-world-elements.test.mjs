import assert from 'node:assert/strict'
import test from 'node:test'
import {createDriveFixture} from './drive-world-elements.js'

const site = {id: 'site', x: 0, y: 0, z: 0, shoulder: 1}

function motions(kind) {
  const fixture = createDriveFixture({id: kind, kind}, site)
  const values = []
  fixture.traverse((object) => {
    if (object.userData.motion) values.push(object.userData.motion)
  })
  return values
}

test('decisions are separate drivable lanes', () => {
  assert.ok(motions('decision').filter((motion) => motion === 'decision-lane').length >= 4)
})

test('authorization is a three-lane toll gate with opening arms', () => {
  const values = motions('authority')
  assert.equal(values.filter((motion) => motion === 'toll-arm').length, 3)
  assert.equal(values.filter((motion) => motion === 'toll-signal').length, 3)
  assert.equal(values.includes('authority-bar'), false)
})

test('failure leaves by off-ramp and recovery rejoins by on-ramp', () => {
  assert.ok(motions('blocker').includes('error-off-ramp'))
  assert.ok(motions('recovery').includes('recovery-on-ramp'))
})

test('road chevrons point in the forward negative-z direction', () => {
  const fixture = createDriveFixture({id: 'effect', kind: 'effect'}, site)
  const chevron = fixture.children.find((object) => object.userData.motion === 'chevron')
  assert.ok(chevron)
  assert.ok(chevron.rotation.x < 0)
})
