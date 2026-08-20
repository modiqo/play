function finiteNonnegative(value) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, number) : 0
}

/** Bead volume has one meaning: token volume. */
export function interactionRadius(record = {}) {
  const signal = Math.log2(2 + finiteNonnegative(record.tokens) / 240)
  return Math.max(.22, Math.min(.52, .18 + signal * .058))
}

/** Halo sweep has one meaning: operation duration/latency. */
export function interactionDurationArc(temporal = {}) {
  const footprint = Math.max(.24, Math.min(.86, finiteNonnegative(temporal.durationWidth)))
  const normalized = (footprint - .24) / (.86 - .24)
  return Math.PI * (.42 + normalized * 1.38)
}
