/**
 * Visor chip layout, renderer independent.
 *
 * Each recorded exchange at the current site becomes one chip docked on the
 * windshield visor. The model decides order, slot geometry, colour family,
 * hazard state, and the approach animation, so the React layer only paints.
 */

export const FAMILY_TONES = Object.freeze({
  adapter: {id: 'adapter', label: 'ADAPTER', hue: 196},
  browser: {id: 'browser', label: 'BROWSER', hue: 36},
  proc: {id: 'shell', label: 'SHELL', hue: 142},
  rote: {id: 'rote', label: 'ROTE', hue: 268},
})
export const UNKNOWN_TONE = Object.freeze({id: 'unknown', label: 'TOOL', hue: 205})
export const CHIP_WIDTH = 168
export const CHIP_GAP = 14
export const MAX_DOCKED = 6

export function chipTone(record) {
  const family = record?.capability?.family
  if (family && Object.hasOwn(FAMILY_TONES, family)) return FAMILY_TONES[family]
  const modality = record?.modality
  if (modality === 'drive') return FAMILY_TONES.browser
  if (modality === 'shell') return FAMILY_TONES.proc
  if (modality === 'call') return FAMILY_TONES.adapter
  return UNKNOWN_TONE
}

export function chipPosture(record) {
  const profile = record?.effect_profile || {}
  const posture = String(profile.posture || record?.effect || 'unknown').toLowerCase()
  const destructive = profile.destructive === true
  return {
    posture,
    destructive,
    hazard: destructive || posture === 'destructive',
    writes: posture === 'write' || posture === 'mutate' || destructive,
  }
}

export function chipStatus(record) {
  const status = String(record?.status || 'unknown').toLowerCase()
  if (status === 'succeeded' || status === 'ok' || status === 'success') return 'ok'
  if (status === 'failed' || status === 'error' || status === 'errored') return 'error'
  if (status === 'running' || status === 'pending' || status === 'active') return 'live'
  return 'unknown'
}

/** Latency arc sweep in degrees, log scaled so 50 ms and 5 s both read. */
export function latencySweepDeg(durationMs) {
  const ms = Math.max(0, Number(durationMs) || 0)
  if (ms === 0) return 0
  const sweep = (Math.log10(ms + 1) / Math.log10(60_001)) * 300
  return Math.max(6, Math.min(300, sweep))
}

/** Token bar fill, relative to the largest exchange at the site. */
export function tokenShare(record, records) {
  const own = Math.max(0, Number(record?.tokens) || 0)
  const peak = Math.max(1, ...records.map((item) => Math.max(0, Number(item?.tokens) || 0)))
  return own / peak
}

/** Packet travel time for the REQ→RES animation, bounded so it always reads. */
export function exchangeFlowMs(durationMs) {
  const ms = Math.max(0, Number(durationMs) || 0)
  return Math.round(Math.max(420, Math.min(2600, 420 + Math.log10(ms + 1) * 520)))
}

/**
 * Dock geometry. Chips centre on the visor; when more exchanges exist than
 * fit, the selected one is always kept in the docked window.
 */
export function visorChips(records = [], {viewportWidth = 1280, selectedSequence = null} = {}) {
  const ordered = [...records].sort((a, b) => Number(a.sequence) - Number(b.sequence))
  const capacity = Math.max(1, Math.min(MAX_DOCKED, Math.floor((viewportWidth * .62 + CHIP_GAP) / (CHIP_WIDTH + CHIP_GAP))))
  let start = 0
  const selectedIndex = ordered.findIndex((item) => item.sequence === selectedSequence)
  if (ordered.length > capacity) {
    if (selectedIndex >= 0) start = Math.max(0, Math.min(ordered.length - capacity, selectedIndex - Math.floor(capacity / 2)))
  }
  const docked = ordered.slice(start, start + capacity)
  const span = docked.length * CHIP_WIDTH + Math.max(0, docked.length - 1) * CHIP_GAP
  const chips = docked.map((record, index) => {
    const tone = chipTone(record)
    const posture = chipPosture(record)
    return {
      sequence: record.sequence,
      index: start + index,
      ordinal: start + index + 1,
      x: -span / 2 + index * (CHIP_WIDTH + CHIP_GAP),
      width: CHIP_WIDTH,
      label: record.capability?.label || record.operation || 'exchange',
      operation: record.operation || '',
      tone,
      posture,
      status: chipStatus(record),
      latencySweep: latencySweepDeg(record.duration_ms),
      tokenShare: tokenShare(record, ordered),
      selected: record.sequence === selectedSequence,
    }
  })
  return {
    chips,
    total: ordered.length,
    hiddenBefore: start,
    hiddenAfter: Math.max(0, ordered.length - start - docked.length),
    capacity,
  }
}

/** Sequence to select after a keyboard step; wraps at both ends. */
export function stepSequence(records = [], selectedSequence, direction) {
  const ordered = [...records].sort((a, b) => Number(a.sequence) - Number(b.sequence))
  if (!ordered.length) return null
  const index = ordered.findIndex((item) => item.sequence === selectedSequence)
  if (index < 0) return direction < 0 ? ordered.at(-1).sequence : ordered[0].sequence
  return ordered[(index + direction + ordered.length) % ordered.length].sequence
}

/**
 * Approach state for chips as the route nears a site: 0 is hidden on the
 * horizon, 1 is fully docked. `distance` is route progress until the site.
 */
export function approachState(distance) {
  const d = Number(distance)
  if (!Number.isFinite(d)) return 1
  if (d <= 0) return 1
  if (d >= .55) return 0
  const t = 1 - d / .55
  return t * t * (3 - 2 * t)
}
