function text(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function identity(record = {}) {
  const capability = record.capability || {}
  const family = text(capability.family)
  const system = text(capability.id) || text(capability.label) || text(record.provider)
  const operation = text(record.operation)
  const posture = text(record.effect_profile?.posture || record.effect || 'unknown').toLowerCase()
  // Typed capability identity is the primary grouping contract. Process records
  // without one group only when their concrete operation is identical.
  const relation = family && system
    ? `${family}:${system}:${posture}`
    : `operation:${operation}:${posture}`
  return {family: family || 'operation', system: system || operation || 'interaction', posture, relation}
}

function sequenceLabel(records) {
  const first = records[0]?.sequence
  const last = records[records.length - 1]?.sequence
  const prefix = (value) => `@${String(value).padStart(2, '0')}`
  return records.length > 1 ? `${prefix(first)}–${prefix(last)}` : prefix(first)
}

/**
 * Losslessly compress contiguous, typed interactions into floor-level plaques.
 * Records remain intact and ordered inside each plaque; this is display
 * compression only, never graph pruning.
 */
export function groupInteractionPlaques(points = [], {maximumGroupSize = 6} = {}) {
  const groups = []
  for (const point of points) {
    const record = point?.record || {}
    const typed = identity(record)
    const previous = groups.at(-1)
    const related = previous?.relation === typed.relation && previous.points.length < maximumGroupSize
    const group = related ? previous : {
      key: `${typed.relation}:${record.sequence ?? groups.length}`,
      relation: typed.relation,
      family: typed.family,
      system: typed.system,
      posture: typed.posture,
      points: [],
      records: [],
    }
    if (!related) groups.push(group)
    group.points.push(point)
    group.records.push(record)
  }
  return groups.map((group) => {
    const x = group.points.reduce((total, point) => total + Number(point?.baseX ?? point?.x ?? 0), 0) / group.points.length
    const z = Math.max(...group.points.map((point) => Number(point?.baseZ ?? point?.z ?? 0)))
    return {
      ...group,
      count: group.records.length,
      sequences: group.records.map((record) => record.sequence),
      label: sequenceLabel(group.records),
      deltaLabel: group.points[0]?.deltaLabel || 'NEXT',
      x,
      z,
    }
  })
}
