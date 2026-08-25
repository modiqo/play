function upper(value) {
  const text = String(value || '').trim()
  return text ? text.toUpperCase() : ''
}

/** Keep missing access metadata quiet while presenting the known interface. */
export function interactionStateLabel(record = {}) {
  const status = upper(record.status || 'recorded')
  const operation = upper(record.operation)
  const knownInterface = upper(record.capability?.interface)
    || upper(record.modality)
    || (operation.includes('CLI') ? 'CLI' : '')
    || (operation.includes('BROWSER') ? 'BROWSER' : '')
    || (operation.includes('API') ? 'API' : '')
    || 'RECORDED'
  return `${knownInterface} · ${status}`
}
