import React, {useEffect, useMemo, useRef, useState} from 'react'
import {OrbitViewport} from '@deck.gl/core'
import * as THREE from 'three'
import {glassBeadGeometry, glassBeadMaterial} from './world-elements.js'

function viewportFor(viewState, width, height) {
  if (!(width > 0 && height > 0)) return null
  return new OrbitViewport({
    id: 'atlas-physical-beads', width, height, orbitAxis: 'Z', fovy: 48,
    target: viewState.target, zoom: viewState.zoom,
    rotationX: viewState.rotationX, rotationOrbit: viewState.rotationOrbit,
  })
}

function projectedRadius(viewport, center, edge) {
  const origin = viewport.project(center)
  const boundary = viewport.project(edge)
  return Math.max(.01, Math.hypot(boundary[0] - origin[0], boundary[1] - origin[1]))
}

function materialVariant({opacity, emissive = .012, transmission = .12}) {
  const material = glassBeadMaterial()
  material.opacity = opacity
  material.transmission = transmission
  material.emissiveIntensity = emissive
  material.depthWrite = opacity >= .3
  return material
}

/**
 * A transparent Three.js rendering plane synchronized to DeckGL's OrbitView.
 * Deck owns terrain and picking; this layer owns the exact physical glass used
 * by Follow so a bead does not change material vocabulary between modes.
 */
export default function PhysicalBeadOverlay({
  beads,
  viewState,
  semanticZoom,
  currentSiteId,
  selectedSequence,
  adjacentSequences,
  reachedSiteIds,
  positionFor,
  edgeFor,
  labelBeads,
  markerScale = 1,
  onSelect,
}) {
  const host = useRef(null)
  const runtime = useRef(null)
  const [size, setSize] = useState({width: 0, height: 0})
  const reached = useMemo(() => new Set(reachedSiteIds), [reachedSiteIds])
  const adjacent = useMemo(() => new Set(adjacentSequences), [adjacentSequences])

  useEffect(() => {
    if (!host.current) return undefined
    const scene = new THREE.Scene()
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .1, 2400)
    camera.position.z = 1200
    const renderer = new THREE.WebGLRenderer({alpha: true, antialias: true, powerPreference: 'high-performance'})
    renderer.setClearColor(0x000000, 0)
    renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = .82
    renderer.domElement.className = 'atlas-physical-bead-canvas'
    host.current.appendChild(renderer.domElement)

    scene.add(new THREE.HemisphereLight(0xdfe3e4, 0x08090a, 1.45))
    const key = new THREE.DirectionalLight(0xffffff, 2.7)
    key.position.set(-420, 520, 900)
    scene.add(key)
    const rim = new THREE.PointLight(0xe88413, 10, 1600, 2)
    rim.position.set(460, -280, 620)
    scene.add(rim)

    const beadGroup = new THREE.Group()
    scene.add(beadGroup)
    const geometry = glassBeadGeometry()
    const materials = {
      future: materialVariant({opacity: .11, transmission: .04}),
      reached: materialVariant({opacity: .3, transmission: .09}),
      current: materialVariant({opacity: .48, emissive: .026}),
      adjacent: materialVariant({opacity: .56, emissive: .045}),
      selected: materialVariant({opacity: .72, emissive: .09}),
    }
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.max(1, Math.round(entry.contentRect.width))
      const height = Math.max(1, Math.round(entry.contentRect.height))
      renderer.setSize(width, height, false)
      camera.left = -width / 2
      camera.right = width / 2
      camera.top = height / 2
      camera.bottom = -height / 2
      camera.updateProjectionMatrix()
      setSize({width, height})
    })
    observer.observe(host.current)
    runtime.current = {scene, camera, renderer, beadGroup, geometry, materials}
    return () => {
      observer.disconnect()
      beadGroup.clear()
      geometry.dispose()
      Object.values(materials).forEach((material) => material.dispose())
      renderer.dispose()
      renderer.domElement.remove()
      runtime.current = null
    }
  }, [])

  useEffect(() => {
    const value = runtime.current
    const viewport = viewportFor(viewState, size.width, size.height)
    if (!value || !viewport) return
    value.beadGroup.clear()
    const groups = {future: [], reached: [], current: [], adjacent: [], selected: []}
    for (const bead of beads) {
      const sequence = bead.interaction.sequence
      const category = sequence === selectedSequence
        ? 'selected'
        : adjacent.has(sequence)
          ? 'adjacent'
          : selectedSequence != null
            ? 'future'
            : bead.site.id === currentSiteId
            ? 'current'
            : reached.has(bead.site.id) ? 'reached' : 'future'
      groups[category].push(bead)
    }
    const dummy = new THREE.Object3D()
    for (const [category, records] of Object.entries(groups)) {
      if (!records.length) continue
      const mesh = new THREE.InstancedMesh(value.geometry, value.materials[category], records.length)
      mesh.frustumCulled = false
      records.forEach((bead, index) => {
        const center = positionFor(bead)
        const edge = edgeFor(bead)
        const projected = viewport.project(center)
        const radius = projectedRadius(viewport, center, edge)
        const overviewFloor = semanticZoom === 'journey'
          ? bead.site.id === currentSiteId ? 3.8 : 1.25
          : 2.2
        const screenRadius = Math.max(overviewFloor * markerScale, radius)
        dummy.position.set(
          projected[0] - size.width / 2,
          size.height / 2 - projected[1],
          120 - projected[2] * 90,
        )
        dummy.scale.setScalar(screenRadius)
        dummy.updateMatrix()
        mesh.setMatrixAt(index, dummy.matrix)
      })
      mesh.instanceMatrix.needsUpdate = true
      value.beadGroup.add(mesh)
    }
    value.renderer.render(value.scene, value.camera)
  }, [adjacent, beads, currentSiteId, edgeFor, markerScale, positionFor, reached, selectedSequence, semanticZoom, size, viewState])

  const viewport = viewportFor(viewState, size.width, size.height)
  const labels = viewport ? labelBeads.map((bead) => {
    const projected = viewport.project(positionFor(bead))
    return {bead, left: projected[0], top: projected[1]}
  }) : []

  return <div className="atlas-physical-beads" ref={host}>
    <div className="atlas-bead-labels">{labels.map(({bead, left, top}) => <button
      key={bead.interaction.sequence}
      className={bead.interaction.sequence === selectedSequence ? 'selected' : ''}
      style={{left, top}}
      onClick={(event) => {
        event.stopPropagation()
        onSelect({siteId: bead.site.id, sequence: bead.interaction.sequence})
      }}
    >@{String(bead.interaction.sequence).padStart(2, '0')}</button>)}</div>
  </div>
}
