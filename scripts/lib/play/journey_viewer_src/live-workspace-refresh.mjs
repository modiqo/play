export const LIVE_WORKSPACE_REFRESH_SECONDS = 5
export const LIVE_WORKSPACE_REFRESH_MINIMUM_MS = 2 * 60 * 1000
export const QUIET_WORKSPACE_REFRESH_SECONDS = 10

/** Start one bounded high-frequency refresh lease for a selected live workspace. */
export function startLiveWorkspaceRefresh(workspace, now = Date.now()) {
  if (!workspace) return null
  return {
    workspace,
    startedAt: now,
    until: now + LIVE_WORKSPACE_REFRESH_MINIMUM_MS,
  }
}

/** Keep the fast cadence only for the selected active exploration and its lease. */
export function liveWorkspaceRefreshActive({lease, workspace, storyState, now = Date.now()} = {}) {
  return Boolean(
    workspace
    && storyState === 'active'
    && lease?.workspace === workspace
    && Number(lease.until) >= now,
  )
}

export function workspaceRefreshSeconds(values = {}) {
  return liveWorkspaceRefreshActive(values)
    ? LIVE_WORKSPACE_REFRESH_SECONDS
    : QUIET_WORKSPACE_REFRESH_SECONDS
}
