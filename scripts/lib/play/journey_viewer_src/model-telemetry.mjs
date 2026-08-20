export function summarizeModelRecords(records = []) {
  const priced = records.filter((record) => Number.isFinite(record.estimated_cost_usd))
  return {
    input_tokens: records.reduce((sum, record) => sum + Number(record.input_tokens || 0), 0),
    output_tokens: records.reduce((sum, record) => sum + Number(record.output_tokens || 0), 0),
    cost_usd: priced.length === records.length
      ? priced.reduce((sum, record) => sum + Number(record.estimated_cost_usd), 0)
      : null,
    count: records.length,
    success: records.filter((record) => record.status === 'succeeded').length,
    error: records.filter((record) => record.status === 'failed').length,
  }
}

export function formatModelCost(value) {
  if (!Number.isFinite(value)) return '—'
  if (value === 0) return '$0.0000'
  if (value < .0001) return `$${value.toFixed(6)}`
  if (value < .01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}

export function addModelSummaries(left, right) {
  const costAvailable = Number.isFinite(left?.cost_usd) && Number.isFinite(right?.cost_usd)
  return {
    input_tokens: Number(left?.input_tokens || 0) + Number(right?.input_tokens || 0),
    output_tokens: Number(left?.output_tokens || 0) + Number(right?.output_tokens || 0),
    cost_usd: costAvailable ? Number(left.cost_usd) + Number(right.cost_usd) : null,
    count: Number(left?.count || 0) + Number(right?.count || 0),
    success: Number(left?.success || 0) + Number(right?.success || 0),
    error: Number(left?.error || 0) + Number(right?.error || 0),
  }
}

export function recordedModelPrefix(records = [], revealedRecords = records.length) {
  const count = Math.max(0, Math.min(records.length, Math.floor(Number(revealedRecords) || 0)))
  return summarizeModelRecords(records.slice(0, count))
}

export function playbackModelTelemetry(chapters = [], sites = {}, index = 0, revealedRecords = Number.MAX_SAFE_INTEGER) {
  const safeIndex = Math.max(0, Math.min(Math.max(0, chapters.length - 1), index))
  const previous = chapters
    .slice(0, safeIndex)
    .flatMap((chapter) => sites?.[chapter.id] || [])
  const records = sites?.[chapters[safeIndex]?.id] || []
  const site = recordedModelPrefix(records, revealedRecords)
  return {site, journey: addModelSummaries(summarizeModelRecords(previous), site)}
}

export function estimatedContextProgress(summary, limits) {
  const trigger = Number(limits?.compaction_at_tokens || 0)
  if (!(trigger > 0)) return null
  const captured = Number(summary?.input_tokens || 0) + Number(summary?.output_tokens || 0)
  const cycles = Math.floor(captured / trigger)
  const usedTokens = captured % trigger
  const consumed = usedTokens / trigger
  return {
    captured_tokens: captured,
    used_tokens: usedTokens,
    remaining_tokens: trigger - usedTokens,
    consumed_percent: consumed * 100,
    remaining_percent: (1 - consumed) * 100,
    estimated_compactions: cycles,
  }
}
