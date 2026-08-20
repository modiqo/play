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
