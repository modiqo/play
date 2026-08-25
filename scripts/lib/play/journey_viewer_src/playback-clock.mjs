export const PLAYBACK_DEPARTURE_MS = 220

function clamp(value, lower, upper) {
  return Math.max(lower, Math.min(upper, value))
}

/**
 * Advance from a recorded route position with travel first and stillness after
 * arrival. The short departure cue makes Play acknowledge the click without
 * delaying the camera for an entire site dwell.
 */
export function playbackProgress({
  from = 0,
  elapsedMs = 0,
  intervals = 1,
  travelMs = 4200,
  dwellMs = 2800,
  departureMs = PLAYBACK_DEPARTURE_MS,
} = {}) {
  const routeIntervals = Math.max(1, Math.floor(Number(intervals) || 1))
  const travel = Math.max(1, Number(travelMs) || 1)
  const dwell = Math.max(0, Number(dwellMs) || 0)
  const cue = Math.max(0, Number(departureMs) || 0)
  const start = clamp(Number(from) || 0, 0, 1)
  const startUnits = start * routeIntervals
  const startStage = Math.min(routeIntervals - 1, Math.floor(startUnits))
  const startFraction = start >= 1 ? 0 : startUnits - startStage
  const cycle = travel + dwell
  const clockOffset = startStage * cycle + startFraction * travel
  const clock = clockOffset + Math.max(0, Number(elapsedMs) - cue)
  const complete = clock >= routeIntervals * cycle
  if (complete) return {progress: 1, departing: false, complete: true}

  const stage = Math.min(routeIntervals - 1, Math.floor(clock / cycle))
  const withinStage = clock - stage * cycle
  const travelFraction = clamp(withinStage / travel, 0, 1)
  return {
    progress: clamp((stage + travelFraction) / routeIntervals, 0, 1),
    departing: Number(elapsedMs) < cue,
    complete: false,
  }
}
