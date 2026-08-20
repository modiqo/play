const locationQuery = new URLSearchParams(location.search)
const queryToken = locationQuery.get('token') || ''
if (queryToken) sessionStorage.setItem('play-journey-token', queryToken)
export const token = queryToken || sessionStorage.getItem('play-journey-token') || ''
export const workspaceFromLocation = locationQuery.get('workspace') || ''
locationQuery.delete('token')
if (queryToken) {
  const retained = locationQuery.toString()
  history.replaceState(null, '', `${location.pathname}${retained ? `?${retained}` : ''}`)
}

export function trackWorkspaceLocation(workspace) {
  if (!workspace) return
  const next = new URL(location.href)
  next.searchParams.delete('token')
  next.searchParams.set('workspace', workspace)
  history.replaceState(null, '', `${next.pathname}?${next.searchParams}`)
}

export const api = (path, values = {}) => `${path}?${new URLSearchParams({token, ...values})}`
