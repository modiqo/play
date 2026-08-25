import React, {useEffect, useMemo, useRef} from 'react'
import * as THREE from 'three'
import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js'
import {RoundedBoxGeometry} from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import {buildAtlas} from './atlas-model.js'
import {buildAtlasCityPlan, sampleAtlasCityRoute} from './atlas-city-plan.mjs'
import {adaptiveRenderPixelRatio} from './render-quality.mjs'
import {KIND_LABEL} from './semantics.js'
import {formatNumber} from './format.js'
import {createDriveFixture, updateDriveFixture} from './drive-world-elements.js'

const BLUE = 0x159dff
const BLUE_BRIGHT = 0x75cfff
const CITY = 0x697176
const CITY_DARK = 0x40484d
const RED = 0xff5a52

function signalMaterial(color, opacity = 1) {
  return new THREE.MeshBasicMaterial({
    color,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity >= 1,
    toneMapped: false,
  })
}

function cityMaterial(color, options = {}) {
  const opacity = options.opacity ?? 1
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? .72,
    metalness: options.metalness ?? .08,
    emissive: options.emissive ?? 0x000000,
    emissiveIntensity: options.emissiveIntensity ?? 0,
    transparent: opacity < 1,
    opacity,
    depthWrite: opacity >= 1,
    dithering: true,
  })
}

function addMesh(group, geometry, material, position = [0, 0, 0], rotation = [0, 0, 0]) {
  const object = new THREE.Mesh(geometry, material)
  object.position.set(...position)
  object.rotation.set(...rotation)
  object.castShadow = true
  object.receiveShadow = true
  group.add(object)
  return object
}

function routeCurve(route) {
  return new THREE.CatmullRomCurve3(route.map((point) => new THREE.Vector3(...point)), false, 'catmullrom', .32)
}

function roadGeometry(curve, width, segments) {
  const positions = []
  const indices = []
  const up = new THREE.Vector3(0, 1, 0)
  const normal = new THREE.Vector3()
  for (let index = 0; index <= segments; index += 1) {
    const amount = index / segments
    const point = curve.getPointAt(amount)
    const tangent = curve.getTangentAt(amount).setY(0).normalize()
    normal.crossVectors(up, tangent).normalize().multiplyScalar(width / 2)
    positions.push(point.x + normal.x, .115, point.z + normal.z)
    positions.push(point.x - normal.x, .115, point.z - normal.z)
    if (index < segments) {
      const cursor = index * 2
      indices.push(cursor, cursor + 2, cursor + 1, cursor + 2, cursor + 3, cursor + 1)
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

function travelerGeometry(scale = 1) {
  const shape = new THREE.Shape()
  shape.moveTo(0, 1.35 * scale)
  shape.lineTo(-.88 * scale, -.9 * scale)
  shape.quadraticCurveTo(0, -.55 * scale, .88 * scale, -.9 * scale)
  shape.closePath()
  return new THREE.ShapeGeometry(shape)
}

function createCityScene(plan, interactions) {
  const root = new THREE.Group()
  root.name = 'atlas-city'
  const pickables = []
  const siteMarkers = []
  const eventMarkers = []
  const siteFixtures = []
  const {minimumX, maximumX, minimumZ, maximumZ} = plan.bounds
  const width = maximumX - minimumX
  const depth = maximumZ - minimumZ
  const centerX = (minimumX + maximumX) / 2
  const centerZ = (minimumZ + maximumZ) / 2

  const ground = addMesh(
    root,
    new THREE.PlaneGeometry(width + 30, depth + 30),
    cityMaterial(0x252a2e, {roughness: .96}),
    [centerX, -.04, centerZ],
    [-Math.PI / 2, 0, 0],
  )
  ground.castShadow = false

  const grid = new THREE.GridHelper(Math.max(width, depth) + 32, Math.round(Math.max(width, depth) / 5.6), 0x596269, 0x42494e)
  grid.position.set(centerX, .006, centerZ)
  grid.material.transparent = true
  grid.material.opacity = .2
  root.add(grid)

  const buildingGeometry = new RoundedBoxGeometry(1, 1, 1, 3, .075)
  const buildingMaterial = cityMaterial(CITY, {roughness: .76, metalness: .05})
  const buildings = new THREE.InstancedMesh(buildingGeometry, buildingMaterial, plan.buildings.length)
  buildings.castShadow = true
  buildings.receiveShadow = true
  const matrix = new THREE.Matrix4()
  const color = new THREE.Color()
  plan.buildings.forEach((building, index) => {
    matrix.compose(
      new THREE.Vector3(building.x, building.height / 2, building.z),
      new THREE.Quaternion(),
      new THREE.Vector3(building.width, building.height, building.depth),
    )
    buildings.setMatrixAt(index, matrix)
    color.setRGB(building.tone * .55, building.tone * .58, building.tone * .6)
    buildings.setColorAt(index, color)
  })
  buildings.instanceMatrix.needsUpdate = true
  buildings.instanceColor.needsUpdate = true
  root.add(buildings)

  const crowned = plan.buildings.filter((building) => building.crown)
  if (crowned.length) {
    const crownGeometry = new RoundedBoxGeometry(1, 1, 1, 2, .08)
    const crowns = new THREE.InstancedMesh(crownGeometry, cityMaterial(CITY_DARK, {roughness: .62, metalness: .12}), crowned.length)
    crowned.forEach((building, index) => {
      matrix.compose(
        new THREE.Vector3(building.x, building.height + .42, building.z),
        new THREE.Quaternion(),
        new THREE.Vector3(building.width * .42, .84, building.depth * .42),
      )
      crowns.setMatrixAt(index, matrix)
    })
    crowns.instanceMatrix.needsUpdate = true
    crowns.castShadow = true
    root.add(crowns)
  }

  const curve = routeCurve(plan.route)
  const routeSegments = Math.max(96, plan.route.length * 2)
  const road = addMesh(root, roadGeometry(curve, 3.7, routeSegments), signalMaterial(0x111a20, .96))
  road.receiveShadow = true
  road.renderOrder = 2
  const routeGlow = addMesh(root, new THREE.TubeGeometry(curve, routeSegments, .34, 10, false), signalMaterial(BLUE, .28), [0, .22, 0])
  const routeCore = addMesh(root, new THREE.TubeGeometry(curve, routeSegments, .145, 10, false), signalMaterial(BLUE), [0, .28, 0])
  const routeHighlight = addMesh(root, new THREE.TubeGeometry(curve, routeSegments, .045, 8, false), signalMaterial(BLUE_BRIGHT), [0, .32, 0])
  routeGlow.renderOrder = 3
  routeCore.renderOrder = 4
  routeHighlight.renderOrder = 5
  routeGlow.castShadow = routeCore.castShadow = routeHighlight.castShadow = false

  plan.sites.forEach((site, siteIndex) => {
    const previous = plan.sites[Math.max(0, siteIndex - 1)]
    const next = plan.sites[Math.min(plan.sites.length - 1, siteIndex + 1)]
    const tangent = new THREE.Vector3(
      next.world[0] - previous.world[0],
      0,
      next.world[2] - previous.world[2],
    ).normalize()
    const fixture = createDriveFixture(site, {
      id: site.id,
      x: site.world[0],
      y: .2,
      z: site.world[2],
      shoulder: siteIndex % 2 ? 1 : -1,
    })
    fixture.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, -1), tangent.lengthSq() ? tangent : new THREE.Vector3(0, 0, -1))
    fixture.scale.setScalar(.72)
    root.add(fixture)
    siteFixtures.push({site, fixture})

    const marker = new THREE.Group()
    marker.position.set(...site.world)
    marker.userData.pick = {siteId: site.id, sequence: null}
    const pad = addMesh(marker, new THREE.CylinderGeometry(1.34, 1.34, .18, 32), signalMaterial(0x111a20), [0, .13, 0])
    const ring = addMesh(marker, new THREE.TorusGeometry(1.06, .115, 10, 40), signalMaterial(0x8a9ca5), [0, .28, 0], [-Math.PI / 2, 0, 0])
    const stem = addMesh(marker, new THREE.CylinderGeometry(.13, .22, 1.55, 16), signalMaterial(BLUE), [0, 1.02, 0])
    const beacon = addMesh(marker, new THREE.SphereGeometry(.34, 18, 12), signalMaterial(0xe8f7ff), [0, 1.9, 0])
    const halo = addMesh(marker, new THREE.SphereGeometry(.68, 18, 12), signalMaterial(BLUE, .2), [0, 1.9, 0])
    for (const object of [pad, ring, stem, beacon, halo]) object.userData.pick = marker.userData.pick
    pickables.push(pad, ring, stem, beacon, halo)
    pad.renderOrder = ring.renderOrder = stem.renderOrder = beacon.renderOrder = halo.renderOrder = 6
    root.add(marker)
    siteMarkers.push({site, marker, pad, ring, stem, beacon, halo})

    const records = interactions?.sites?.[site.id] || []
    const eventGroup = new THREE.Group()
    eventGroup.position.set(...site.world)
    records.slice(0, 12).forEach((record, index) => {
      const angle = index / Math.max(1, records.length) * Math.PI * 2 - Math.PI / 2
      const radius = 1.55 + (index % 2) * .32
      const succeeded = record.status === 'succeeded' || record.status === 'ok'
      const bead = addMesh(eventGroup, new THREE.SphereGeometry(.26, 18, 12), signalMaterial(succeeded ? 0xdce8ed : RED), [Math.cos(angle) * radius, .62, Math.sin(angle) * radius])
      bead.userData.pick = {siteId: site.id, sequence: record.sequence}
      pickables.push(bead)
      eventMarkers.push({siteId: site.id, sequence: record.sequence, bead, group: eventGroup})
    })
    eventGroup.visible = false
    root.add(eventGroup)
  })

  const traveler = new THREE.Group()
  const shadow = addMesh(traveler, travelerGeometry(1.08), cityMaterial(0x101417, {opacity: .62}), [0, .02, .12], [-Math.PI / 2, 0, 0])
  shadow.castShadow = false
  const outer = addMesh(traveler, travelerGeometry(1), cityMaterial(RED, {emissive: RED, emissiveIntensity: 1.25, roughness: .22}), [0, .18, 0], [-Math.PI / 2, 0, 0])
  outer.castShadow = false
  const inner = addMesh(traveler, travelerGeometry(.68), cityMaterial(0xf4f7f8, {emissive: 0xd8f2ff, emissiveIntensity: .6, roughness: .22}), [0, .205, -.035], [-Math.PI / 2, 0, 0])
  inner.castShadow = false
  root.add(traveler)

  return {root, pickables, siteMarkers, siteFixtures, eventMarkers, traveler}
}

function disposeScene(root) {
  root.traverse((object) => {
    object.geometry?.dispose?.()
    if (Array.isArray(object.material)) object.material.forEach((item) => item.dispose?.())
    else object.material?.dispose?.()
  })
}

export default function Cartography({story, interactions, replay, playing, selected, onSelect, fitSignal}) {
  const host = useRef(null)
  const replayRef = useRef(replay)
  const selectedRef = useRef(selected)
  const apiRef = useRef(null)
  const atlas = useMemo(() => buildAtlas(story, interactions), [interactions, story])
  const cityPlan = useMemo(() => buildAtlasCityPlan(atlas, story.journey_key || story.outcome), [atlas, story.journey_key, story.outcome])
  const replayIndex = Math.max(0, Math.min(story.chapters.length - 1, Math.floor(replay * Math.max(1, story.chapters.length - 1) + .001)))
  const currentChapter = story.chapters[replayIndex]
  const activeSiteId = selected?.siteId || currentChapter?.id
  const activeSite = cityPlan.sites.find((site) => site.id === activeSiteId) || currentChapter
  const activeRecords = interactions?.sites?.[activeSiteId] || []

  useEffect(() => { replayRef.current = replay }, [replay])
  useEffect(() => { selectedRef.current = selected }, [selected])

  useEffect(() => {
    if (!host.current) return undefined
    let disposed = false
    let frame = 0
    let observer
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x121a1f)
    scene.fog = new THREE.FogExp2(0x121a1f, .0048)
    const camera = new THREE.PerspectiveCamera(42, 1, .1, 700)
    const renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: 'high-performance'})
    renderer.domElement.className = 'atlas-city-canvas'
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.08
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    host.current.appendChild(renderer.domElement)

    scene.add(new THREE.HemisphereLight(0xdce8ed, 0x20262a, 2.35))
    scene.add(new THREE.AmbientLight(0xb9c5ca, .48))
    const sun = new THREE.DirectionalLight(0xffffff, 3.4)
    sun.position.set(-42, 74, 36)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    sun.shadow.camera.left = -90
    sun.shadow.camera.right = 90
    sun.shadow.camera.top = 90
    sun.shadow.camera.bottom = -90
    scene.add(sun)

    const city = createCityScene(cityPlan, interactions)
    scene.add(city.root)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = .075
    controls.screenSpacePanning = false
    controls.minPolarAngle = .28
    controls.maxPolarAngle = 1.28
    controls.minDistance = 12
    controls.maxDistance = 240

    const center = new THREE.Vector3(
      (cityPlan.bounds.minimumX + cityPlan.bounds.maximumX) / 2,
      0,
      (cityPlan.bounds.minimumZ + cityPlan.bounds.maximumZ) / 2,
    )
    const span = Math.max(
      cityPlan.bounds.maximumX - cityPlan.bounds.minimumX,
      cityPlan.bounds.maximumZ - cityPlan.bounds.minimumZ,
      40,
    )
    const fit = () => {
      controls.target.copy(center)
      camera.position.set(center.x + span * .5, span * .78, center.z + span * .68)
      camera.near = Math.max(.1, span / 900)
      camera.far = span * 8
      camera.updateProjectionMatrix()
      controls.update()
    }
    const focus = (siteId) => {
      const site = cityPlan.sites.find((item) => item.id === siteId)
      if (!site) return
      const target = new THREE.Vector3(...site.world)
      const direction = camera.position.clone().sub(controls.target).normalize()
      controls.target.copy(target)
      camera.position.copy(target).addScaledVector(direction, Math.max(24, span * .34))
    }
    fit()
    apiRef.current = {fit, focus}

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const pointerStart = new THREE.Vector2()
    let dragging = false
    const pointerDown = (event) => {
      pointerStart.set(event.clientX, event.clientY)
      dragging = false
    }
    const pointerMove = (event) => {
      if (Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 4) dragging = true
    }
    const pointerUp = (event) => {
      if (dragging) return
      const bounds = renderer.domElement.getBoundingClientRect()
      pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, -((event.clientY - bounds.top) / bounds.height) * 2 + 1)
      raycaster.setFromCamera(pointer, camera)
      const hit = raycaster.intersectObjects(city.pickables, true)[0]
      if (hit?.object?.userData?.pick) onSelect(hit.object.userData.pick)
      else onSelect(null)
    }
    renderer.domElement.addEventListener('pointerdown', pointerDown)
    renderer.domElement.addEventListener('pointermove', pointerMove)
    renderer.domElement.addEventListener('pointerup', pointerUp)

    const resize = () => {
      if (!host.current) return
      const width = host.current.clientWidth
      const height = host.current.clientHeight
      camera.aspect = width / Math.max(1, height)
      camera.updateProjectionMatrix()
      renderer.setPixelRatio(adaptiveRenderPixelRatio(window.devicePixelRatio, width, height))
      renderer.setSize(width, height, false)
    }
    observer = new ResizeObserver(resize)
    observer.observe(host.current)
    resize()

    const forward = new THREE.Vector3(0, 0, -1)
    const heading = new THREE.Vector3()
    const desiredScale = new THREE.Vector3()
    const projected = new THREE.Vector3()
    const labelNodes = new Map([...host.current.querySelectorAll('[data-atlas-site]')].map((node) => [node.dataset.atlasSite, node]))
    const render = () => {
      if (disposed) return
      const sample = sampleAtlasCityRoute(cityPlan.route, replayRef.current)
      city.traveler.position.set(...sample.position)
      city.traveler.position.y = .22
      heading.set(...sample.tangent).normalize()
      city.traveler.quaternion.setFromUnitVectors(forward, heading)
      const stageIndex = Math.max(0, Math.min(city.siteMarkers.length - 1, Math.floor(replayRef.current * Math.max(1, city.siteMarkers.length - 1) + .001)))
      const selectedSiteId = selectedRef.current?.siteId
      const currentSiteId = city.siteMarkers[stageIndex]?.site.id
      const elapsed = performance.now() / 1000
      city.siteFixtures.forEach(({site, fixture}, index) => {
        const active = index === stageIndex || site.id === selectedSiteId
        updateDriveFixture(fixture, {
          active,
          approaching: !active,
          completed: index < stageIndex,
          elapsed,
        })
      })
      city.siteMarkers.forEach(({site, marker, ring, pad, stem, halo}, index) => {
        const active = index === stageIndex || site.id === selectedSiteId
        const reached = index <= stageIndex
        ring.material.color.setHex(active ? BLUE_BRIGHT : reached ? BLUE : 0x8a9ca5)
        stem.material.color.setHex(active ? BLUE_BRIGHT : reached ? BLUE : 0x61727b)
        halo.material.opacity = active ? .32 : reached ? .14 : .08
        pad.material.color.setHex(active ? 0x183b50 : 0x262e33)
        desiredScale.setScalar(active ? 1.18 : 1)
        ring.scale.lerp(desiredScale, .12)
        marker.getWorldPosition(projected)
        projected.y += 2.55
        projected.project(camera)
        const label = labelNodes.get(site.id)
        if (label) {
          const visible = projected.z > -1 && projected.z < 1 && Math.abs(projected.x) < 1.08 && Math.abs(projected.y) < 1.08
          label.style.left = `${(projected.x * .5 + .5) * 100}%`
          label.style.top = `${(-projected.y * .5 + .5) * 100}%`
          label.style.opacity = visible ? (active ? '1' : reached ? '.82' : '.58') : '0'
          label.style.zIndex = String(active ? 8 : reached ? 7 : 6)
          label.classList.toggle('active', active)
          label.classList.toggle('reached', reached)
        }
      })
      city.eventMarkers.forEach((event) => {
        event.group.visible = event.siteId === (selectedSiteId || currentSiteId)
        const selectedEvent = event.sequence === selectedRef.current?.sequence
        event.bead.scale.setScalar(selectedEvent ? 1.55 : 1)
      })
      controls.update()
      renderer.render(scene, camera)
      frame = requestAnimationFrame(render)
    }
    render()

    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      observer?.disconnect()
      renderer.domElement.removeEventListener('pointerdown', pointerDown)
      renderer.domElement.removeEventListener('pointermove', pointerMove)
      renderer.domElement.removeEventListener('pointerup', pointerUp)
      controls.dispose()
      disposeScene(city.root)
      renderer.dispose()
      renderer.domElement.remove()
      apiRef.current = null
    }
  }, [cityPlan, interactions, onSelect])

  useEffect(() => {
    if (selected?.siteId) apiRef.current?.focus(selected.siteId)
  }, [selected?.siteId])

  useEffect(() => {
    if (fitSignal) apiRef.current?.fit()
  }, [fitSignal])

  return <div className="atlas-city" ref={host}>
    <div className="atlas-site-labels" aria-label="Route vantage points">
      {cityPlan.sites.map((site, index) => <button
        key={site.id}
        data-atlas-site={site.id}
        onClick={() => onSelect({siteId: site.id, sequence: null})}
        aria-label={`Open vantage ${index + 1}: ${site.title}`}
      >
        <b>{String(index + 1).padStart(2, '0')}</b>
        <span>{site.title}</span>
      </button>)}
    </div>
    <div className="atlas-city-status">
      <span>3D NAVIGATION · {String(replayIndex + 1).padStart(2, '0')} / {String(story.chapters.length).padStart(2, '0')}</span>
      <strong>{currentChapter?.title}</strong>
      <small>{KIND_LABEL[currentChapter?.kind] || currentChapter?.kind}</small>
    </div>
    <div className="atlas-city-compass"><b>N</b><i>▲</i><small>DRAG · ORBIT<br />SCROLL · ZOOM</small></div>
    <div className="atlas-city-scale">{playing ? 'ROUTE ADVANCING' : selected?.siteId ? 'SITE SELECTED · OPENING EVIDENCE' : 'SELECT A ROUTE SITE'}</div>
    <section className="atlas-exchange-rail" aria-label="Recorded exchanges at current vantage">
      <div className="atlas-exchange-heading">
        <span>{selected?.siteId ? 'OPEN VANTAGE' : 'CURRENT VANTAGE'}</span>
        <strong>{activeSite?.title}</strong>
        <small>{KIND_LABEL[activeSite?.kind] || activeSite?.kind} · {activeRecords.length} {activeRecords.length === 1 ? 'exchange' : 'exchanges'}</small>
      </div>
      <div className="atlas-exchange-list">
        {activeRecords.length ? activeRecords.slice(0, 8).map((record) => <button
          key={record.sequence}
          className={selected?.sequence === record.sequence ? 'selected' : ''}
          onClick={() => onSelect({siteId: activeSiteId, sequence: record.sequence})}
          title="Open recorded request and response"
        >
          <b>@{String(record.sequence).padStart(2, '0')}</b>
          <span>{record.capability?.label || record.provider || record.operation}</span>
          <em>{formatNumber(record.tokens)} tok · {record.status}</em>
        </button>) : <p>No external exchange recorded at this vantage.</p>}
      </div>
      {activeRecords.length > 0 && <small className="atlas-exchange-hint">SELECT AN EXCHANGE TO INSPECT REQUEST → RESPONSE</small>}
    </section>
  </div>
}
