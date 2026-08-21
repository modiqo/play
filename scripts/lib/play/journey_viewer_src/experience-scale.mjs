export const EXPERIENCE_SCALES = [1, 1.15, 1.3, 1.45]

export function storedExperienceScale(value) {
  const number = Number(value)
  return EXPERIENCE_SCALES.find((item) => Math.abs(item - number) < .001) ?? null
}

export function defaultExperienceScale(width, height) {
  return Number(width) <= 1440 || Number(height) <= 900 ? 1.15 : 1
}

export function markerScaleForExperience(scale, width, height) {
  const selected = storedExperienceScale(scale) ?? 1
  const shortEdge = Math.min(Number(width) || 0, Number(height) || 0)
  const compactBoost = shortEdge > 0 && shortEdge < 900
    ? Math.min(.07, (900 - shortEdge) / 1900)
    : 0
  return Math.min(1.3, 1 + (selected - 1) * .56 + compactBoost)
}

export function adjacentExperienceScale(scale, direction) {
  const selected = storedExperienceScale(scale) ?? 1
  const index = EXPERIENCE_SCALES.indexOf(selected)
  return EXPERIENCE_SCALES[Math.max(0, Math.min(EXPERIENCE_SCALES.length - 1, index + Math.sign(direction)))]
}
