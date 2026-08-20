function finiteNonnegative(value) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, number) : 0
}

/** Tower height has one meaning: token volume. */
export function towerHeight(record = {}) {
  const signal = Math.log2(2 + finiteNonnegative(record.tokens) / 240)
  return Math.max(.7, Math.min(4.6, signal))
}

/** Tower frontage width has one meaning: operation duration. */
export function towerWidth(temporal = {}, fallback = .24) {
  return Math.max(finiteNonnegative(fallback), finiteNonnegative(temporal.durationWidth))
}
