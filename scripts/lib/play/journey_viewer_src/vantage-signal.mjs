export const VANTAGE_SIGNAL_COLORS = Object.freeze({
  healthy: 0x55d98b,
  caution: 0xe88413,
  error: 0xe64b4b,
})

/**
 * Resolve the health signal for one vantage from the same operations used to
 * build its @ bead cluster. Recorded failures take precedence over semantic
 * gates; a gate without an observed failure remains a caution rather than an
 * error.
 */
export function vantageSignal(chapter = {}, records = []) {
  const hasFailedOperation = records.some((record) => record?.status === 'failed')
  if (hasFailedOperation || (chapter.status === 'failed' && chapter.kind !== 'blocker')) {
    return {kind: 'error', color: VANTAGE_SIGNAL_COLORS.error}
  }
  if (chapter.kind === 'authority' || chapter.kind === 'blocker' || chapter.status === 'blocked') {
    return {kind: 'caution', color: VANTAGE_SIGNAL_COLORS.caution}
  }
  return {kind: 'healthy', color: VANTAGE_SIGNAL_COLORS.healthy}
}
