import {interactionDurationArc, interactionRadius} from './interaction-metrics.mjs'
import {layoutTemporalCorridor} from './temporal-corridor.mjs'

export const DARK = {
  ground: [12, 14, 16], district: [24, 27, 29], districtAlt: [19, 22, 24],
  street: [78, 84, 86, 145], streetCore: [17, 19, 21, 230],
  building: [91, 96, 99], buildingTop: [128, 132, 134], ink: [242, 160, 57],
  muted: [149, 115, 71], routeBed: [29, 31, 33, 255],
}

export const NAV_BLUE = [194, 111, 20]
export const NAV_BLUE_BRIGHT = [240, 160, 58]

export function rgba(rgb, alpha = 255) {
  return rgb.length === 4 ? rgb : [...rgb, alpha]
}

function stableNumber(value) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function rectangle(cx, cy, width, depth, z = 0) {
  const x = width / 2
  const y = depth / 2
  return [
    [cx - x, cy - y, z], [cx + x, cy - y, z], [cx + x, cy + y, z],
    [cx - x, cy + y, z], [cx - x, cy - y, z],
  ]
}

function smoothPath(points, subdivisions = 8) {
  if (points.length < 2) return points
  const result = []
  for (let index = 0; index < points.length - 1; index += 1) {
    const p0 = points[Math.max(0, index - 1)]
    const p1 = points[index]
    const p2 = points[index + 1]
    const p3 = points[Math.min(points.length - 1, index + 2)]
    for (let step = 0; step < subdivisions; step += 1) {
      const t = step / subdivisions
      const t2 = t * t
      const t3 = t2 * t
      result.push([0, 1, 2].map((axis) => .5 * (
        (2 * p1[axis]) + (-p0[axis] + p2[axis]) * t +
        (2 * p0[axis] - 5 * p1[axis] + 4 * p2[axis] - p3[axis]) * t2 +
        (-p0[axis] + 3 * p1[axis] - 3 * p2[axis] + p3[axis]) * t3
      )))
    }
  }
  return [...result, points[points.length - 1]]
}

export function interpolatePath(points, progress) {
  if (!points.length) return [0, 0, 0]
  if (points.length === 1) return points[0]
  const scaled = Math.max(0, Math.min(1, progress)) * (points.length - 1)
  const index = Math.min(points.length - 2, Math.floor(scaled))
  const amount = scaled - index
  const source = points[index]
  const target = points[index + 1]
  return source.map((value, axis) => value + (target[axis] - value) * amount)
}

function threadPath(source, target, direction = 1, subdivisions = 14) {
  const dx = target[0] - source[0]
  const dy = target[1] - source[1]
  const length = Math.max(.001, Math.hypot(dx, dy))
  const nx = -dy / length
  const ny = dx / length
  const bow = Math.min(.34, length * .1) * direction
  const sag = Math.min(.2, length * .045)
  return Array.from({length: subdivisions + 1}, (_, index) => {
    if (index === 0) return [...source]
    if (index === subdivisions) return [...target]
    const amount = index / subdivisions
    const curve = Math.sin(Math.PI * amount)
    const irregularity = Math.sin(Math.PI * amount * 2) * .035
    return [
      source[0] + dx * amount + nx * (bow * curve + irregularity),
      source[1] + dy * amount + ny * (bow * curve + irregularity),
      source[2] + (target[2] - source[2]) * amount - sag * curve,
    ]
  })
}

function haloPath(center, radius, sweep, subdivisions = 28) {
  return Array.from({length: subdivisions + 1}, (_, index) => {
    const angle = -Math.PI / 2 + sweep * index / subdivisions
    return [
      center[0] + Math.cos(angle) * (radius + .105),
      center[1] - .025,
      center[2] + Math.sin(angle) * (radius + .105),
    ]
  })
}

export function buildAtlas(story, interactionProjection) {
  const chapters = story.chapters || []
  const count = chapters.length
  const columns = Math.max(2, Math.ceil(Math.sqrt(count * 1.55)))
  const xStep = 34
  const yStep = 28
  const sites = chapters.map((chapter, order) => {
    const row = Math.floor(order / columns)
    const cell = order % columns
    const column = row % 2 === 0 ? cell : columns - 1 - cell
    const semanticDrift = ((stableNumber(chapter.id) % 7) - 3) * .42
    const center = [column * xStep, row * yStep + semanticDrift, .42]
    const interactions = interactionProjection?.sites?.[chapter.id] || []
    return {...chapter, center, row, column, interactions, width: 15, depth: 12}
  })

  const districts = []
  const contours = []
  const beads = []
  const threads = []
  const halos = []
  const streets = []
  for (const site of sites) {
    const [cx, cy] = site.center
    districts.push({id: `district-${site.id}`, site, polygon: rectangle(cx, cy, site.width, site.depth, 0)})
    for (let ring = 1; ring <= 2; ring += 1) {
      contours.push({
        id: `contour-${site.id}-${ring}`, site,
        path: rectangle(cx, cy, site.width + ring * 1.4, site.depth + ring * 1.4, .07),
        ring,
      })
    }
    const temporalCorridor = layoutTemporalCorridor(site.interactions)
    streets.push({
      id: `timeline-${site.id}`,
      site,
      path: temporalCorridor.spine.map((point) => [cx + point.x, cy + point.z, .2]),
    })
    const seed = stableNumber(site.id)
    const siteBeads = temporalCorridor.points.map((temporal, index) => {
      const interaction = temporal.record
      const radius = interactionRadius(interaction)
      const elevation = .82 + radius + temporal.lane * .56 + (index % 2) * .12
      const center = [cx + temporal.x, cy + temporal.z, elevation]
      const bead = {
        id: `interaction-${interaction.sequence}`, site, interaction, temporal, center, radius,
        tone: .08 + (((seed >>> (index % 16)) & 15) / 15) * .36,
      }
      halos.push({
        id: `halo-${interaction.sequence}`, bead,
        path: haloPath(center, radius, interactionDurationArc(temporal)),
      })
      return bead
    })
    beads.push(...siteBeads)
    for (let index = 1; index < siteBeads.length; index += 1) {
      const source = siteBeads[index - 1]
      const target = siteBeads[index]
      threads.push({
        id: `thread-${source.interaction.sequence}-${target.interaction.sequence}`,
        site, source, target,
        path: threadPath(source.center, target.center, index % 2 === 0 ? 1 : -1),
      })
    }
    site.localPath = siteBeads.length > 1
      ? smoothPath(siteBeads.map((bead) => bead.center), 6)
      : siteBeads.map((bead) => bead.center)
  }

  const beadBySequence = new Map(beads.map((bead) => [bead.interaction.sequence, bead]))
  const semanticPath = smoothPath(sites.map((site) => site.center), 10)
  const minX = Math.min(...sites.map((site) => site.center[0] - site.width / 2)) - 8
  const maxX = Math.max(...sites.map((site) => site.center[0] + site.width / 2)) + 8
  const minY = Math.min(...sites.map((site) => site.center[1] - site.depth / 2)) - 8
  const maxY = Math.max(...sites.map((site) => site.center[1] + site.depth / 2)) + 8
  const gridLines = []
  for (let x = Math.floor(minX / 8) * 8; x <= maxX; x += 8) {
    gridLines.push({id: `grid-x-${x}`, path: [[x, minY, .01], [x, maxY, .01]]})
  }
  for (let y = Math.floor(minY / 8) * 8; y <= maxY; y += 8) {
    gridLines.push({id: `grid-y-${y}`, path: [[minX, y, .01], [maxX, y, .01]]})
  }
  return {
    sites, districts, contours, beads, threads, halos, streets, gridLines, semanticPath, beadBySequence,
    ground: rectangle((minX + maxX) / 2, (minY + maxY) / 2, maxX - minX + 22, maxY - minY + 22, -.1),
    bounds: {minX, maxX, minY, maxY},
  }
}

export function fitView(atlas) {
  const {minX, maxX, minY, maxY} = atlas.bounds
  const span = Math.max(maxX - minX, (maxY - minY) * 1.45, 32)
  return {
    target: [(minX + maxX) / 2, (minY + maxY) / 2, 0], rotationOrbit: -28,
    rotationX: 55, zoom: Math.log2(760 / span) + .62, minZoom: -2, maxZoom: 6,
  }
}
