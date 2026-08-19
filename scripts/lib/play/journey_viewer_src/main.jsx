import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {createRoot} from 'react-dom/client'
import DeckGL from '@deck.gl/react'
import {AmbientLight, COORDINATE_SYSTEM, DirectionalLight, LightingEffect, LinearInterpolator, OrbitView} from '@deck.gl/core'
import {ColumnLayer, PathLayer, PolygonLayer, ScatterplotLayer, TextLayer} from '@deck.gl/layers'
import JourneyWorld, {KIND_LABEL, MAP_MEANING, WORLD_ROLE, WORLD_STORY} from './world.jsx'

const queryToken = new URLSearchParams(location.search).get('token') || ''
if (queryToken) sessionStorage.setItem('play-journey-token', queryToken)
const token = queryToken || sessionStorage.getItem('play-journey-token') || ''
if (token) history.replaceState(null, '', location.pathname)
const api = (path, values = {}) => `${path}?${new URLSearchParams({token, ...values})}`

const LIGHT = {
  ground: [231, 235, 234], district: [244, 245, 241], districtAlt: [236, 238, 235],
  street: [176, 183, 182, 155], streetCore: [250, 250, 247, 220],
  building: [43, 46, 49], buildingTop: [65, 68, 71], ink: [39, 41, 42],
  muted: [115, 119, 119], routeBed: [247, 248, 245, 255], audit: [84, 91, 93, 75],
}

const DARK = {
  ground: [12, 14, 16], district: [24, 27, 29], districtAlt: [19, 22, 24],
  street: [78, 84, 86, 145], streetCore: [17, 19, 21, 230],
  building: [91, 96, 99], buildingTop: [128, 132, 134], ink: [242, 160, 57],
  muted: [149, 115, 71], routeBed: [29, 31, 33, 255], audit: [163, 168, 169, 75],
}

const NAV_BLUE = [194, 111, 20]
const NAV_BLUE_BRIGHT = [240, 160, 58]

function rgba(rgb, alpha = 255) {
  return rgb.length === 4 ? rgb : [...rgb, alpha]
}

function formatNumber(value) {
  const number = Number(value || 0)
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`
  if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 1 : 2)}K`
  return String(number)
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

function interpolatePath(points, progress) {
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

function buildAtlas(story, scene, interactionProjection) {
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

function fitView(atlas) {
  const {minX, maxX, minY, maxY} = atlas.bounds
  const span = Math.max(maxX - minX, (maxY - minY) * 1.45, 32)
  return {
    target: [(minX + maxX) / 2, (minY + maxY) / 2, 0], rotationOrbit: -28,
    rotationX: 55, zoom: Math.log2(760 / span) + .62, minZoom: -2, maxZoom: 6,
  }
}

function useMotion(active) {
  const [phase, setPhase] = useState(0)
  useEffect(() => {
    if (!active) return undefined
    let frame = 0
    let previous = 0
    const tick = (time) => {
      if (time - previous > 40) {
        previous = time
        setPhase((time % 3200) / 3200)
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [active])
  return phase
}

function Cartography({story, scene, interactions, replay, playing, audit, selected, onSelect, fitSignal}) {
  const atlas = useMemo(() => buildAtlas(story, scene, interactions), [interactions, scene, story])
  const fittedView = useMemo(() => fitView(atlas), [atlas])
  const colors = DARK
  const live = story.state === 'active'
  const phase = useMotion(live || playing)
  const [viewState, setViewState] = useState(() => fittedView)
  const previousJourney = useRef(story.journey_key)

  useEffect(() => {
    if (previousJourney.current !== story.journey_key || fitSignal) {
      previousJourney.current = story.journey_key
      setViewState(fittedView)
    }
  }, [atlas, fitSignal, fittedView, story.journey_key])

  useEffect(() => {
    if (!selected?.siteId) return
    const building = selected.sequence ? atlas.buildingBySequence.get(selected.sequence) : null
    const site = atlas.sites.find((item) => item.id === selected.siteId)
    if (!building && !site) return
    const center = building?.center || site.center
    setViewState((current) => ({
      ...current,
      target: [center[0], center[1], building ? building.height * .34 : 0],
      zoom: building ? fittedView.zoom + 2.35 : fittedView.zoom + 1.15,
      rotationX: building ? 64 : 58,
      transitionDuration: 850,
      transitionInterpolator: new LinearInterpolator(['target', 'zoom', 'rotationX', 'rotationOrbit']),
    }))
  }, [atlas, fittedView.zoom, selected?.sequence, selected?.siteId])

  const semanticZoom = viewState.zoom < fittedView.zoom + .82 ? 'journey' : viewState.zoom < fittedView.zoom + 2.05 ? 'phase' : 'evidence'
  const visibleSiteCount = Math.ceil(replay * atlas.sites.length)
  const reachedSites = new Set(atlas.sites.slice(0, visibleSiteCount).map((site) => site.id))
  const orderedBuildings = [...atlas.buildings].sort((a, b) => a.interaction.sequence - b.interaction.sequence)
  const visibleBuildingCount = Math.ceil(replay * orderedBuildings.length)
  const reachedSequences = new Set(orderedBuildings.slice(0, visibleBuildingCount).map((building) => building.interaction.sequence))
  const pathCount = Math.max(1, Math.ceil(replay * atlas.semanticPath.length))
  const visiblePath = atlas.semanticPath.slice(0, pathCount)
  const currentPosition = interpolatePath(visiblePath, (live && replay >= .995) || playing ? Math.max(.9, phase) : 1)
  const selectedSite = atlas.sites.find((site) => site.id === selected?.siteId)
  const replaySite = atlas.sites[Math.max(0, visibleSiteCount - 1)]
  const currentSite = playing || story.state !== 'active'
    ? replaySite
    : (atlas.sites.find((site) => site.id === story.current_chapter) || replaySite)
  const focusSite = selectedSite || currentSite
  const focusPath = focusSite?.localPath || []
  const phaseBuildings = semanticZoom === 'journey'
    ? atlas.buildings
    : atlas.buildings.filter((building) => building.site.id === focusSite?.id)
  const visiblePhaseBuildings = phaseBuildings.filter((building) => reachedSequences.has(building.interaction.sequence))
  const focusDistricts = focusSite ? atlas.districts.filter((district) => district.site.id === focusSite.id) : []
  const focusContours = focusSite ? atlas.contours.filter((contour) => contour.site.id === focusSite.id) : []
  const focusStreets = focusSite ? atlas.streets.filter((street) => street.id.includes(focusSite.id)) : []
  const landmarkKinds = new Set(['intent', 'blocker', 'recovery', 'milestone', 'artifact', 'play_candidate', 'play'])
  const calloutSites = semanticZoom === 'journey'
    ? atlas.sites.filter((site) => site.id === currentSite?.id || site.id === selectedSite?.id || site.order === atlas.sites.length - 1 || landmarkKinds.has(site.kind))
    : (focusSite ? [focusSite] : [])
  const callouts = calloutSites.map((site) => {
    const tallest = Math.max(3.5, ...site.interactions.map((interaction) => atlas.buildingBySequence.get(interaction.sequence)?.height || 0))
    const side = (site.row + site.column) % 2 === 0 ? 1 : -1
    const verticalOffset = site.row % 2 === 0 ? -3.8 : 3.8
    const position = [site.center[0] + side * 4.6, site.center[1] + verticalOffset, tallest + 3.5]
    const currentOrder = currentSite?.order || 0
    const role = site.order === 0 ? 'START' : site.id === currentSite?.id ? (story.state === 'active' ? 'NOW' : 'FINISH') : site.order < currentOrder ? 'DONE' : 'NEXT'
    return {site, position, anchor: [site.center[0], site.center[1], .55], role}
  })

  useEffect(() => {
    if (!playing || !currentSite) return
    setViewState((current) => ({
      ...current,
      target: [currentSite.center[0], currentSite.center[1], 0],
      zoom: fittedView.zoom + 1.02,
      rotationX: 56,
      rotationOrbit: -32 + currentSite.order * 3.5,
      transitionDuration: 620,
      transitionInterpolator: new LinearInterpolator(['target', 'zoom', 'rotationX', 'rotationOrbit']),
    }))
  }, [currentSite?.id, fittedView.zoom, playing])
  const ambient = useMemo(() => new AmbientLight({color: [255, 255, 255], intensity: 1.15}), [])
  const sun = useMemo(() => new DirectionalLight({color: [255, 255, 255], intensity: 2.15, direction: [-3, -7, -10]}), [])
  const effects = useMemo(() => [new LightingEffect({ambient, sun})], [ambient, sun])
  const coordinateSystem = COORDINATE_SYSTEM.CARTESIAN
  const layers = [
    new PolygonLayer({id: 'atlas-ground', data: [{polygon: atlas.ground}], coordinateSystem, getPolygon: (item) => item.polygon, getFillColor: rgba(colors.ground), filled: true, stroked: false, extruded: false}),
    new PathLayer({
      id: 'terrain-grid', data: atlas.gridLines, coordinateSystem, getPath: (item) => item.path,
      getColor: [...colors.street, 26], getWidth: .65, widthUnits: 'pixels',
    }),
    new PolygonLayer({
      id: 'semantic-districts', data: semanticZoom === 'journey' ? [] : focusDistricts, coordinateSystem, getPolygon: (item) => item.polygon,
      getFillColor: [...colors.ground, 22],
      filled: true, stroked: true, getLineColor: [...NAV_BLUE, 72], getLineWidth: 1.2,
      lineWidthUnits: 'pixels', extruded: false, pickable: true,
      onClick: ({object}) => object && onSelect({siteId: object.site.id, sequence: null}),
    }),
    new PathLayer({
      id: 'terrain-contours', data: semanticZoom === 'journey' ? [] : focusContours, coordinateSystem, getPath: (item) => item.path,
      getColor: (item) => [...colors.street, 74 - item.ring * 12],
      getWidth: .75, widthUnits: 'pixels', jointRounded: true, capRounded: true,
    }),
    new PathLayer({id: 'city-streets-bed', data: semanticZoom === 'journey' ? [] : focusStreets, coordinateSystem, getPath: (item) => item.path, getColor: colors.streetCore, getWidth: 4.4, widthUnits: 'pixels', jointRounded: true, capRounded: true}),
    new PathLayer({id: 'city-streets', data: semanticZoom === 'journey' ? [] : focusStreets, coordinateSystem, getPath: (item) => item.path, getColor: colors.street, getWidth: .9, widthUnits: 'pixels', jointRounded: true, capRounded: true}),
    audit && new PathLayer({id: 'semantic-audit-routes', data: atlas.auditRoutes, coordinateSystem, getPath: (item) => item.path, getColor: colors.audit, getWidth: (item) => item.active ? 2.1 : 1, widthUnits: 'pixels', jointRounded: true, capRounded: true, pickable: true}),
    new PathLayer({id: 'journey-road-bed', data: [{path: atlas.semanticPath}], coordinateSystem, getPath: (item) => item.path, getColor: [4, 6, 8, 245], getWidth: 8, widthUnits: 'pixels', jointRounded: true, capRounded: true}),
    new PathLayer({
      id: 'journey-route', data: [{path: atlas.semanticPath}], coordinateSystem,
      getPath: (item) => item.path, getColor: [...NAV_BLUE, 132], getWidth: 2.4,
      widthUnits: 'pixels', jointRounded: true, capRounded: true,
    }),
    new PathLayer({
      id: 'journey-live-trail', data: [{path: visiblePath}], coordinateSystem,
      getPath: (item) => item.path, getColor: [...NAV_BLUE_BRIGHT, 248], getWidth: 2.8,
      widthUnits: 'pixels', jointRounded: true, capRounded: true,
    }),
    new PathLayer({
      id: 'phase-entry-path', data: focusPath.length ? [{path: focusPath}] : [], coordinateSystem,
      getPath: (item) => item.path, getColor: [...NAV_BLUE_BRIGHT, semanticZoom === 'journey' ? 0 : 235],
      getWidth: semanticZoom === 'evidence' ? 3.4 : 2.4, widthUnits: 'pixels', jointRounded: true, capRounded: true,
    }),
    new ScatterplotLayer({
      id: 'semantic-stations', data: atlas.sites, coordinateSystem,
      getPosition: (item) => [item.center[0], item.center[1], .22],
      getRadius: (item) => item.id === currentSite?.id ? 7 : 4.5,
      radiusUnits: 'pixels', filled: true, stroked: true,
      getFillColor: [12, 14, 16, 255],
      getLineColor: (item) => item.id === currentSite?.id ? [...NAV_BLUE_BRIGHT, 255] : [178, 184, 187, reachedSites.has(item.id) ? 185 : 58],
      getLineWidth: (item) => item.id === currentSite?.id ? 2 : 1, lineWidthUnits: 'pixels',
      pickable: true, onClick: ({object}) => object && onSelect({siteId: object.id, sequence: null}),
    }),
    new PolygonLayer({
      id: 'interaction-towers', data: visiblePhaseBuildings, coordinateSystem, getPolygon: (item) => item.polygon,
      extruded: true, wireframe: false, getElevation: (item) => item.height,
      getFillColor: (item) => {
        const selectedTower = selected?.sequence === item.interaction.sequence
        if (selectedTower) return [178, 184, 188, 255]
        const alpha = semanticZoom === 'journey'
          ? (reachedSites.has(item.site.id) ? 142 : 34)
          : (reachedSequences.has(item.interaction.sequence) ? 250 : 58)
        const shade = Math.round(item.tone * 34)
        return [82 + shade, 86 + shade, 89 + shade, alpha]
      },
      material: {ambient: .38, diffuse: .76, shininess: 48, specularColor: [132, 136, 138]},
      pickable: true,
      onClick: ({object}) => object && onSelect({siteId: object.site.id, sequence: object.interaction.sequence}),
    }),
    new ScatterplotLayer({
      id: 'selected-tower-ring', data: selected?.sequence ? [atlas.buildingBySequence.get(selected.sequence)].filter(Boolean) : [], coordinateSystem,
      getPosition: (item) => [item.center[0], item.center[1], .18], getRadius: 3.5,
      radiusUnits: 'common', filled: false, stroked: true, getLineColor: [...NAV_BLUE_BRIGHT, 255],
      getLineWidth: 2.2, lineWidthUnits: 'pixels',
    }),
    new ScatterplotLayer({
      id: 'traveler-beacon', data: [{position: currentPosition}], coordinateSystem,
      getPosition: (item) => item.position, getRadius: live || playing ? 9 + phase * 8 : 9,
      radiusUnits: 'pixels', filled: false, stroked: true,
      getLineColor: [232, 132, 19, live || playing ? Math.round(175 * (1 - phase)) : 150], getLineWidth: 1.4, lineWidthUnits: 'pixels',
    }),
    new ColumnLayer({
      id: 'journey-traveler', data: [{position: currentPosition}], coordinateSystem,
      getPosition: (item) => item.position, diskResolution: 4, radius: .72, angle: 45,
      extruded: true, getElevation: 1.5, getFillColor: [232, 132, 19, 255],
      stroked: true, getLineColor: [247, 200, 137, 255], getLineWidth: 1, lineWidthUnits: 'pixels',
    }),
    new PathLayer({
      id: 'callout-stems', data: callouts, coordinateSystem,
      getPath: (item) => [item.anchor, item.position], getColor: [152, 158, 160, 150],
      getWidth: 1, widthUnits: 'pixels', capRounded: true,
    }),
    new TextLayer({
      id: 'journey-callouts', data: callouts, coordinateSystem,
      getPosition: (item) => item.position,
      getText: (item) => {
        const heading = `${item.role}  ${String(item.site.order + 1).padStart(2, '0')}/${String(atlas.sites.length).padStart(2, '0')}  ·  ${(KIND_LABEL[item.site.kind] || item.site.kind).toUpperCase()}`
        const title = item.site.title.toUpperCase()
        return `${heading}\n${title}`
      },
      getColor: (item) => item.site.id === currentSite?.id || item.site.id === selectedSite?.id ? [240, 160, 58, 255] : [190, 125, 50, 225],
      getSize: (item) => item.site.id === currentSite?.id || item.site.id === selectedSite?.id ? 10 : 8.3, sizeUnits: 'pixels',
      getTextAnchor: 'middle', getAlignmentBaseline: 'bottom', billboard: true,
      maxWidth: 165, wordBreak: 'break-word', lineHeight: 1.24,
      background: true, getBackgroundColor: (item) => item.site.id === currentSite?.id || item.site.id === selectedSite?.id ? [13, 15, 17, 248] : [13, 15, 17, 222],
      getBorderColor: (item) => item.site.id === currentSite?.id || item.site.order === 0 ? [232, 132, 19, 230] : [95, 101, 104, 190],
      getBorderWidth: (item) => item.site.id === currentSite?.id || item.site.order === 0 ? 1.5 : .75,
      backgroundPadding: [7, 5, 7, 5],
      outlineWidth: 0,
      fontFamily: 'Departure Mono, SFMono-Regular, Menlo, monospace', pickable: true,
      onClick: ({object}) => object && onSelect({siteId: object.site.id, sequence: null}),
    }),
    new TextLayer({
      id: 'tower-numbers', data: semanticZoom === 'evidence' ? phaseBuildings : [], coordinateSystem,
      getPosition: (item) => [item.center[0], item.center[1], item.height + .7],
      getText: (item) => `@${item.interaction.sequence}`,
      getColor: (item) => selected?.sequence === item.interaction.sequence ? [...NAV_BLUE_BRIGHT, 255] : [...colors.ink, 205],
      getSize: 10, sizeUnits: 'pixels', getTextAnchor: 'middle', getAlignmentBaseline: 'bottom', billboard: true,
      background: true, getBackgroundColor: [13, 15, 17, 226], backgroundPadding: [4, 3, 4, 3],
      outlineWidth: 0,
      fontFamily: 'Departure Mono, SFMono-Regular, Menlo, monospace', pickable: true,
      onClick: ({object}) => object && onSelect({siteId: object.site.id, sequence: object.interaction.sequence}),
    }),
  ].filter(Boolean)

  return <DeckGL
    views={new OrbitView({id: 'journey-atlas', controller: {dragRotate: true, inertia: true}, orbitAxis: 'Z', fovy: 48})}
    viewState={viewState} onViewStateChange={({viewState: next}) => setViewState(next)}
    layers={layers} effects={effects} useDevicePixels={Math.min(1.5, window.devicePixelRatio || 1)}
    getCursor={({isDragging, isHovering}) => isDragging ? 'grabbing' : isHovering ? 'pointer' : 'grab'}
    onClick={({object}) => { if (!object) onSelect(null) }}
  >
    <div className="map-compass"><span>N</span><i /></div>
    <div className="map-scale">{semanticZoom.toUpperCase()} SCALE · {semanticZoom === 'journey' ? 'FOLLOW THE BLUE TRAJECTORY' : semanticZoom === 'phase' ? 'ENTERING OUTCOME-BEARING WORK' : 'SELECT A TOWER TO INSPECT EVIDENCE'}</div>
    {selectedSite && <div className="selection-beacon">{String(selectedSite.order + 1).padStart(2, '0')} · {selected?.sequence ? `INTERACTION @${selected.sequence}` : KIND_LABEL[selectedSite.kind]}</div>}
  </DeckGL>
}

function Telemetry({story, open, onToggle}) {
  const latency = Number(story?.telemetry.duration_ms || 0)
  const tokens = Number(story?.telemetry.payload_tokens || 0)
  const avoided = Number(story?.telemetry.tokens_saved || 0)
  const denominator = Math.max(1, tokens + avoided)
  return <section className={`telemetry${open ? ' open' : ''}`}>
    <button className="telemetry-toggle" onClick={onToggle} aria-expanded={open}><span>TELEMETRY</span><strong>{formatNumber(latency)} ms · {formatNumber(tokens)} tok</strong><i>{open ? '×' : '+'}</i></button>
    <div className="telemetry-body">
      <div className="metric"><span>LATENCY</span><strong>{formatNumber(latency)}<small> ms</small></strong><i style={{'--fill': `${Math.min(100, Math.log10(latency + 1) * 24)}%`}} /></div>
      <div className="metric"><span>CONSUMED</span><strong>{formatNumber(tokens)}</strong><i style={{'--fill': `${tokens / denominator * 100}%`}} /></div>
      <div className="metric saved"><span>AVOIDED</span><strong>{formatNumber(avoided)}</strong><i style={{'--fill': `${avoided / denominator * 100}%`}} /></div>
    </div>
  </section>
}

const WHY = {
  intent: 'Establish the requested outcome before choosing tools or taking effects.',
  decision: 'Choose the next route while preserving the user’s constraints and authority.',
  capability: 'Prepare the capability needed to advance the outcome.',
  authority: 'Confirm that the next effect is allowed before it occurs.',
  phase: 'Group related commands into one understandable stage of the outcome.',
  effect: 'Perform outcome-bearing work through the selected capability.',
  evidence: 'Check the observed result before treating the work as complete.',
  blocker: 'Expose what prevented progress instead of hiding it behind retries.',
  recovery: 'Re-enter the useful path with verified corrective evidence.',
  milestone: 'Record a meaningful boundary in the completed journey.',
  artifact: 'Turn the verified work into something the user can use.',
  play_candidate: 'Compress the successful trajectory into a reusable procedure.',
  play: 'Make the verified procedure available for future runs.',
}

function JourneyGuide({story, interactions, replay, playing, frozen, onOpen}) {
  if (!story?.chapters?.length) return null
  const playbackIndex = Math.max(0, Math.min(story.chapters.length - 1, Math.ceil(replay * story.chapters.length) - 1))
  const liveIndex = Math.max(0, story.chapters.findIndex((chapter) => chapter.id === story.current_chapter))
  const restingIndex = story.state === 'active' ? liveIndex : story.chapters.length - 1
  const index = playing || replay < .999 ? playbackIndex : restingIndex
  const current = story.chapters[index]
  const next = story.chapters[index + 1]
  const records = interactions?.sites?.[current.id] || []
  const capabilities = [...new Set(records.map(capabilityName))]
  return <aside className={`journey-guide${frozen ? ' frozen' : ''}`} onClick={() => onOpen({siteId: current.id, sequence: null})}>
    <div className="guide-kicker"><i />{playing ? 'TRAVERSING' : frozen ? 'FROZEN VANTAGE' : story.state === 'active' ? 'NOW' : 'RECORDED JOURNEY'}<span>{String(index + 1).padStart(2, '0')} / {String(story.chapters.length).padStart(2, '0')}</span></div>
    <h1>{current.title}</h1>
    <p><strong>{KIND_LABEL[current.kind] || current.kind} → {WORLD_ROLE[current.kind] || 'journey stage'}.</strong> {WORLD_STORY[current.kind] || WHY[current.kind] || 'Advance the requested outcome while preserving evidence.'}</p>
    <dl>
      <dt>HAPPENED</dt><dd>{current.detail || current.title}</dd>
      <dt>STRUCTURES</dt><dd>{records.length ? `${records.length} illuminated · select any callout for evidence` : 'No tool interactions recorded at this vantage'}</dd>
      {capabilities.length > 0 && <><dt>EQUIPPED</dt><dd>{capabilities.join(' · ')}</dd></>}
      <dt>NEXT</dt><dd>{next?.title || 'Deliver the verified outcome'}</dd>
    </dl>
    <div className="guide-progress"><i style={{width: `${Math.max(2, (index + 1) / story.chapters.length * 100)}%`}} /></div>
  </aside>
}

const WORLD_MODEL_KINDS = ['intent', 'capability', 'authority', 'effect', 'evidence', 'blocker', 'recovery', 'milestone', 'artifact', 'play_candidate']

function WorldModel({open, onToggle}) {
  return <>
    <button className="world-model-toggle" onClick={onToggle} aria-expanded={open}>◇ WORLD MODEL</button>
    <aside className={`world-model${open ? ' open' : ''}`}>
      <div className="panel-heading"><span>HOW TO READ THIS WORLD</span><button onClick={onToggle}>×</button></div>
      <p>The same spatial vocabulary repeats across every journey. Shape tells you what role a place has before you inspect its evidence.</p>
      <dl>{WORLD_MODEL_KINDS.map((kind) => <React.Fragment key={kind}>
        <dt><i className={`world-glyph ${kind}`} />{KIND_LABEL[kind]}</dt>
        <dd><strong>{WORLD_ROLE[kind]}</strong><span>{WORLD_STORY[kind]}</span></dd>
      </React.Fragment>)}</dl>
      <div className="world-model-note"><i className="route-mark" />The amber route is the agent’s path. Structures around a stop are recorded interactions; select one to inspect its redacted exchange.</div>
    </aside>
  </>
}

function capabilityName(record) {
  if (record.provider) return record.provider
  const operation = String(record.operation || 'local')
  return operation.split(/[\s.]/)[0] || 'local'
}

function CapabilityRail({story, interactions, replay, onJump}) {
  const chapterIndex = Math.max(0, Math.min(story.chapters.length - 1, Math.floor(replay * Math.max(1, story.chapters.length - 1) + .001)))
  const currentChapter = story.chapters[chapterIndex]
  const activeNames = new Set((interactions?.sites?.[currentChapter?.id] || []).map(capabilityName))
  const entries = []
  const byName = new Map()
  story.chapters.forEach((chapter) => {
    for (const record of interactions?.sites?.[chapter.id] || []) {
      const name = capabilityName(record)
      const existing = byName.get(name)
      const entry = existing || {name, first: chapter.order, last: chapter.order, count: 0}
      entry.first = Math.min(entry.first, chapter.order)
      entry.last = Math.max(entry.last, chapter.order)
      entry.count += 1
      byName.set(name, entry)
    }
  })
  for (const entry of byName.values()) entries.push(entry)
  entries.sort((left, right) => {
    const leftActive = activeNames.has(left.name) ? 0 : 1
    const rightActive = activeNames.has(right.name) ? 0 : 1
    return leftActive - rightActive || left.first - right.first || left.name.localeCompare(right.name)
  })
  if (!entries.length) return null
  return <aside className="capability-rail">
    <h2>CAPABILITIES</h2><p>What the agent can use on this journey</p>
    <div>{entries.slice(0, 8).map((entry) => {
      const active = activeNames.has(entry.name)
      const used = entry.first <= chapterIndex
      return <button key={entry.name} className={active ? 'active' : used ? 'used' : ''} onClick={() => onJump(entry.first)}>
        <i /><span>{entry.name}</span><small>{active ? 'IN USE' : used ? 'USED' : 'AVAILABLE'}</small><em>{entry.count}</em>
      </button>
    })}</div>
  </aside>
}

function App() {
  const [index, setIndex] = useState(null)
  const [workspace, setWorkspace] = useState('')
  const [story, setStory] = useState(null)
  const [scene, setScene] = useState(null)
  const [interactions, setInteractions] = useState(null)
  const [selected, setSelected] = useState(null)
  const [exchange, setExchange] = useState(null)
  const [replay, setReplay] = useState(1)
  const [playing, setPlaying] = useState(false)
  const [observing, setObserving] = useState(true)
  const [snapshotCountdown, setSnapshotCountdown] = useState(10)
  const [lastSnapshotAt, setLastSnapshotAt] = useState(null)
  const [fitSignal, setFitSignal] = useState(0)
  const [mode, setMode] = useState('follow')
  const [message, setMessage] = useState('Loading journeys')
  const [loadError, setLoadError] = useState('')
  const [journeysOpen, setJourneysOpen] = useState(false)
  const [telemetryOpen, setTelemetryOpen] = useState(false)
  const [worldModelOpen, setWorldModelOpen] = useState(false)
  const playback = useRef(null)

  const loadIndex = useCallback(async () => {
    const response = await fetch(api('/api/workspaces'), {cache: 'no-store'})
    if (!response.ok) throw new Error(`Workspace index unavailable (${response.status})`)
    const value = await response.json()
    setLoadError('')
    setIndex(value)
    setWorkspace((current) => current || value.selected_id || value.workspaces[0]?.id || '')
    return value
  }, [])

  const loadJourney = useCallback(async (id, quiet = false) => {
    if (!quiet) setMessage('Loading journey map')
    const [storyResponse, sceneResponse, interactionResponse] = await Promise.all([
      fetch(api('/api/story', {workspace: id}), {cache: 'no-store'}),
      fetch(api('/api/scene', {workspace: id}), {cache: 'no-store'}),
      fetch(api('/api/interactions', {workspace: id}), {cache: 'no-store'}),
    ])
    if (!storyResponse.ok || !sceneResponse.ok || !interactionResponse.ok) throw new Error('Journey map is unavailable')
    const [nextStory, nextScene, nextInteractions] = await Promise.all([storyResponse.json(), sceneResponse.json(), interactionResponse.json()])
    setStory(nextStory)
    setScene(nextScene)
    setInteractions(nextInteractions)
    setSelected((current) => nextStory.chapters.some((chapter) => chapter.id === current?.siteId) ? current : null)
    if (!quiet) setReplay(nextStory.state === 'active' ? 1 : 0)
    if (!quiet) setObserving(true)
    if (!quiet) setMessage(nextStory.state === 'active' ? 'Live journey connected' : 'Recorded journey loaded')
    setLastSnapshotAt(Date.now())
  }, [])

  async function choose(item) {
    try {
      setPlaying(false)
      setObserving(true)
      playback.current = null
      setSelected(null)
      setMode('follow')
      if (!item.graph_ready && !item.projectable) {
        setMessage('This historical capture no longer has its Rote workspace evidence, so no map can be projected')
        return
      }
      if (!item.graph_ready) {
        setMessage('Projecting first journey snapshot')
        const start = await fetch(api('/api/project', {workspace: item.id}), {method: 'POST', cache: 'no-store'})
        if (!start.ok && start.status !== 202) throw new Error(`Projection could not start (${start.status})`)
        const deadline = Date.now() + 10000
        let ready = false
        while (Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 240))
          const next = await loadIndex()
          ready = Boolean(next.workspaces.find((candidate) => candidate.id === item.id)?.graph_ready)
          if (ready) break
        }
        if (!ready) throw new Error('First map is still building; select it again in a moment')
      }
      await loadJourney(item.id)
      setWorkspace(item.id)
      setJourneysOpen(false)
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
  }

  useEffect(() => {
    loadIndex().catch((error) => {
      setMessage(error.message)
      setLoadError(error.message)
    })
  }, [loadIndex])
  useEffect(() => {
    if (!workspace) return undefined
    loadJourney(workspace).catch((error) => setMessage(error.message))
    const events = new EventSource(api('/api/events', {workspace}))
    events.addEventListener('journey', () => {
      loadJourney(workspace, true).catch(() => {})
      loadIndex().catch(() => {})
      setSnapshotCountdown(10)
    })
    events.onerror = () => setMessage('Reconnecting to live journey')
    return () => events.close()
  }, [loadIndex, loadJourney, workspace])

  useEffect(() => {
    if (!workspace) return undefined
    let remaining = 10
    setSnapshotCountdown(remaining)
    const interval = window.setInterval(() => {
      remaining -= 1
      if (remaining <= 0) {
        remaining = 10
        loadIndex()
          .then((nextIndex) => {
            const currentWorkspace = nextIndex.workspaces.find((item) => item.id === workspace)
            if (currentWorkspace?.capture_state === 'active') {
              return loadJourney(workspace, true)
            }
            return undefined
          })
          .catch(() => {})
      }
      setSnapshotCountdown(remaining)
    }, 1000)
    return () => window.clearInterval(interval)
  }, [loadIndex, loadJourney, workspace])

  useEffect(() => {
    if (!selected?.sequence || !workspace) {
      setExchange(null)
      return undefined
    }
    const abort = new AbortController()
    setExchange({loading: true})
    fetch(api('/api/exchange', {workspace, sequence: selected.sequence}), {cache: 'no-store', signal: abort.signal})
      .then((response) => {
        if (!response.ok) throw new Error(`Evidence unavailable (${response.status})`)
        return response.json()
      })
      .then(setExchange)
      .catch((error) => { if (error.name !== 'AbortError') setExchange({error: error.message}) })
    return () => abort.abort()
  }, [selected?.sequence, workspace])

  useEffect(() => {
    if (!selected?.sequence) return
    setTelemetryOpen(false)
    setWorldModelOpen(false)
  }, [selected?.sequence])

  useEffect(() => {
    if (!playing || !story) return undefined
    let frame = 0
    const count = story.chapters.length
    const intervals = Math.max(1, count - 1)
    const dwellMs = 2800
    const travelMs = 4200
    const cycleMs = dwellMs + travelMs
    const startingUnits = (playback.current?.from || 0) * intervals
    const startingStage = Math.min(intervals, Math.floor(startingUnits))
    const startingFraction = startingUnits - startingStage
    const timelineOffset = startingStage * cycleMs + (startingFraction > .001 ? dwellMs + startingFraction * travelMs : 0)
    const finishAt = intervals * cycleMs + dwellMs
    const tick = (time) => {
      const state = playback.current
      if (!state) return
      const timeline = timelineOffset + time - state.started
      const stage = Math.min(intervals, Math.floor(timeline / cycleMs))
      const withinStage = timeline - stage * cycleMs
      const rawTravel = stage >= intervals ? 0 : Math.max(0, Math.min(1, (withinStage - dwellMs) / travelMs))
      const travel = rawTravel * rawTravel * (3 - 2 * rawTravel)
      const progress = Math.min(1, (stage + travel) / intervals)
      setReplay(progress)
      if (timeline >= finishAt) {
        playback.current = null
        setPlaying(false)
        setObserving(true)
        setMessage('Journey traversal complete')
        return
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, story])

  function togglePlayback() {
    if (playing) {
      playback.current = null
      setPlaying(false)
      setObserving(true)
      setMessage('Vantage frozen · all local structures are available for inspection')
      return
    }
    const from = replay >= .999 ? 0 : replay
    setSelected(null)
    setObserving(false)
    setReplay(from)
    setFitSignal((value) => value + 1)
    playback.current = {from, started: performance.now()}
    setPlaying(true)
    setMessage('Following the agent trajectory')
  }

  function jumpToChapter(index) {
    setPlaying(false)
    setObserving(true)
    playback.current = null
    setSelected(null)
    const denominator = Math.max(1, (story?.chapters.length || 1) - 1)
    setReplay(index / denominator)
    setMessage(`Jumped to stage ${index + 1}`)
  }

  const selectVantage = useCallback((value) => {
    if (value) {
      playback.current = null
      setPlaying(false)
      setObserving(true)
      setMessage(value.sequence ? `Inspecting interaction @${value.sequence}` : 'Situational awareness opened')
    }
    setSelected(value)
  }, [])

  const chapter = story?.chapters.find((item) => item.id === selected?.siteId)
  const interaction = selected?.sequence
    ? interactions?.sites?.[selected.siteId]?.find((item) => item.sequence === selected.sequence)
    : null
  const selectedWorkspace = index?.workspaces.find((item) => item.id === workspace)
  const liveCapture = selectedWorkspace?.capture_state === 'active'
  const liveActivity = Boolean(liveCapture && selectedWorkspace?.active_recently)
  const status = liveActivity ? 'LIVE' : liveCapture ? 'LIVE · IDLE' : 'HISTORY'
  const replayChapter = story ? Math.min(story.chapters.length - 1, Math.floor(replay * Math.max(1, story.chapters.length - 1) + .001)) : 0
  const frozen = mode === 'follow' && observing && !playing

  const showEvidencePanel = chapter && (mode !== 'follow' || interaction)

  return <main className={`dark mode-${mode}${frozen ? ' is-frozen' : ''}`}>
    <section className="atlas-stage">
      {story && scene && interactions
        ? mode === 'follow'
          ? <JourneyWorld story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} selected={selected} onSelect={selectVantage} />
          : <Cartography story={story} scene={scene} interactions={interactions} replay={replay} playing={playing} audit={mode === 'audit'} selected={selected} onSelect={setSelected} fitSignal={fitSignal} />
        : loadError
          ? <div className="loading failed"><strong>JOURNEY CONNECTION LOST</strong><span>{loadError}</span><code>./scripts/bin/play-journey view --active</code></div>
          : <div className="loading"><i />CONSTRUCTING JOURNEY ATLAS</div>}
    </section>
    <header>
      <button className="brand" onClick={() => setJourneysOpen((value) => !value)}><strong>PLAY CARTOGRAPHY</strong><small>{mode === 'follow' ? 'JOURNEY FOLLOW' : mode === 'audit' ? 'EVIDENCE AUDIT' : 'JOURNEY ATLAS'}</small></button>
      <div className={`header-title${liveActivity ? ' live' : ''}`}><i />{status}{liveCapture && <b>NEXT SNAPSHOT {String(snapshotCountdown).padStart(2, '0')}s</b>}<span>{story?.outcome || 'Captured exploration'}</span></div>
      <div className="header-actions">
        <button className={mode === 'follow' ? 'active' : ''} onClick={() => { setMode('follow'); setSelected(null) }}>FOLLOW</button>
        <button className={mode === 'atlas' ? 'active' : ''} onClick={() => { setMode('atlas'); setSelected(null); setFitSignal((value) => value + 1) }}>ATLAS</button>
        <button className={mode === 'audit' ? 'active' : ''} onClick={() => { setMode('audit'); setSelected(null); setFitSignal((value) => value + 1) }}>AUDIT</button>
        {mode !== 'follow' && <button onClick={() => setFitSignal((value) => value + 1)}>FIT</button>}
      </div>
    </header>
    <aside className={`journey-drawer${journeysOpen ? ' open' : ''}`}>
      <div className="panel-heading"><span>JOURNEY ARCHIVE</span><button onClick={() => setJourneysOpen(false)}>×</button></div>
      <div className="workspace-list">{index?.workspaces.map((item) => {
        const unavailable = !item.graph_ready && !item.projectable
        const stateLabel = workspace === item.id
          ? item.active_recently ? 'VIEWING · LIVE' : item.capture_state === 'active' ? 'VIEWING · IDLE' : 'VIEWING'
          : item.graph_ready && item.active_recently
            ? 'LIVE'
            : item.graph_ready && item.capture_state === 'active'
              ? 'IDLE'
            : item.graph_ready
              ? 'RECORDED'
              : item.projectable
                ? 'BUILD MAP'
                : 'NO EVIDENCE'
        const coverage = item.graph_ready ? `${item.nodes} sites · ${item.edges} routes` : item.projectable ? 'projection available' : 'workspace unavailable'
        return <button key={item.id} disabled={unavailable} className={`workspace-card${workspace === item.id ? ' active' : ''}${item.active_recently ? ' live' : ''}`} onClick={() => choose(item)}>
        <i /><span>{item.intent}</span>
        <small><b>{stateLabel}</b><em>{coverage}</em></small>
      </button>})}</div>
      <p>The atlas is a semantic projection. Every canonical node, edge, command and evidence reference remains preserved below it.</p>
    </aside>
    <aside className={`landmark-panel${showEvidencePanel ? ' visible' : ''}`}>
      {showEvidencePanel && <>
        <div className="panel-heading"><span>{interaction ? `INTERACTION @${interaction.sequence}` : `DISTRICT ${String(chapter.order + 1).padStart(2, '0')}`}</span><button onClick={() => setSelected(null)}>×</button></div>
        <span className="kind">{KIND_LABEL[chapter.kind] || chapter.kind}</span>
        <h1>{chapter.title}</h1><p>{chapter.detail}</p>
        <div className="meaning"><strong>WHY THIS STEP EXISTS</strong><span>{MAP_MEANING[chapter.kind] || 'Advances the requested outcome while preserving evidence.'}</span></div>
        {interaction ? <>
          <dl>
            <dt>OPERATION</dt><dd>{interaction.operation}</dd><dt>STATE</dt><dd>{interaction.status}</dd>
            <dt>LATENCY</dt><dd>{formatNumber(interaction.duration_ms)} ms</dd><dt>TOKENS</dt><dd>{formatNumber(interaction.tokens)}</dd>
            <dt>AVOIDED</dt><dd>{formatNumber(interaction.tokens_saved)}</dd>
            {interaction.provider && <><dt>PROVIDER</dt><dd>{interaction.provider}</dd></>}
          </dl>
          <section className="exchange">
            {exchange?.loading && <p>LOADING OWNER-PRIVATE EVIDENCE…</p>}
            {exchange?.error && <p>{exchange.error}</p>}
            {exchange?.schema && <>
              <div className="evidence-note">REDACTED DISPLAY COPY{exchange.truncated ? ' · TRUNCATED' : ''}</div>
              <h2>REQUEST</h2><pre>{JSON.stringify(exchange.request, null, 2)}</pre>
              <h2>RESPONSE</h2><pre>{JSON.stringify(exchange.response, null, 2)}</pre>
            </>}
          </section>
        </> : <>
          <dl>
            <dt>STATE</dt><dd>{chapter.status}</dd><dt>TOWERS</dt><dd>{interactions?.sites?.[chapter.id]?.length || 0}</dd>
            <dt>LATENCY</dt><dd>{formatNumber(chapter.telemetry.duration_ms)} ms</dd><dt>TOKENS</dt><dd>{formatNumber(chapter.telemetry.payload_tokens)}</dd>
            <dt>AVOIDED</dt><dd>{formatNumber(chapter.telemetry.tokens_saved)}</dd>
            {chapter.provider && <><dt>PROVIDER</dt><dd>{chapter.provider}</dd></>}
          </dl>
          <details><summary>EVIDENCE REFERENCES</summary><pre>{Object.entries(chapter.evidence).filter(([, values]) => values?.length).map(([key, values]) => `${key}: ${values.join(', ')}`).join('\n') || 'No opaque evidence references recorded'}</pre></details>
        </>}
      </>}
    </aside>
    {mode === 'follow' && story && interactions && <JourneyGuide story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} onOpen={selectVantage} />}
    {mode === 'follow' && story && interactions && <CapabilityRail story={story} interactions={interactions} replay={replay} onJump={jumpToChapter} />}
    <WorldModel open={worldModelOpen} onToggle={() => setWorldModelOpen((value) => !value)} />
    <Telemetry story={story} open={telemetryOpen} onToggle={() => setTelemetryOpen((value) => !value)} />
    <footer>
      <button onClick={() => setJourneysOpen((value) => !value)}>☷ JOURNEYS</button>
      <span>{story ? `${story.audit.canonical_nodes} STAGES · ${interactions?.total || 0} INTERACTIONS · GEN ${story.graph_generation}` : 'WAITING FOR GRAPH'}</span>
      <div className="replay"><button className={playing ? 'playing' : frozen ? 'frozen' : ''} onClick={togglePlayback}>{playing ? 'Ⅱ FREEZE' : frozen ? '▶ RESUME' : '▶ PLAY'}</button><div className="replay-track"><input aria-label="Journey replay" type="range" min="0" max="1" step="0.002" value={replay} onChange={(event) => { setPlaying(false); setObserving(true); playback.current = null; setReplay(Number(event.target.value)); setMessage('Vantage frozen · inspect the illuminated structures') }} /><div className="chapter-markers">{story?.chapters.map((item, itemIndex) => <button key={item.id} className={itemIndex === replayChapter ? 'current' : itemIndex < replayChapter ? 'reached' : ''} style={{left: `${itemIndex / Math.max(1, story.chapters.length - 1) * 100}%`}} onClick={() => jumpToChapter(itemIndex)} aria-label={`Freeze at stage ${itemIndex + 1}: ${item.title}`} />)}</div></div><em>{story ? `${replayChapter + 1}/${story.chapters.length}` : '0/0'}</em></div>
      <span className="footer-message">{frozen ? `FROZEN VANTAGE · ${message}` : lastSnapshotAt && liveCapture ? `SNAPSHOT ${new Date(lastSnapshotAt).toLocaleTimeString()} · ${message}` : message}</span>
    </footer>
  </main>
}

createRoot(document.getElementById('journey-root')).render(<App />)
