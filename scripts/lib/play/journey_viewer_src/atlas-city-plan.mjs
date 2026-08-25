function hashText(value) {
  let hash = 2166136261
  for (const character of String(value)) {
    hash ^= character.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function distanceToSegment(px, pz, ax, az, bx, bz) {
  const dx = bx - ax
  const dz = bz - az
  const length = dx * dx + dz * dz || 1
  const amount = Math.max(0, Math.min(1, ((px - ax) * dx + (pz - az) * dz) / length))
  return Math.hypot(px - (ax + dx * amount), pz - (az + dz * amount))
}

function distanceToRoute(x, z, route) {
  let distance = Infinity
  for (let index = 1; index < route.length; index += 1) {
    distance = Math.min(distance, distanceToSegment(
      x, z,
      route[index - 1][0], route[index - 1][2],
      route[index][0], route[index][2],
    ))
  }
  return distance
}

export function buildAtlasCityPlan(atlas, identity = 'play-atlas-city') {
  const route = atlas.semanticPath.map(([x, y]) => [x, .12, -y])
  const sites = atlas.sites.map((site) => ({...site, world: [site.center[0], .12, -site.center[1]]}))
  const padding = 24
  const minimumX = atlas.bounds.minX - padding
  const maximumX = atlas.bounds.maxX + padding
  const minimumZ = -atlas.bounds.maxY - padding
  const maximumZ = -atlas.bounds.minY + padding
  const step = 5.6
  const buildings = []
  for (let x = Math.floor(minimumX / step) * step; x <= maximumX; x += step) {
    for (let z = Math.floor(minimumZ / step) * step; z <= maximumZ; z += step) {
      const key = hashText(`${identity}:${x.toFixed(1)}:${z.toFixed(1)}`)
      if (key % 20 < 12) continue
      if (distanceToRoute(x, z, route) < 8.2) continue
      if (sites.some((site) => Math.hypot(x - site.world[0], z - site.world[2]) < 8.8)) continue
      const width = 3 + ((key >>> 5) % 16) / 10
      const depth = 3 + ((key >>> 9) % 16) / 10
      const height = 3.2 + ((key >>> 13) % 100) / 10
      buildings.push({
        id: `building-${buildings.length}`,
        x: x + (((key >>> 18) % 7) - 3) * .08,
        z: z + (((key >>> 21) % 7) - 3) * .08,
        width,
        depth,
        height,
        tone: .72 + ((key >>> 24) % 20) / 100,
        crown: key % 9 === 0,
      })
    }
  }
  return {
    schema: 'play.atlas-city-plan/v1',
    route,
    sites,
    buildings,
    bounds: {minimumX, maximumX, minimumZ, maximumZ},
  }
}

export function sampleAtlasCityRoute(route, progress) {
  if (!route.length) return {position: [0, 0, 0], tangent: [0, 0, -1]}
  const bounded = Math.max(0, Math.min(1, Number(progress) || 0))
  const scaled = bounded * Math.max(1, route.length - 1)
  const index = Math.min(Math.max(0, route.length - 2), Math.floor(scaled))
  const amount = scaled - index
  const source = route[index]
  const target = route[Math.min(route.length - 1, index + 1)]
  const position = source.map((value, axis) => value + (target[axis] - value) * amount)
  const length = Math.hypot(target[0] - source[0], target[2] - source[2]) || 1
  return {
    position,
    tangent: [(target[0] - source[0]) / length, 0, (target[2] - source[2]) / length],
  }
}
