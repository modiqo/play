export const DARK = {
  ground: [12, 14, 16], district: [24, 27, 29], districtAlt: [19, 22, 24],
  street: [78, 84, 86, 145], streetCore: [17, 19, 21, 230],
  building: [91, 96, 99], buildingTop: [128, 132, 134], ink: [242, 160, 57],
  muted: [149, 115, 71], routeBed: [29, 31, 33, 255], audit: [163, 168, 169, 75],
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

function bend(source, target, elevation = .22) {
  const dx = target[0] - source[0]
  const dy = target[1] - source[1]
  const length = Math.max(1, Math.hypot(dx, dy))
  const curve = Math.min(8, length * .16)
  const nx = -dy / length
  const ny = dx / length
  return [source, [(source[0] + target[0]) / 2 + nx * curve, (source[1] + target[1]) / 2 + ny * curve, elevation], target]
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

function roundedPath(points, subdivisions = 8) {
  if (points.length < 3) return points
  const result = [points[0]]
  for (let index = 1; index < points.length - 1; index += 1) {
    const before = points[index - 1]
    const corner = points[index]
    const after = points[index + 1]
    const incoming = Math.hypot(corner[0] - before[0], corner[1] - before[1])
    const outgoing = Math.hypot(after[0] - corner[0], after[1] - corner[1])
    const radius = Math.min(5.5, incoming * .18, outgoing * .18)
    const entry = [
      corner[0] + (before[0] - corner[0]) / Math.max(.001, incoming) * radius,
      corner[1] + (before[1] - corner[1]) / Math.max(.001, incoming) * radius,
      corner[2],
    ]
    const exit = [
      corner[0] + (after[0] - corner[0]) / Math.max(.001, outgoing) * radius,
      corner[1] + (after[1] - corner[1]) / Math.max(.001, outgoing) * radius,
      corner[2],
    ]
    result.push(entry)
    for (let step = 1; step <= subdivisions; step += 1) {
      const amount = step / subdivisions
      const inverse = 1 - amount
      result.push([
        inverse * inverse * entry[0] + 2 * inverse * amount * corner[0] + amount * amount * exit[0],
        inverse * inverse * entry[1] + 2 * inverse * amount * corner[1] + amount * amount * exit[1],
        corner[2],
      ])
    }
  }
  result.push(points[points.length - 1])
  return result
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

function offsetPath(points, distance) {
  return points.map((point, index) => {
    const before = points[Math.max(0, index - 1)]
    const after = points[Math.min(points.length - 1, index + 1)]
    const dx = after[0] - before[0]
    const dy = after[1] - before[1]
    const length = Math.max(.001, Math.hypot(dx, dy))
    return [point[0] - dy / length * distance, point[1] + dx / length * distance, point[2]]
  })
}

export function buildAtlas(story, scene, interactionProjection) {
  const chapters = story.chapters
  const count = chapters.length
  const columns = Math.max(2, Math.ceil(Math.sqrt(count * 1.55)))
  const xStep = 34
  const yStep = 28
  const centers = new Map()
  const sites = chapters.map((chapter, order) => {
    const row = Math.floor(order / columns)
    const cell = order % columns
    const column = row % 2 === 0 ? cell : columns - 1 - cell
    const semanticDrift = ((stableNumber(chapter.id) % 7) - 3) * .42
    const center = [column * xStep, row * yStep + semanticDrift, .42]
    centers.set(chapter.id, center)
    const interactions = interactionProjection?.sites?.[chapter.id] || []
    return {...chapter, center, row, column, interactions}
  })

  const districts = []
  const contours = []
  const buildings = []
  const streets = []
  for (const site of sites) {
    const [cx, cy] = site.center
    const buildingColumns = Math.max(1, Math.ceil(Math.sqrt(Math.max(1, site.interactions.length) * 1.25)))
    const buildingRows = Math.max(1, Math.ceil(Math.max(1, site.interactions.length) / buildingColumns))
    const width = Math.max(27, buildingColumns * 5.2 + 11)
    const depth = Math.max(22, buildingRows * 5.2 + 11)
    site.width = width
    site.depth = depth
    districts.push({id: `district-${site.id}`, site, polygon: rectangle(cx, cy, width, depth, 0)})
    for (let ring = 1; ring <= 3; ring += 1) {
      contours.push({
        id: `contour-${site.id}-${ring}`, site,
        path: rectangle(cx, cy, width + ring * 2.6, depth + ring * 2.6, .07),
        ring,
      })
    }
    streets.push(
      {id: `street-h-${site.id}`, path: [[cx - width / 2, cy, .15], [cx + width / 2, cy, .15]]},
      {id: `street-v-${site.id}`, path: [[cx, cy - depth / 2, .15], [cx, cy + depth / 2, .15]]},
      {id: `street-n-${site.id}`, path: [[cx - width / 2, cy - depth * .34, .15], [cx + width / 2, cy - depth * .34, .15]]},
      {id: `street-e-${site.id}`, path: [[cx + width * .34, cy - depth / 2, .15], [cx + width * .34, cy + depth / 2, .15]]},
    )

    const seed = stableNumber(site.id)
    for (let index = 0; index < site.interactions.length; index += 1) {
      const interaction = site.interactions[index]
      const row = Math.floor(index / buildingColumns)
      const rawColumn = index % buildingColumns
      const column = row % 2 === 0 ? rawColumn : buildingColumns - 1 - rawColumn
      const slot = [
        (column - (buildingColumns - 1) / 2) * 5.1,
        (row - (buildingRows - 1) / 2) * 5.1,
      ]
      const variance = ((seed >>> (index % 16)) & 15) / 15
      const towerWidth = 3.0 + ((seed + index * 13) % 10) / 10
      const towerDepth = 3.0 + ((seed + index * 19) % 8) / 10
      const telemetryScale = Math.log2(interaction.duration_ms + interaction.tokens / 3 + 2)
      const height = 2.5 + telemetryScale * (1.25 + variance * .62)
      const center = [cx + slot[0], cy + slot[1], .24]
      buildings.push({
        id: `interaction-${interaction.sequence}`, site, interaction, center,
        polygon: rectangle(center[0], center[1], towerWidth, towerDepth, .22),
        height, tone: .08 + variance * .36,
      })
    }
    site.localPath = smoothPath(
      buildings
        .filter((building) => building.site.id === site.id)
        .sort((a, b) => a.interaction.sequence - b.interaction.sequence)
        .map((building) => building.center),
      6,
    )
  }

  const buildingBySequence = new Map(buildings.map((building) => [building.interaction.sequence, building]))
  const semanticPath = roundedPath(sites.map((site) => site.center), 8)
  const sceneEdges = Array.isArray(scene?.edges) ? scene.edges : []
  const auditRoutes = sceneEdges.flatMap((edge) => {
    if (edge.kind === 'derived_from' || edge.kind === 'decomposes_into') return []
    const source = centers.get(edge.source)
    const target = centers.get(edge.target)
    if (!source || !target) return []
    return [{...edge, path: bend(source, target, .72)}]
  })
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
    sites, districts, contours, buildings, streets, gridLines, semanticPath, auditRoutes, buildingBySequence,
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

