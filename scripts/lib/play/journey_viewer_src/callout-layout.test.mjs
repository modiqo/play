import assert from 'node:assert/strict'
import test from 'node:test'

import {horizontalCalloutOffsets} from './callout-layout.mjs'

test('moves a proof card right before considering the left side', () => {
  assert.deepEqual(
    horizontalCalloutOffsets({edgeX: 0, width: 400, worldCallout: true}),
    [0, 48, 96, 144, -48, -96],
  )
})

test('retains compact bidirectional candidates for interaction plaques', () => {
  assert.deepEqual(
    horizontalCalloutOffsets({edgeX: 4, worldCallout: false, direction: -1}),
    [4, -34, 42, -74],
  )
})
