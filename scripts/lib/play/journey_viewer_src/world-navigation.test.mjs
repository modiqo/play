import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'
import {applyInteractionFocusView} from './world-navigation.js'

test('selected interactions are framed head-on from the temporal frontage', () => {
  const marker = new THREE.Vector3(4.25, 1.8, -12)
  const camera = new THREE.Vector3()
  const look = new THREE.Vector3()

  const distance = applyInteractionFocusView(marker, camera, look, {markerCount: 15})

  assert.deepEqual(look.toArray(), marker.toArray())
  assert.equal(camera.x, marker.x)
  assert.equal(camera.z, marker.z + distance)
  assert.ok(camera.y > marker.y)
  assert.ok(distance >= 9.4 && distance <= 13.4)
})
