import assert from 'node:assert/strict'
import test from 'node:test'

import {
  LIVE_WORKSPACE_REFRESH_MINIMUM_MS,
  LIVE_WORKSPACE_REFRESH_SECONDS,
  QUIET_WORKSPACE_REFRESH_SECONDS,
  liveWorkspaceRefreshActive,
  startLiveWorkspaceRefresh,
  workspaceRefreshSeconds,
} from './live-workspace-refresh.mjs'

test('a selected live workspace refreshes every five seconds for two minutes', () => {
  const lease = startLiveWorkspaceRefresh('workspace-a', 1000)

  assert.equal(lease.until - lease.startedAt, 120000)
  assert.equal(LIVE_WORKSPACE_REFRESH_MINIMUM_MS, 120000)
  assert.equal(LIVE_WORKSPACE_REFRESH_SECONDS, 5)
  assert.equal(workspaceRefreshSeconds({
    lease,
    workspace: 'workspace-a',
    storyState: 'active',
    now: lease.until,
  }), 5)
})

test('the refresh lease does not follow another workspace or a recorded exploration', () => {
  const lease = startLiveWorkspaceRefresh('workspace-a', 1000)

  assert.equal(liveWorkspaceRefreshActive({
    lease,
    workspace: 'workspace-b',
    storyState: 'active',
    now: 2000,
  }), false)
  assert.equal(liveWorkspaceRefreshActive({
    lease,
    workspace: 'workspace-a',
    storyState: 'recorded',
    now: 2000,
  }), false)
})

test('the viewer returns to its calm cadence after the minimum window', () => {
  const lease = startLiveWorkspaceRefresh('workspace-a', 1000)

  assert.equal(workspaceRefreshSeconds({
    lease,
    workspace: 'workspace-a',
    storyState: 'active',
    now: lease.until + 1,
  }), QUIET_WORKSPACE_REFRESH_SECONDS)
})
