function numericEpoch(value) {
  const epoch = Number(value)
  return Number.isFinite(epoch) && epoch > 0 ? epoch : 0
}

export function journeyActivityEpoch(item = {}) {
  const activity = numericEpoch(item.activity_epoch)
  if (activity) return activity
  const created = Date.parse(item.created_at || '')
  return Number.isFinite(created) ? created / 1000 : 0
}

export function journeyPickerItems(items = []) {
  return [...items].sort((left, right) => {
    if (Boolean(left.tutorial) !== Boolean(right.tutorial)) return left.tutorial ? 1 : -1
    const byTime = journeyActivityEpoch(right) - journeyActivityEpoch(left)
    if (byTime) return byTime
    return String(left.intent || left.id || '').localeCompare(String(right.intent || right.id || ''))
  })
}

export function journeyKind(item = {}) {
  if (item.tutorial) return 'START HERE'
  if (item.journey_mode === 'live') return 'LIVE'
  if (item.journey_mode === 'workspace') return 'WORKSPACE'
  return 'RECORDED'
}

export function journeyActivityLabel(item = {}, nowMs = Date.now()) {
  const epoch = journeyActivityEpoch(item)
  if (!epoch) return 'TIME NOT RECORDED'
  const ageSeconds = Math.max(0, Math.round(nowMs / 1000 - epoch))
  if (ageSeconds < 60) return 'JUST NOW'
  if (ageSeconds < 3600) return `${Math.max(1, Math.round(ageSeconds / 60))}M AGO`
  if (ageSeconds < 86400) return `${Math.max(1, Math.round(ageSeconds / 3600))}H AGO`
  if (ageSeconds < 604800) return `${Math.max(1, Math.round(ageSeconds / 86400))}D AGO`
  return new Date(epoch * 1000).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'}).toUpperCase()
}
