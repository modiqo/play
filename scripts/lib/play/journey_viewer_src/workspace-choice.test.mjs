import assert from 'node:assert/strict'
import test from 'node:test'
import {chooseWorkspace} from './workspace-choice.mjs'

const workspaces = [
  {id: 'tutorial', workspace: 'start-here', tutorial: true, graph_ready: true},
  {id: 'live', workspace: 'owner-work', graph_ready: true},
]

test('defaults a first launch to Start Here', () => {
  assert.equal(chooseWorkspace(workspaces, {selectedId: 'live'}).id, 'tutorial')
})

test('an explicit URL workspace wins over the tutorial default', () => {
  assert.equal(chooseWorkspace(workspaces, {requested: 'owner-work', selectedId: 'tutorial'}).id, 'live')
})

test('an existing user selection remains stable', () => {
  assert.equal(chooseWorkspace(workspaces, {current: 'live'}).id, 'live')
})
