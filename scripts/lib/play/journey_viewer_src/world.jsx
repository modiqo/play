import React, {useEffect, useMemo, useRef, useState} from 'react'
import * as THREE from 'three'
import {CSS2DRenderer} from 'three/addons/renderers/CSS2DRenderer.js'
import {BokehPass} from 'three/addons/postprocessing/BokehPass.js'
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js'
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js'
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js'
import {SMAAPass} from 'three/addons/postprocessing/SMAAPass.js'
import {AMBER, GROUND, clampVisibleCallouts, eventHaloMaterial, glassBeadGeometry, glassBeadMaterial, journeyPositions, landmarkFor, makeCallout, makeInteractionIndex, makeInteractionPlaque, makeTemporalCorridor, material} from './world-elements.js'
import {applyInteractionFocusView, createWorldNavigation} from './world-navigation.js'
import {KIND_LABEL, WORLD_ROLE} from './semantics.js'
import {groupInteractionPlaques} from './interaction-plaques.mjs'
import {layoutTemporalCorridor} from './temporal-corridor.mjs'
import {plaqueIsVisible, temporalNeighborhood, updateMarkerAppearance} from './marker-appearance.mjs'
import {interactionDurationArc, interactionRadius} from './interaction-metrics.mjs'
import {journeyVisibilityWindow} from './journey-position.mjs'
import {calloutIsInTransit} from './world-callout-transition.mjs'
import {vantageSignal} from './vantage-signal.mjs'
import {adaptiveRenderPixelRatio, COMPOSER_SAMPLES} from './render-quality.mjs'

const THREAD_STEEL = 0x717c7f
const THREAD_PREVIOUS = 0xaeb8ba
const WORLD_SKY = 0x20272a
const WORLD_STAGE_PAGE = 50

function makeTemporalThreads(markers) {
  return markers.slice(1).map((marker, index) => {
    const previous = markers[index]
    const start = previous.bead.position.clone()
    const end = marker.bead.position.clone()
    const delta = end.clone().sub(start)
    const distance = Math.max(.001, delta.length())
    const lateral = new THREE.Vector3(-delta.z, 0, delta.x)
    if (lateral.lengthSq() > .0001) lateral.normalize()
    const sag = THREE.MathUtils.clamp(.07 + distance * .025, .09, .24)
    const bow = (index % 2 === 0 ? 1 : -1) * THREE.MathUtils.clamp(distance * .018, .025, .11)
    const first = start.clone().lerp(end, .28).addScaledVector(lateral, bow * .65)
    const middle = start.clone().lerp(end, .5).addScaledVector(lateral, bow)
    const last = start.clone().lerp(end, .72).addScaledVector(lateral, bow * .65)
    first.y -= sag * .62
    middle.y -= sag
    last.y -= sag * .62
    const curve = new THREE.CatmullRomCurve3([start, first, middle, last, end], false, 'centripetal', .48)
    const material = new THREE.MeshPhysicalMaterial({
      color: THREAD_STEEL,
      roughness: .3,
      metalness: .03,
      clearcoat: .72,
      clearcoatRoughness: .2,
      transmission: .08,
      thickness: .08,
      transparent: true,
      opacity: .11,
      depthTest: true,
      depthWrite: false,
      emissive: THREAD_STEEL,
      emissiveIntensity: .015,
    })
    const mesh = new THREE.Mesh(
      new THREE.TubeGeometry(curve, THREE.MathUtils.clamp(Math.round(distance * 5), 14, 32), .013, 5, false),
      material,
    )
    mesh.renderOrder = -1
    return {mesh, material, from: previous.sequence, to: marker.sequence}
  })
}

function updateTemporalThreadAppearance(thread, {
  relation = null,
  current = false,
  future = false,
  interactionFocus = false,
  selectedSite = false,
  elapsed = 0,
  index = 0,
} = {}) {
  const incoming = relation === 'previous' && selectedSite
  const outgoing = relation === 'next' && selectedSite
  const selectedSegment = incoming || outgoing
  const breath = .92 + Math.sin(elapsed * 1.15 + index * .73) * .08
  thread.material.color.setHex(outgoing ? AMBER : incoming ? THREAD_PREVIOUS : THREAD_STEEL)
  thread.material.emissive.setHex(outgoing ? AMBER : incoming ? THREAD_PREVIOUS : THREAD_STEEL)
  thread.material.opacity = selectedSegment
    ? (outgoing ? .48 : .32) * breath
    : future ? .004
      : interactionFocus ? .007
        : current ? .1 + Math.sin(elapsed * .8 + index) * .012 : .022
  thread.material.emissiveIntensity = selectedSegment
    ? (outgoing ? .42 : .16) * breath
    : current && !interactionFocus ? .018 : .004
}

export default function JourneyWorld({story, interactions, replay, playing, frozen, selected, onSelect, markerScale = 1}) {
  const host = useRef(null)
  const runtime = useRef(null)
  const replayRef = useRef(replay)
  const selectedRef = useRef(selected)
  const playingRef = useRef(playing)
  const frozenRef = useRef(frozen)
  const dismissed = useRef(new Set())
  const viewState = useRef(null)
  const [error, setError] = useState('')
  const positions = useMemo(() => journeyPositions(story.chapters), [story])
  const replayValue = Number(replay)
  const vantageIndex = Number.isFinite(replayValue)
    ? Math.max(0, Math.min(story.chapters.length - 1, Math.floor(THREE.MathUtils.clamp(replayValue, 0, 1) * Math.max(1, story.chapters.length - 1) + .001)))
    : 0
  const vantage = story.chapters[vantageIndex]
  const pageStart = story.chapters.length > WORLD_STAGE_PAGE
    ? Math.floor(vantageIndex / WORLD_STAGE_PAGE) * WORLD_STAGE_PAGE
    : 0
  const pageEnd = Math.min(story.chapters.length, pageStart + WORLD_STAGE_PAGE)

  useEffect(() => { replayRef.current = replay }, [replay])
  useEffect(() => { selectedRef.current = selected }, [selected])
  useEffect(() => { playingRef.current = playing }, [playing])
  useEffect(() => { frozenRef.current = frozen }, [frozen])

  useEffect(() => {
    if (!host.current) return undefined
    setError('')
    dismissed.current.clear()
    let disposed = false
    let frame = 0
    let renderer
    let composer
    let focusPass
    let smaaPass
    let labels
    let observer
    let navigation
    let scene
    let camera
    let cameraTarget
    const cleanup = () => {
      if (disposed) return
      if (camera && cameraTarget) {
        viewState.current = {
          camera: camera.position.toArray(),
          target: cameraTarget.toArray(),
        }
      }
      disposed = true
      cancelAnimationFrame(frame)
      observer?.disconnect()
      navigation?.dispose()
      focusPass?.dispose?.()
      smaaPass?.dispose?.()
      composer?.dispose?.()
      scene?.traverse((object) => {
        object.geometry?.dispose?.()
        if (Array.isArray(object.material)) object.material.forEach((item) => { item.map?.dispose?.(); item.dispose?.() })
        else {
          object.material?.map?.dispose?.()
          object.material?.dispose?.()
        }
      })
      renderer?.dispose?.()
      labels?.domElement?.remove()
      renderer?.domElement?.remove()
      runtime.current = null
    }
    try {
      if (!positions.length || positions.some((point) => !point || ![point.x, point.y, point.z].every(Number.isFinite))) {
        throw new Error('Journey route has no valid vantage points')
      }
      scene = new THREE.Scene()
      const tutorialFocus = story.origin?.kind === 'tutorial'
      scene.background = new THREE.Color(WORLD_SKY)
      scene.fog = new THREE.FogExp2(WORLD_SKY, .008)
      camera = new THREE.PerspectiveCamera(54, 1, .1, 260)
      camera.position.set(0, 3.3, 6)
      if (viewState.current?.camera) camera.position.fromArray(viewState.current.camera)

      renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: 'high-performance'})
      renderer.setPixelRatio(adaptiveRenderPixelRatio(
        window.devicePixelRatio,
        host.current.clientWidth,
        host.current.clientHeight,
      ))
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = THREE.PCFShadowMap
      renderer.outputColorSpace = THREE.SRGBColorSpace
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = 1.08
      renderer.domElement.className = 'world-canvas'
      host.current.appendChild(renderer.domElement)
      const composerTarget = new THREE.WebGLRenderTarget(1, 1, {
        type: THREE.HalfFloatType,
        samples: COMPOSER_SAMPLES,
      })
      composer = new EffectComposer(renderer, composerTarget)
      composer.addPass(new RenderPass(scene, camera))
      focusPass = new BokehPass(scene, camera, {
        focus: 12,
        aperture: tutorialFocus ? .00012 : .00009,
        maxblur: tutorialFocus ? .007 : .0055,
      })
      composer.addPass(focusPass)
      smaaPass = new SMAAPass()
      composer.addPass(smaaPass)
      composer.addPass(new OutputPass())

      labels = new CSS2DRenderer()
      labels.domElement.className = 'world-labels'
      host.current.appendChild(labels.domElement)

      scene.add(new THREE.HemisphereLight(0xf1f4f4, 0x596164, 2.7))
      scene.add(new THREE.AmbientLight(0xe4e9ea, 1.55))
      const key = new THREE.DirectionalLight(0xffffff, 3.2)
      key.position.set(-18, 34, 12)
      key.castShadow = true
      key.shadow.mapSize.set(2048, 2048)
      key.shadow.camera.left = -48
      key.shadow.camera.right = 48
      key.shadow.camera.top = 48
      key.shadow.camera.bottom = -48
      scene.add(key)
      const statusLight = new THREE.PointLight(0x55d98b, 6.4, 26, 2)
      scene.add(statusLight)

      const worldLength = Math.max(70, story.chapters.length * 25)
      const ground = new THREE.Mesh(new THREE.PlaneGeometry(130, worldLength), material(GROUND, {roughness: 1}))
      ground.rotation.x = -Math.PI / 2
      ground.position.z = -(worldLength / 2) + 12
      ground.receiveShadow = true
      scene.add(ground)
      const grid = new THREE.GridHelper(worldLength, Math.max(24, story.chapters.length * 4), 0x25292b, 0x15191b)
      grid.position.z = -(worldLength / 2) + 12
      grid.material.transparent = true
      grid.material.opacity = .54
      scene.add(grid)

      const routePoints = positions.length > 1
        ? positions.map((point) => point.clone().setY(.07))
        : [positions[0].clone().setY(.07), positions[0].clone().add(new THREE.Vector3(0, .07, -12))]
      const routeCurve = new THREE.CatmullRomCurve3(routePoints, false, 'centripetal', .42)
      const route = new THREE.Mesh(
        new THREE.TubeGeometry(routeCurve, Math.max(48, positions.length * 18), .045, 7, false),
        new THREE.MeshStandardMaterial({color: AMBER, emissive: AMBER, emissiveIntensity: 1.5, roughness: .4, transparent: true, opacity: 1}),
      )
      scene.add(route)

      const sites = new Array(story.chapters.length)
      const interactionMeshes = []
      const semanticMeshes = []
      story.chapters.slice(pageStart, pageEnd).forEach((chapter, localIndex) => {
        const index = pageStart + localIndex
        const site = new THREE.Group()
        const siteSemanticMeshes = []
        site.position.copy(positions[index])
        const platform = new THREE.Mesh(new THREE.BoxGeometry(15, .24, 12), material(0x232a2d))
        platform.position.y = .08
        platform.receiveShadow = true
        platform.userData = {siteId: chapter.id, sequence: null}
        semanticMeshes.push(platform)
        siteSemanticMeshes.push(platform)
        site.add(platform)

        const landmark = landmarkFor(chapter)
        const landmarkSize = new THREE.Box3().setFromObject(landmark).getSize(new THREE.Vector3())
        const landmarkMaterials = []
        const focusEdges = []
        landmark.traverse((object) => {
          if (!object.isMesh) return
          object.userData = {siteId: chapter.id, sequence: null}
          semanticMeshes.push(object)
          siteSemanticMeshes.push(object)
          const materials = Array.isArray(object.material) ? object.material : [object.material]
          materials.forEach((entry) => {
            if (!entry?.color) return
            landmarkMaterials.push({
              material: entry,
              color: entry.color.clone(),
              emissive: entry.emissive?.clone?.() || null,
              emissiveIntensity: Number(entry.emissiveIntensity || 0),
            })
          })
          const edge = new THREE.LineSegments(
            new THREE.EdgesGeometry(object.geometry, 28),
            new THREE.LineBasicMaterial({color: AMBER, transparent: true, opacity: 0, depthTest: true}),
          )
          edge.renderOrder = 4
          object.add(edge)
          focusEdges.push(edge)
        })
        site.add(landmark)
        const records = interactions?.sites?.[chapter.id] || []
        const temporalCorridor = layoutTemporalCorridor(records)
        const temporalStructure = makeTemporalCorridor(chapter, temporalCorridor)
        site.add(temporalStructure)
        const markers = []
        let maximumMarkerElevation = 0
        temporalCorridor.points.forEach((temporal, recordIndex) => {
          const record = {...temporal.record, temporal, siteId: chapter.id}
          const radius = interactionRadius(record) * markerScale
          const baseY = .82 + radius + temporal.lane * .56 + (recordIndex % 2) * .12
          maximumMarkerElevation = Math.max(maximumMarkerElevation, baseY + radius)
          const bead = new THREE.Mesh(glassBeadGeometry(radius), glassBeadMaterial())
          const halo = new THREE.Mesh(
            new THREE.TorusGeometry(radius + .105, .018, 6, 34, interactionDurationArc(temporal)),
            eventHaloMaterial(),
          )
          halo.rotation.z = -Math.PI / 2
          bead.position.set(temporal.x, baseY, temporal.z)
          halo.position.copy(bead.position)
          bead.castShadow = true
          bead.userData = {siteId: chapter.id, sequence: record.sequence}
          const indexLabel = makeInteractionIndex(record, (selection) => {
            onSelect(selectedRef.current?.sequence === selection.sequence ? null : selection)
          })
          bead.add(indexLabel.label)
          site.add(bead, halo)
          interactionMeshes.push(bead)
          markers.push({bead, halo, indexRoot: indexLabel.root, temporal, sequence: record.sequence, baseY})
        })
        const threads = makeTemporalThreads(markers)
        threads.forEach((thread) => site.add(thread.mesh))
        const plaques = groupInteractionPlaques(temporalCorridor.points).map((group, plaqueIndex) => {
          const plaque = makeInteractionPlaque(group, chapter, plaqueIndex, (selection) => {
            onSelect(selectedRef.current?.sequence === selection.sequence ? null : selection)
          })
          // Evidence controls occupy their own foreground rail; the timeline labels
          // remain directly behind them and never share the same screen band.
          plaque.label.position.set(group.x, .16, temporalCorridor.frontage.plaqueZ)
          site.add(plaque.label)
          return plaque
        })
        const {label, root} = makeCallout(chapter, records.length, story.chapters.length, (siteId) => {
          if (selectedRef.current?.siteId === siteId && !selectedRef.current?.sequence) {
            dismissed.current.add(siteId)
            onSelect(null)
          } else {
            dismissed.current.delete(siteId)
            onSelect({siteId, sequence: null})
          }
        })
        label.position.y = Math.max(4.9, landmarkSize.y + 1.2, maximumMarkerElevation + 1.7)
        site.add(label)
        scene.add(site)
        sites[index] = {
          chapter, records, group: site, platform, landmark, landmarkMaterials, focusEdges, label: root,
          timeLabels: temporalStructure.userData.timeLabels || [], markers, threads, plaques, semanticMeshes: siteSemanticMeshes, worldPosition: site.position.clone(),
          approachDistance: Math.max(12.5, landmarkSize.z * .5 + 8, landmarkSize.x * .38 + 8),
          eyeHeight: THREE.MathUtils.clamp(landmarkSize.y * .42, 2.5, 3.8),
        }
      })

      const traveler = new THREE.Mesh(
        new THREE.OctahedronGeometry(.18, 0),
        new THREE.MeshStandardMaterial({color: 0x55d98b, emissive: 0x55d98b, emissiveIntensity: 2.3, roughness: .28}),
      )
      traveler.castShadow = true
      scene.add(traveler)
      const focusRing = new THREE.Mesh(
        new THREE.RingGeometry(1.05, 1.14, 48),
        new THREE.MeshBasicMaterial({color: 0x55d98b, transparent: true, opacity: .42, side: THREE.DoubleSide}),
      )
      focusRing.rotation.x = -Math.PI / 2
      scene.add(focusRing)

      navigation = createWorldNavigation({
        canvas: renderer.domElement, camera, frozenRef, interactionMeshes, semanticMeshes, onSelect,
      })

      const resize = () => {
        if (!host.current) return
        const width = host.current.clientWidth
        const height = host.current.clientHeight
        const pixelRatio = adaptiveRenderPixelRatio(window.devicePixelRatio, width, height)
        camera.aspect = width / Math.max(1, height)
        camera.updateProjectionMatrix()
        if (Math.abs(renderer.getPixelRatio() - pixelRatio) > .001) {
          renderer.setPixelRatio(pixelRatio)
          composer?.setPixelRatio(pixelRatio)
        }
        renderer.setSize(width, height, false)
        composer?.setSize(width, height)
        labels.setSize(width, height)
      }
      observer = new ResizeObserver(resize)
      observer.observe(host.current)
      resize()

      runtime.current = {sites, camera, traveler}
      cameraTarget = new THREE.Vector3()
      if (viewState.current?.target) cameraTarget.fromArray(viewState.current.target)
      const desiredCamera = new THREE.Vector3()
      const desiredLook = new THREE.Vector3()
      const signalTarget = new THREE.Color(0x55d98b)
      let previousReached = -1
      let reachedAt = performance.now()
      let lastCalloutLayout = 0
      const render = () => {
        if (disposed) return
        try {
          const elapsed = performance.now() / 1000
          const replayValue = Number(replayRef.current)
          const progress = Number.isFinite(replayValue) ? THREE.MathUtils.clamp(replayValue, 0, 1) : 0
          const lastIndex = positions.length - 1
          const scaled = progress * Math.max(1, lastIndex)
          const index = Math.max(0, Math.min(lastIndex, Math.floor(scaled)))
          const nextIndex = Math.max(0, Math.min(lastIndex, index + 1))
          const amount = scaled - index
          const currentPoint = positions[index]
          const nextPoint = positions[nextIndex]
          const aheadPoint = positions[Math.max(0, Math.min(lastIndex, nextIndex + 1))]
          if (!currentPoint || !nextPoint || !aheadPoint) throw new Error('Journey route changed while rendering')
          const current = currentPoint.clone().lerp(nextPoint, amount)
          const ahead = aheadPoint.clone()
          const direction = ahead.clone().sub(current).normalize()
          if (direction.lengthSq() < .01) direction.set(0, 0, -1)

          const selectedSequence = selectedRef.current?.sequence
          const focus = selectedSequence ? selectedRef.current.siteId : null
          const focusSite = sites.find((site) => site?.chapter.id === focus)
          const focusMarker = focusSite?.markers.find((marker) => marker.sequence === selectedSequence)
          if (focusMarker) {
            const markerWorld = focusMarker.bead.getWorldPosition(new THREE.Vector3())
            applyInteractionFocusView(markerWorld, desiredCamera, desiredLook, {
              markerCount: focusSite.markers.length,
            })
          } else if (frozenRef.current) {
            navigation.applyFrozenView(current, direction, desiredCamera, desiredLook, sites[index])
          } else {
            const side = index % 2 === 0 ? 1 : -1
            desiredCamera.copy(current).addScaledVector(direction, -8.2)
            desiredCamera.x -= side * 2.2
            desiredCamera.y = 3.4
            desiredLook.copy(current).addScaledVector(direction, 3.5)
            desiredLook.y = 2.35
          }
          camera.position.lerp(desiredCamera, playingRef.current ? .065 : .1)
          cameraTarget.lerp(desiredLook, .09)
          camera.lookAt(cameraTarget)
          traveler.position.copy(current).setY(.22 + Math.sin(elapsed * 3.2) * .025)
          traveler.rotation.y = elapsed * 1.1
          statusLight.position.copy(traveler.position).setY(2.1)

          const reached = Math.max(0, Math.min(lastIndex, Math.floor(scaled + .001)))
          const signal = vantageSignal(sites[reached]?.chapter, sites[reached]?.records)
          signalTarget.setHex(signal.color)
          statusLight.color.lerp(signalTarget, .09)
          traveler.material.color.lerp(signalTarget, .09)
          traveler.material.emissive.lerp(signalTarget, .09)
          focusRing.material.color.lerp(signalTarget, .09)
          route.material.color.lerp(signalTarget, .09)
          route.material.emissive.lerp(signalTarget, .09)
          if (reached !== previousReached) {
            dismissed.current.delete(sites[reached]?.chapter.id)
            navigation.reset()
            previousReached = reached
            reachedAt = performance.now()
          }
          focusRing.position.copy(positions[reached]).setY(.16)
          const ringPulse = 1 + Math.sin(elapsed * 2.2) * .045
          focusRing.scale.set(ringPulse, ringPulse, ringPulse)
          const interactionFocus = selectedSequence !== undefined && selectedSequence !== null
          const calloutInTransit = calloutIsInTransit({
            playing: playingRef.current,
            travelAmount: amount,
            settleElapsedMs: performance.now() - reachedAt,
          })
          const visibleWindow = journeyVisibilityWindow(sites.length, reached)
          route.material.opacity = interactionFocus ? .34 : 1
          traveler.visible = !interactionFocus
          focusRing.material.opacity = interactionFocus ? .06 : .42
          sites.forEach((site, siteIndex) => {
            const visible = siteIndex >= visibleWindow.start && siteIndex <= visibleWindow.end
            site.group.visible = visible
            const isCurrent = siteIndex === reached
            const isFuture = siteIndex > reached
            site.semanticMeshes.forEach((mesh) => { mesh.userData.actionable = visible && isCurrent })
            if (!visible) {
              site.markers.forEach((marker) => { marker.bead.userData.actionable = false })
              return
            }
            const isSelectedSite = selectedRef.current?.siteId === site.chapter.id
            const isSelected = isSelectedSite && !interactionFocus
            const interactionEngaged = (isSelectedSite && interactionFocus) || site.plaques.some((plaque) => plaque.root.classList.contains('spread'))
            site.landmark.position.y = tutorialFocus && isCurrent && !interactionFocus ? .08 + Math.sin(elapsed * 1.8) * .015 : 0
            site.platform.material.color.setHex(isCurrent ? (interactionFocus ? 0x1b2225 : 0x252d30) : 0x101518)
            site.landmarkMaterials.forEach((state) => {
              state.material.color.copy(state.color)
              if (interactionFocus) state.material.color.multiplyScalar(.28)
              else if (isFuture) state.material.color.multiplyScalar(.06)
              else if (tutorialFocus && !isCurrent) state.material.color.multiplyScalar(.22)
              if (state.material.emissive && state.emissive) {
                state.material.emissive.copy(state.emissive)
                state.material.emissiveIntensity = isCurrent && !interactionFocus ? state.emissiveIntensity : 0
              }
            })
            site.focusEdges.forEach((edge) => {
              edge.visible = tutorialFocus && isCurrent && !interactionFocus
              edge.material.opacity = edge.visible ? .2 + Math.sin(elapsed * 1.9) * .045 : 0
            })
            site.label.classList.toggle('expanded', isSelected || (isCurrent && !selectedRef.current && !dismissed.current.has(site.chapter.id)))
            site.label.classList.toggle('behind-interaction', interactionEngaged)
            site.label.classList.toggle('current', isCurrent)
            site.label.classList.toggle('in-transit', isCurrent && calloutInTransit)
            site.label.classList.toggle('frozen', isCurrent && frozenRef.current)
            site.label.classList.toggle('complete', siteIndex < reached)
            site.label.classList.toggle('next', siteIndex === reached + 1)
            site.label.classList.toggle('tutorial-dimmed', tutorialFocus && !isCurrent)
            site.label.classList.toggle('future-dimmed', isFuture)
            site.timeLabels.forEach((timeLabel) => {
              timeLabel.classList.toggle('future-dimmed', isFuture)
              timeLabel.classList.toggle('focus-muted', interactionFocus)
            })
            const temporalFocus = temporalNeighborhood(
              site.markers,
              isSelectedSite ? selectedSequence : null,
            )
            site.markers.forEach((marker, markerIndex) => {
              const markerSelected = selectedSequence === marker.sequence && isSelectedSite
              const temporalRelation = temporalFocus.markerRelations[markerIndex]
              const temporalAdjacent = temporalRelation === 'previous' || temporalRelation === 'next'
              const proximity = isCurrent || Boolean(markerSelected)
              marker.bead.userData.actionable = isCurrent || markerSelected
              const pulse = proximity
                ? frozenRef.current ? .88 : .42 + Math.max(0, Math.sin(elapsed * 2.3 - markerIndex * .72)) * .8
                : 0
              const float = isCurrent && !playingRef.current ? Math.sin(elapsed * 1.7 + markerIndex * .84) * .035 : 0
              marker.bead.position.y = marker.baseY + float
              marker.halo.position.y = marker.baseY + float
              updateMarkerAppearance(marker, {
                selected: markerSelected,
                proximity,
                pulse,
                frozen: frozenRef.current,
                future: isFuture,
                muted: interactionFocus && !markerSelected && !temporalAdjacent,
                temporalRelation,
              })
            })
            site.threads.forEach((thread, threadIndex) => {
              updateTemporalThreadAppearance(thread, {
                relation: temporalFocus.segmentRelations[threadIndex],
                current: isCurrent,
                future: isFuture,
                interactionFocus,
                selectedSite: isSelectedSite,
                elapsed,
                index: threadIndex,
              })
            })
            site.plaques.forEach((plaque) => {
              const plaqueSelected = isSelectedSite && plaque.sequences.includes(selectedSequence)
              const proximity = plaqueIsVisible({
                isCurrent,
                selected: plaqueSelected,
                playing: playingRef.current,
                frozen: frozenRef.current,
              })
              plaque.label.visible = proximity
              plaque.root.classList.toggle('arrived', isCurrent && !playingRef.current)
              plaque.root.classList.toggle('proximity', proximity)
              plaque.root.classList.toggle('frozen', isCurrent && frozenRef.current)
              plaque.root.classList.toggle('selected', plaqueSelected)
              plaque.root.classList.toggle('focus-muted', interactionFocus && !plaqueSelected)
            })
          })
          if (focusPass) {
            const selectedSite = interactionFocus ? sites.find((site) => site.chapter.id === selectedRef.current?.siteId) : null
            const selectedMarker = selectedSite?.markers.find((marker) => marker.sequence === selectedSequence)
            const focusSite = selectedSite || sites[reached]
            const focusPoint = selectedMarker
              ? selectedMarker.bead.getWorldPosition(new THREE.Vector3())
              : focusSite.worldPosition.clone().setY(Math.max(1.4, focusSite.eyeHeight))
            focusPass.uniforms.focus.value = camera.position.distanceTo(focusPoint)
            focusPass.uniforms.aperture.value = interactionFocus ? .00017 : playingRef.current ? .000065 : tutorialFocus ? .00013 : .0001
            composer.render()
          } else renderer.render(scene, camera)
          labels.render(scene, camera)
          const layoutNow = performance.now()
          if (host.current && (layoutNow - lastCalloutLayout >= 80 || previousReached !== reached)) {
            clampVisibleCallouts(labels.domElement, host.current)
            lastCalloutLayout = layoutNow
          }
          frame = requestAnimationFrame(render)
        } catch (caught) {
          setError(caught instanceof Error ? caught.message : String(caught))
          cleanup()
        }
      }
      render()
      return cleanup
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
      cleanup()
      return undefined
    }
  }, [interactions, markerScale, onSelect, pageEnd, pageStart, positions, story])

  useEffect(() => {
    const close = (event) => { if (event.key === 'Escape') onSelect(null) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onSelect])

  return <div className="journey-world" ref={host}>
    {error && <div className="world-error">3D JOURNEY UNAVAILABLE · {error}</div>}
    <div className="world-reticle"><i /><span>{frozen ? `${WORLD_ROLE[vantage?.kind] || 'Journey stage'} · ${KIND_LABEL[vantage?.kind] || vantage?.kind || 'Vantage'} · SITUATIONAL AWARENESS` : 'FOLLOWING THE AGENT'}</span></div>
    <div className="world-instruction">{frozen ? 'DRAG TO LOOK 360° · SCROLL TO MOVE FORWARD OR BACK · SELECT ANY ILLUMINATED CALLOUT FOR EVIDENCE' : 'THE PATH REVEALS AS THE WORK PROGRESSES · CLICK A VANTAGE TO FREEZE AND LOOK AROUND'}</div>
  </div>
}
