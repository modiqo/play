export const MAX_RENDER_PIXEL_RATIO = 2
export const MAX_RENDER_PIXELS = 5_500_000
export const COMPOSER_SAMPLES = 4

/**
 * Preserve Retina edges on compact displays without allowing a large or
 * externally scaled canvas to multiply the GPU fill cost without bound.
 */
export function adaptiveRenderPixelRatio(devicePixelRatio, width, height, pixelBudget = MAX_RENDER_PIXELS) {
  const requested = Math.max(1, Math.min(MAX_RENDER_PIXEL_RATIO, Number(devicePixelRatio) || 1))
  const area = Math.max(0, Number(width) || 0) * Math.max(0, Number(height) || 0)
  if (!(area > 0) || !(pixelBudget > 0)) return requested
  return Math.max(1, Math.min(requested, Math.sqrt(pixelBudget / area)))
}

/**
 * Coarse GPU budget tier from what the browser will tell us without a probe.
 * `high` enables refractive visor glass and bloom; `balanced` keeps the same
 * geometry with cheaper materials; `reduced` also honours reduced motion.
 */
export function renderQualityTier({devicePixelRatio = 1, hardwareConcurrency = 4, width = 1280, height = 720, reducedMotion = false} = {}) {
  if (reducedMotion) return 'reduced'
  const area = Math.max(0, Number(width) || 0) * Math.max(0, Number(height) || 0) * Math.max(1, Number(devicePixelRatio) || 1) ** 2
  const cores = Math.max(1, Number(hardwareConcurrency) || 1)
  if (cores >= 8 && area <= 9_000_000) return 'high'
  if (cores >= 4 && area <= 12_000_000) return 'balanced'
  return 'balanced'
}
