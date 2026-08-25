const STAGE_SPACING = 21
const ROAD_HALF_WIDTH = 5.4

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value))
}

function hashText(value) {
  let hash = 2166136261
  for (const character of String(value || 'rote-drive')) {
    hash ^= character.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function catmull(value0, value1, value2, value3, amount) {
  const amount2 = amount * amount
  const amount3 = amount2 * amount
  return .5 * (
    2 * value1
    + (-value0 + value2) * amount
    + (2 * value0 - 5 * value1 + 4 * value2 - value3) * amount2
    + (-value0 + 3 * value1 - 3 * value2 + value3) * amount3
  )
}

function routePoint(sites, progress) {
  if (!sites.length) return {x: 0, y: 0, z: 0}
  const bounded = clamp(progress, 0, Math.max(0, sites.length - 1))
  const index = Math.min(sites.length - 1, Math.floor(bounded))
  const amount = bounded - index
  const point0 = sites[Math.max(0, index - 1)]
  const point1 = sites[index]
  const point2 = sites[Math.min(sites.length - 1, index + 1)]
  const point3 = sites[Math.min(sites.length - 1, index + 2)]
  return {
    x: catmull(point0.x, point1.x, point2.x, point3.x, amount),
    y: catmull(point0.y, point1.y, point2.y, point3.y, amount),
    z: catmull(point0.z, point1.z, point2.z, point3.z, amount),
  }
}

export function sampleDriveRoute(plan, progress) {
  const sites = plan?.sites || []
  const point = routePoint(sites, progress)
  const previous = routePoint(sites, progress - .035)
  const next = routePoint(sites, progress + .035)
  let tangentX = next.x - previous.x
  let tangentY = next.y - previous.y
  let tangentZ = next.z - previous.z
  const length = Math.hypot(tangentX, tangentY, tangentZ) || 1
  tangentX /= length
  tangentY /= length
  tangentZ /= length
  return {...point, tangent: {x: tangentX, y: tangentY, z: tangentZ}}
}

export function buildDriveWorldPlan(story = {}) {
  const chapters = Array.isArray(story) ? story : story.chapters || []
  const identity = Array.isArray(story)
    ? chapters.map((chapter) => chapter.id || chapter.title).join(':')
    : story.journey_key || story.outcome || chapters.map((chapter) => chapter.id).join(':')
  const seed = hashText(identity)
  let lateral = ((seed % 17) - 8) * .06
  const sites = chapters.map((chapter, index) => {
    const bend = Math.sin((index + (seed % 11) * .13) * .68) * 2.1
    const decisionBias = chapter.kind === 'decision' ? (index % 2 ? -2.4 : 2.4) : 0
    lateral = clamp(lateral * .42 + bend + decisionBias, -7.5, 7.5)
    return {
      id: chapter.id,
      index,
      kind: chapter.kind,
      x: lateral,
      y: 0,
      z: -index * STAGE_SPACING,
      shoulder: index % 2 ? -1 : 1,
    }
  })
  const sampleCount = Math.max(2, (sites.length - 1) * 24 + 1)
  const samples = Array.from({length: sampleCount}, (_, index) => {
    const progress = sites.length <= 1 ? 0 : index / (sampleCount - 1) * (sites.length - 1)
    return {...sampleDriveRoute({sites}, progress), progress}
  })
  return {
    schema: 'play.drive-world-plan/v1',
    seed,
    roadHalfWidth: ROAD_HALF_WIDTH,
    stageSpacing: STAGE_SPACING,
    sites,
    samples,
  }
}
