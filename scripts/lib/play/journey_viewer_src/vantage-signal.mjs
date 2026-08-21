export const VANTAGE_SIGNAL_COLORS = Object.freeze({
  healthy: 0x55d98b,
  caution: 0xe88413,
  error: 0xe64b4b,
})

/**
 * Resolve the health signal for one vantage from the same operations used to
 * build its @ bead cluster. A minority error rate is cautionary; a rate of 50%
 * or more is an error. A gate without failed evidence remains a caution.
 */
export function vantageSignal(chapter = {}, records = []) {
  const observed = records.filter((record) => record?.status === 'succeeded' || record?.status === 'failed')
  const failures = observed.filter((record) => record.status === 'failed').length
  const errorRate = observed.length ? failures / observed.length : 0
  if (errorRate >= .5 || (chapter.status === 'failed' && chapter.kind !== 'blocker' && !observed.length)) {
    return {kind: 'error', color: VANTAGE_SIGNAL_COLORS.error}
  }
  if (failures || chapter.kind === 'authority' || chapter.kind === 'blocker' || chapter.status === 'blocked') {
    return {kind: 'caution', color: VANTAGE_SIGNAL_COLORS.caution}
  }
  return {kind: 'healthy', color: VANTAGE_SIGNAL_COLORS.healthy}
}
