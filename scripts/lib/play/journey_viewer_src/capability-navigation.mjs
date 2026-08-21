export function capabilityJumpIndex(occurrenceIndexes = [], currentIndex = 0, fallbackIndex = 0) {
  const current = Math.max(0, Math.floor(Number(currentIndex) || 0))
  const reached = occurrenceIndexes
    .map((value) => Math.max(0, Math.floor(Number(value) || 0)))
    .filter((value) => value <= current)
    .sort((left, right) => left - right)
  return reached.at(-1) ?? Math.max(0, Math.floor(Number(fallbackIndex) || 0))
}
