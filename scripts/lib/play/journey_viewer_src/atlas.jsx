import React, {useEffect, useMemo, useRef, useState} from 'react'
import DeckGL from '@deck.gl/react'
import {AmbientLight, COORDINATE_SYSTEM, DirectionalLight, LightingEffect, LinearInterpolator, OrbitView} from '@deck.gl/core'
import {ColumnLayer, PathLayer, PolygonLayer, ScatterplotLayer, TextLayer} from '@deck.gl/layers'
import {SimpleMeshLayer} from '@deck.gl/mesh-layers'
import {IcoSphereGeometry} from '@luma.gl/engine'
import {DARK, NAV_BLUE, NAV_BLUE_BRIGHT, buildAtlas, fitView, interpolatePath, rgba} from './atlas-model.js'
import {KIND_LABEL} from './semantics.js'

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

export default function Cartography({story, scene, interactions, replay, playing, audit, selected, onSelect, fitSignal}) {
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
    const bead = selected.sequence ? atlas.beadBySequence.get(selected.sequence) : null
    const site = atlas.sites.find((item) => item.id === selected.siteId)
    if (!bead && !site) return
    const center = bead?.center || site.center
    setViewState((current) => ({
      ...current,
      target: [center[0], center[1], bead ? center[2] : 0],
      zoom: bead ? Math.max(5.2, fittedView.zoom + 3.1) : Math.max(4.2, fittedView.zoom + 2.1),
      rotationX: bead ? 66 : 60,
      rotationOrbit: 0,
      transitionDuration: 850,
      transitionInterpolator: new LinearInterpolator(['target', 'zoom', 'rotationX', 'rotationOrbit']),
    }))
  }, [atlas, fittedView.zoom, selected?.sequence, selected?.siteId])

  const zoomDelta = viewState.zoom - fittedView.zoom
  const semanticZoom = selected?.sequence ? 'evidence' : selected?.siteId ? 'phase' : zoomDelta < .82 ? 'journey' : zoomDelta < 2.05 ? 'phase' : 'evidence'
  const visibleSiteCount = atlas.sites.length
    ? Math.min(atlas.sites.length, Math.floor(replay * Math.max(1, atlas.sites.length - 1) + .001) + 1)
    : 0
  const reachedSites = new Set(atlas.sites.slice(0, visibleSiteCount).map((site) => site.id))
  const pathCount = Math.max(1, Math.ceil(replay * atlas.semanticPath.length))
  const visiblePath = atlas.semanticPath.slice(0, pathCount)
  const currentPosition = interpolatePath(atlas.semanticPath, replay)
  const selectedSite = atlas.sites.find((site) => site.id === selected?.siteId)
  const replaySite = atlas.sites[Math.max(0, visibleSiteCount - 1)]
  const currentSite = playing || story.state !== 'active'
    ? replaySite
    : (atlas.sites.find((site) => site.id === story.current_chapter) || replaySite)
  const focusSite = selectedSite || currentSite
  const phaseBeads = semanticZoom === 'journey'
    ? atlas.beads
    : atlas.beads.filter((bead) => bead.site.id === focusSite?.id)
  const phaseThreads = semanticZoom === 'journey'
    ? atlas.threads
    : atlas.threads.filter((thread) => thread.site.id === focusSite?.id)
  const phaseHalos = semanticZoom === 'journey'
    ? atlas.halos
    : atlas.halos.filter((halo) => halo.bead.site.id === focusSite?.id)
  const focusBeads = atlas.beads
    .filter((bead) => bead.site.id === focusSite?.id)
    .sort((left, right) => left.interaction.sequence - right.interaction.sequence)
  const selectedBeadIndex = focusBeads.findIndex((bead) => bead.interaction.sequence === selected?.sequence)
  const adjacentSequences = new Set(selectedBeadIndex < 0 ? [] : focusBeads
    .slice(Math.max(0, selectedBeadIndex - 1), selectedBeadIndex + 2)
    .map((bead) => bead.interaction.sequence))
  const focusDistricts = focusSite ? atlas.districts.filter((district) => district.site.id === focusSite.id) : []
  const focusContours = focusSite ? atlas.contours.filter((contour) => contour.site.id === focusSite.id) : []
  const focusStreets = focusSite ? atlas.streets.filter((street) => street.id.includes(focusSite.id)) : []
  useEffect(() => {
    if (!playing) return
    setViewState((current) => ({
      ...current, ...fittedView,
      rotationX: 62,
      rotationOrbit: -34,
      zoom: fittedView.zoom + .14,
      transitionDuration: 900,
      transitionInterpolator: new LinearInterpolator(['target', 'zoom', 'rotationX', 'rotationOrbit']),
    }))
  }, [fittedView, playing])
  const ambient = useMemo(() => new AmbientLight({color: [255, 255, 255], intensity: 1.15}), [])
  const sun = useMemo(() => new DirectionalLight({color: [255, 255, 255], intensity: 2.15, direction: [-3, -7, -10]}), [])
  const effects = useMemo(() => [new LightingEffect({ambient, sun})], [ambient, sun])
  const beadMesh = useMemo(() => new IcoSphereGeometry({id: 'atlas-event-bead', radius: 1, iterations: 3}), [])
  const coordinateSystem = COORDINATE_SYSTEM.CARTESIAN
  const terrainDistricts = semanticZoom === 'journey' ? atlas.districts : focusDistricts
  const beadAlpha = (bead, base = 1) => {
    if (selected?.sequence) {
      if (selected.sequence === bead.interaction.sequence) return Math.round(245 * base)
      if (adjacentSequences.has(bead.interaction.sequence)) return Math.round(112 * base)
      return Math.round(15 * base)
    }
    if (semanticZoom !== 'journey') return Math.round(178 * base)
    return Math.round((reachedSites.has(bead.site.id) ? 118 : 22) * base)
  }
  const layers = [
    new PolygonLayer({id: 'atlas-ground', data: [{polygon: atlas.ground}], coordinateSystem, getPolygon: (item) => item.polygon, getFillColor: rgba(colors.ground), filled: true, stroked: false, extruded: false}),
    new PathLayer({
      id: 'terrain-grid', data: atlas.gridLines, coordinateSystem, getPath: (item) => item.path,
      getColor: [...colors.street, 26], getWidth: .65, widthUnits: 'pixels',
    }),
    new PolygonLayer({
      id: 'semantic-districts', data: terrainDistricts, coordinateSystem, getPolygon: (item) => item.polygon,
      getFillColor: (item) => [17, 21, 24, item.site.id === focusSite?.id ? 176 : reachedSites.has(item.site.id) ? 112 : 52],
      filled: true, stroked: true,
      getLineColor: (item) => item.site.id === focusSite?.id ? [...NAV_BLUE, 150] : [...colors.street, reachedSites.has(item.site.id) ? 74 : 28],
      getLineWidth: (item) => item.site.id === focusSite?.id ? 1.5 : .65,
      lineWidthUnits: 'pixels', extruded: false, pickable: true,
      onClick: ({object}) => object && onSelect({siteId: object.site.id, sequence: null}),
    }),
    new PathLayer({
      id: 'terrain-contours', data: semanticZoom === 'journey' ? [] : focusContours, coordinateSystem, getPath: (item) => item.path,
      getColor: (item) => [...colors.street, 74 - item.ring * 12],
      getWidth: .75, widthUnits: 'pixels', jointRounded: true, capRounded: true,
    }),
    new PathLayer({id: 'temporal-spine-bed', data: semanticZoom === 'journey' ? [] : focusStreets, coordinateSystem, getPath: (item) => item.path, getColor: colors.streetCore, getWidth: 4.4, widthUnits: 'pixels', jointRounded: true, capRounded: true}),
    new PathLayer({id: 'temporal-spine', data: semanticZoom === 'journey' ? [] : focusStreets, coordinateSystem, getPath: (item) => item.path, getColor: colors.street, getWidth: .9, widthUnits: 'pixels', jointRounded: true, capRounded: true}),
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
      id: 'event-thread-shadow', data: phaseThreads, coordinateSystem, getPath: (item) => item.path,
      getColor: [3, 5, 6, 210], getWidth: semanticZoom === 'journey' ? 2.6 : 4.2,
      widthUnits: 'pixels', jointRounded: true, capRounded: true,
    }),
    new PathLayer({
      id: 'event-threads', data: phaseThreads, coordinateSystem, getPath: (item) => item.path,
      getColor: (item) => {
        const selectedThread = selected?.sequence && (
          adjacentSequences.has(item.source.interaction.sequence) && adjacentSequences.has(item.target.interaction.sequence)
        )
        if (selected?.sequence) return [...NAV_BLUE_BRIGHT, selectedThread ? 172 : 12]
        if (semanticZoom === 'journey') return [...NAV_BLUE, reachedSites.has(item.site.id) ? 76 : 15]
        return [...NAV_BLUE, 112]
      },
      getWidth: semanticZoom === 'evidence' ? 1.45 : .85,
      widthUnits: 'pixels', jointRounded: true, capRounded: true,
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
    new SimpleMeshLayer({
      id: 'event-beads', data: phaseBeads, coordinateSystem, getPosition: (item) => item.center,
      mesh: beadMesh, sizeScale: semanticZoom === 'journey' ? 2.1 : 1.35,
      getScale: (item) => [item.radius, item.radius, item.radius],
      getColor: (item) => {
        const shade = Math.round(item.tone * 26)
        return [72 + shade, 82 + shade, 86 + shade, beadAlpha(item)]
      },
      material: {ambient: .28, diffuse: .72, shininess: 108, specularColor: [232, 240, 241]},
      pickable: true,
      onClick: ({object}) => object && onSelect({siteId: object.site.id, sequence: object.interaction.sequence}),
    }),
    new SimpleMeshLayer({
      id: 'event-bead-glints', data: phaseBeads, coordinateSystem,
      mesh: beadMesh, sizeScale: semanticZoom === 'journey' ? 2.1 : 1.35,
      getPosition: (item) => [
        item.center[0] - item.radius * .34,
        item.center[1] - item.radius * .12,
        item.center[2] + item.radius * .58,
      ],
      getScale: (item) => [item.radius * .105, item.radius * .105, item.radius * .105],
      getColor: (item) => [244, 249, 249, beadAlpha(item, .9)],
      material: {ambient: .88, diffuse: .12, shininess: 128, specularColor: [255, 255, 255]},
      pickable: false,
    }),
    new PathLayer({
      id: 'event-latency-halos', data: phaseHalos, coordinateSystem, getPath: (item) => item.path,
      getColor: (item) => [...NAV_BLUE_BRIGHT, beadAlpha(item.bead, selected?.sequence === item.bead.interaction.sequence ? .9 : .54)],
      getWidth: selected?.sequence ? 1.5 : 1, widthUnits: 'pixels', jointRounded: true, capRounded: true,
    }),
    new ScatterplotLayer({
      id: 'selected-bead-ring', data: selected?.sequence ? [atlas.beadBySequence.get(selected.sequence)].filter(Boolean) : [], coordinateSystem,
      getPosition: (item) => item.center, getRadius: (item) => item.radius + .24,
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
    new TextLayer({
      id: 'bead-numbers', data: selected?.sequence ? phaseBeads.filter((item) => adjacentSequences.has(item.interaction.sequence)) : [], coordinateSystem,
      getPosition: (item) => [item.center[0], item.center[1] - item.radius * .08, item.center[2] + item.radius * .08],
      getText: (item) => `@${item.interaction.sequence}`,
      getColor: (item) => selected?.sequence === item.interaction.sequence ? [...NAV_BLUE_BRIGHT, 255] : [...colors.ink, 205],
      getSize: 9, sizeUnits: 'pixels', getTextAnchor: 'middle', getAlignmentBaseline: 'center', billboard: true,
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
    <div className="map-scale">{semanticZoom.toUpperCase()} SCALE · {semanticZoom === 'journey' ? 'COMPACT SPATIO-TEMPORAL TERRAIN' : semanticZoom === 'phase' ? 'EVENT BEADS FOLLOW TIME LEFT TO RIGHT' : 'SELECT A GLASS BEAD TO INSPECT EVIDENCE'}</div>
    {selectedSite && <div className="selection-beacon">{String(selectedSite.order + 1).padStart(2, '0')} · {selected?.sequence ? `INTERACTION @${selected.sequence}` : KIND_LABEL[selectedSite.kind]}</div>}
  </DeckGL>
}
