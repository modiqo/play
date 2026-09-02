/**
 * Steering and gear-dial kinematics, renderer independent.
 *
 * The wheel follows the road, not the gear: its angle is the yaw the route
 * turns through over a short look-ahead, scaled like a real steering ratio
 * and clamped to a plausible hand movement. The dial expresses the active
 * capability as a detent angle. Both are damped so the cockpit never snaps.
 */

export const WHEEL_LIMIT_DEG = 110
export const WHEEL_GAIN = 3.2
export const DIAL_DETENTS = Object.freeze({
  call: -34,
  drive: 0,
  shell: 34,
})

const DEG = Math.PI / 180

function yawOf(tangent) {
  return Math.atan2(Number(tangent?.x) || 0, -(Number(tangent?.z) || 0))
}

/** Signed heading change from one tangent to the next, in degrees, wrapped to (-180, 180]. */
export function headingDeltaDeg(from, to) {
  let delta = (yawOf(to) - yawOf(from)) / DEG
  while (delta > 180) delta -= 360
  while (delta <= -180) delta += 360
  return delta
}

/**
 * Wheel angle for a route bend. Positive turns the wheel clockwise, which
 * matches a right-hand bend when the camera looks down -Z.
 */
export function wheelAngleFromTangents(from, to, {gain = WHEEL_GAIN, limit = WHEEL_LIMIT_DEG} = {}) {
  const delta = headingDeltaDeg(from, to)
  if (!Number.isFinite(delta)) return 0
  return Math.max(-limit, Math.min(limit, delta * gain))
}

/** Exponential damping toward a target; rate is the per-second responsiveness. */
export function dampAngle(current, target, deltaSeconds, rate = 6) {
  const dt = Math.max(0, Number(deltaSeconds) || 0)
  const blend = 1 - Math.exp(-dt * Math.max(0, rate))
  return current + (target - current) * blend
}

/**
 * Small hand corrections while moving so a straight road never reads as a
 * frozen wheel. Two incommensurate sines avoid a visible loop.
 */
export function wheelMicroCorrectionDeg(elapsedSeconds, moving) {
  if (!moving) return 0
  const t = Number(elapsedSeconds) || 0
  return Math.sin(t * 1.7) * 1.4 + Math.sin(t * 0.61 + 1.3) * 0.8
}

/** Detent angle for a capability gear; neutral rests at the centre detent. */
export function dialAngleForGear(gear) {
  return Object.hasOwn(DIAL_DETENTS, gear) ? DIAL_DETENTS[gear] : DIAL_DETENTS.drive
}

/** Detent easing: overshoot slightly, then settle, like a spring-loaded selector. */
export function detentEase(progress) {
  const p = Math.max(0, Math.min(1, Number(progress) || 0))
  const c4 = (2 * Math.PI) / 3
  return p === 0 ? 0 : p === 1 ? 1 : Math.pow(2, -10 * p) * Math.sin((p * 10 - 0.75) * c4) + 1
}
