export function calloutIsInTransit({
  playing = false,
  travelAmount = 0,
  settleElapsedMs = Number.POSITIVE_INFINITY,
  departureThreshold = .015,
  settleMs = 420,
} = {}) {
  if (!playing) return false
  const amount = Math.max(0, Math.min(1, Number(travelAmount) || 0))
  return amount > departureThreshold || Number(settleElapsedMs) < settleMs
}
