const DEFAULTS = Object.freeze({
  centerX: 0,
  pointPitch: 1.05,
  maximumSpan: 9.6,
  timelineZ: 4.35,
  towerInset: .72,
  lanePitch: .72,
  minimumStep: 1,
  elasticStep: 1.35,
  elasticWindowMs: 1200,
})

function finiteNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function timestampMs(value) {
  if (!value) return null
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatDelta(deltaMs, first) {
  if (first) return 'START'
  if (!Number.isFinite(deltaMs)) return 'NEXT'
  if (deltaMs < 1000) return `+${Math.round(deltaMs)} ms`
  if (deltaMs < 60_000) return `+${(deltaMs / 1000).toFixed(deltaMs < 10_000 ? 1 : 0)} s`
  return `+${(deltaMs / 60_000).toFixed(deltaMs < 600_000 ? 1 : 0)} min`
}

function chronological(records) {
  return [...records].map((record, sourceIndex) => ({record, sourceIndex})).sort((left, right) => {
    const leftSequence = finiteNumber(left.record?.sequence, left.sourceIndex)
    const rightSequence = finiteNumber(right.record?.sequence, right.sourceIndex)
    return leftSequence - rightSequence || left.sourceIndex - right.sourceIndex
  })
}

/**
 * Project canonical interactions into a deterministic frontage timeline.
 *
 * Spatial grammar:
 * - chronology is the familiar left-to-right axis directly in front of the vantage;
 * - every canonical sequence remains visible as an @N index on that axis;
 * - towers cluster immediately behind their index instead of orbiting the landmark;
 * - only proven interval overlap creates a deeper tower lane;
 * - elapsed time stretches horizontal distance with a bounded logarithmic scale;
 * - height and appearance remain renderer-owned signals.
 *
 * This is a renderer-neutral projection of the complete interaction sequence. It
 * changes placement, never evidence retention.
 */
export function layoutTemporalCorridor(records = [], options = {}) {
  const settings = {...DEFAULTS, ...options}
  const ordered = chronological(Array.isArray(records) ? records : [])
  const laneEnds = []
  const temporal = ordered.map(({record, sourceIndex}, order) => {
    const startMs = timestampMs(record?.timestamp)
    const durationMs = Math.max(0, finiteNumber(record?.duration_ms))
    const endMs = startMs === null ? null : startMs + durationMs
    let lane = 0
    if (startMs !== null) {
      lane = laneEnds.findIndex((laneEnd) => laneEnd <= startMs)
      if (lane < 0) lane = laneEnds.length
      laneEnds[lane] = Math.max(laneEnds[lane] ?? -Infinity, endMs ?? startMs)
    }
    const previous = order > 0 ? ordered[order - 1].record : null
    const previousStart = timestampMs(previous?.timestamp)
    const deltaMs = order === 0 ? 0 : startMs !== null && previousStart !== null
      ? Math.max(0, startMs - previousStart)
      : Math.max(0, finiteNumber(previous?.duration_ms))
    const previousEnd = previousStart === null ? null : previousStart + Math.max(0, finiteNumber(previous?.duration_ms))
    const gapMs = order === 0 ? 0 : startMs !== null && previousEnd !== null ? Math.max(0, startMs - previousEnd) : deltaMs
    return {record, sourceIndex, order, startMs, endMs, durationMs, deltaMs, gapMs, lane}
  })

  const weights = temporal.slice(1).map(({deltaMs}) => {
    const elastic = Math.log1p(Math.max(0, deltaMs) / Math.max(1, settings.elasticWindowMs))
    return settings.minimumStep + Math.min(settings.elasticStep, elastic * settings.elasticStep)
  })
  const totalWeight = weights.reduce((total, weight) => total + weight, 0)
  const span = temporal.length <= 1 ? 0 : Math.min(settings.maximumSpan, Math.max(settings.pointPitch, (temporal.length - 1) * settings.pointPitch))
  const startX = settings.centerX - span / 2
  const endX = settings.centerX + span / 2
  let traversed = 0
  const points = temporal.map((entry, index) => {
    if (index > 0) traversed += weights[index - 1]
    const progress = temporal.length <= 1 ? .5 : totalWeight > 0 ? traversed / totalWeight : index / (temporal.length - 1)
    const baseX = startX + span * progress
    const baseZ = settings.timelineZ
    return {
      ...entry,
      sequence: entry.record?.sequence,
      progress,
      baseX,
      baseZ,
      normalX: 0,
      normalZ: -1,
      tangentX: 1,
      tangentZ: 0,
      x: baseX,
      z: baseZ - settings.towerInset - entry.lane * settings.lanePitch,
      tickRotation: 0,
      deltaLabel: formatDelta(entry.deltaMs, index === 0),
    }
  })

  return {
    schema: 'play.temporal-corridor/v1',
    direction: 'left-to-right',
    orientation: 'frontage-timeline',
    frontage: {z: settings.timelineZ, towerInset: settings.towerInset},
    entrance: {x: startX - .38, z: settings.timelineZ, tangentX: 1, tangentZ: 0},
    exit: {x: endX + .38, z: settings.timelineZ, tangentX: 1, tangentZ: 0},
    laneCount: Math.max(1, laneEnds.length),
    points,
    spine: [
      {x: startX - .38, z: settings.timelineZ},
      {x: endX + .38, z: settings.timelineZ},
    ],
  }
}
