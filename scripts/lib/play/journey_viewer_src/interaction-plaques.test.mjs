import assert from 'node:assert/strict'
import test from 'node:test'
import {groupInteractionPlaques} from './interaction-plaques.mjs'

const point = (sequence, operation, capability, provider = 'gmail') => ({
  sequence,
  baseX: sequence,
  baseZ: 4.35,
  record: {sequence, operation, provider, capability, effect_profile: {posture: 'read'}},
})

test('compresses contiguous interactions from the same typed capability', () => {
  const gmail = {family: 'adapter', id: 'gmail', label: 'Gmail'}
  const groups = groupInteractionPlaques([
    point(2, 'gmail.users.messages.list', gmail),
    point(3, 'gmail.users.messages.get', gmail),
    point(4, 'gmail.users.messages.get', gmail),
    point(5, 'gmail.users.messages.get', gmail),
  ])
  assert.equal(groups.length, 1)
  assert.equal(groups[0].label, '@02–@05')
  assert.equal(groups[0].count, 4)
  assert.deepEqual(groups[0].sequences, [2, 3, 4, 5])
})

test('does not combine different systems or access postures', () => {
  const groups = groupInteractionPlaques([
    point(1, 'messages.list', {family: 'adapter', id: 'gmail'}),
    point(2, 'pages.search', {family: 'adapter', id: 'notion'}, 'notion'),
    {...point(3, 'pages.update', {family: 'adapter', id: 'notion'}, 'notion'), record: {
      ...point(3, 'pages.update', {family: 'adapter', id: 'notion'}, 'notion').record,
      effect_profile: {posture: 'write'},
    }},
  ])
  assert.equal(groups.length, 3)
})

test('preserves every canonical record across bounded groups', () => {
  const capability = {family: 'adapter', id: 'gmail'}
  const points = Array.from({length: 14}, (_, index) => point(index + 1, 'messages.get', capability))
  const groups = groupInteractionPlaques(points)
  assert.deepEqual(groups.flatMap((group) => group.records), points.map((item) => item.record))
  assert.deepEqual(groups.map((group) => group.count), [6, 6, 2])
})
