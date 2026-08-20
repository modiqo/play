import assert from 'node:assert/strict'
import test from 'node:test'

import {calloutIsInTransit} from './world-callout-transition.mjs'

test('fades the current callout throughout travel', () => {
  assert.equal(calloutIsInTransit({playing: true, travelAmount: .02, settleElapsedMs: 900}), true)
  assert.equal(calloutIsInTransit({playing: true, travelAmount: .7, settleElapsedMs: 900}), true)
})

test('holds the arriving callout hidden until the camera settles', () => {
  assert.equal(calloutIsInTransit({playing: true, travelAmount: 0, settleElapsedMs: 200}), true)
  assert.equal(calloutIsInTransit({playing: true, travelAmount: 0, settleElapsedMs: 500}), false)
})

test('never suppresses a frozen callout', () => {
  assert.equal(calloutIsInTransit({playing: false, travelAmount: .6, settleElapsedMs: 0}), false)
})
