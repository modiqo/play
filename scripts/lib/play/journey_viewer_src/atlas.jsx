import React, {useEffect, useMemo, useRef, useState} from 'react'
import DeckGL from '@deck.gl/react'
import {AmbientLight, COORDINATE_SYSTEM, DirectionalLight, LightingEffect, LinearInterpolator, OrbitView} from '@deck.gl/core'
import {ColumnLayer, PathLayer, PolygonLayer, ScatterplotLayer, TextLayer} from '@deck.gl/layers'
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


