import assert from 'node:assert/strict'
import test from 'node:test'

import {capabilityJumpIndex} from './capability-navigation.mjs'

test('an active capability stays at the current situated vantage', () => {
  assert.equal(capabilityJumpIndex([0, 4, 9], 9, 0), 9)
})

test('a previously used capability opens its most recent reached vantage', () => {
  assert.equal(capabilityJumpIndex([0, 4, 9], 7, 0), 4)
})

test('a capability without a reached occurrence retains its lifecycle fallback', () => {
  assert.equal(capabilityJumpIndex([8], 3, 2), 2)
})
