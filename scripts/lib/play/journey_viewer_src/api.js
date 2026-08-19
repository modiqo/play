const queryToken = new URLSearchParams(location.search).get('token') || ''
if (queryToken) sessionStorage.setItem('play-journey-token', queryToken)
export const token = queryToken || sessionStorage.getItem('play-journey-token') || ''
if (token) history.replaceState(null, '', location.pathname)
export const api = (path, values = {}) => `${path}?${new URLSearchParams({token, ...values})}`

