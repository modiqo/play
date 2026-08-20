import React, {useEffect, useMemo, useRef, useState} from 'react'
import * as THREE from 'three'
import {CSS2DRenderer} from 'three/addons/renderers/CSS2DRenderer.js'
import {BokehPass} from 'three/addons/postprocessing/BokehPass.js'
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js'
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js'
import {AMBER, GROUND, clampVisibleCallouts, glassTowerEdge, glassTowerMaterial, journeyPositions, landmarkFor, makeCallout, makeInteractionPlaque, makeTemporalCorridor, material} from './world-elements.js'
import {createWorldNavigation} from './world-navigation.js'
import {KIND_LABEL, WORLD_ROLE} from './semantics.js'
import {groupInteractionPlaques} from './interaction-plaques.mjs'
import {layoutTemporalCorridor} from './temporal-corridor.mjs'
import {plaqueIsVisible, updateMarkerAppearance} from './marker-appearance.mjs'
import {towerHeight, towerWidth} from './tower-metrics.mjs'

export default function JourneyWorld({story, interactions, replay, playing, frozen, selected, onSelect}) {
  const host = useRef(null)
  const runtime = useRef(null)
  const replayRef = useRef(replay)
  const selectedRef = useRef(selected)
  const playingRef = useRef(playing)
  const frozenRef = useRef(frozen)
  const dismissed = useRef(new Set())
  const [error, setError] = useState('')
  const positions = useMemo(() => journeyPositions(story.chapters), [story])
  const replayValue = Number(replay)
  const vantageIndex = Number.isFinite(replayValue)
    ? Math.max(0, Math.min(story.chapters.length - 1, Math.floor(THREE.MathUtils.clamp(replayValue, 0, 1) * Math.max(1, story.chapters.length - 1) + .001)))
    : 0
  const vantage = story.chapters[vantageIndex]

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
    let labels
    let observer
    let navigation
    let scene
    const cleanup = () => {
      if (disposed) return
      disposed = true
      cancelAnimationFrame(frame)
      observer?.disconnect()
      navigation?.dispose()
      focusPass?.dispose?.()
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
      scene.background = new THREE.Color(GROUND)
      scene.fog = new THREE.FogExp2(GROUND, .015)
      const camera = new THREE.PerspectiveCamera(54, 1, .1, 260)
      camera.position.set(0, 3.3, 6)

      renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: 'high-performance'})
      renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1))
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = THREE.PCFShadowMap
      renderer.outputColorSpace = THREE.SRGBColorSpace
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = .82
      renderer.domElement.className = 'world-canvas'
      host.current.appendChild(renderer.domElement)
      if (tutorialFocus) {
        composer = new EffectComposer(renderer)
        composer.addPass(new RenderPass(scene, camera))
        focusPass = new BokehPass(scene, camera, {focus: 12, aperture: .00012, maxblur: .007})
        composer.addPass(focusPass)
      }

      labels = new CSS2DRenderer()
      labels.domElement.className = 'world-labels'
      host.current.appendChild(labels.domElement)

      scene.add(new THREE.HemisphereLight(0xdfe3e4, 0x08090a, 1.45))
      const key = new THREE.DirectionalLight(0xffffff, 2.7)
      key.position.set(-18, 34, 12)
      key.castShadow = true
      key.shadow.mapSize.set(2048, 2048)
      key.shadow.camera.left = -48
      key.shadow.camera.right = 48
      key.shadow.camera.top = 48
      key.shadow.camera.bottom = -48
      scene.add(key)
      const amberLight = new THREE.PointLight(AMBER, 10, 24, 2)
      scene.add(amberLight)

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
        new THREE.MeshStandardMaterial({color: AMBER, emissive: AMBER, emissiveIntensity: 1.5, roughness: .4}),
      )
      scene.add(route)

      const sites = []
      const interactionMeshes = []
      const semanticMeshes = []
      story.chapters.forEach((chapter, index) => {
        const site = new THREE.Group()
        site.position.copy(positions[index])
        const platform = new THREE.Mesh(new THREE.BoxGeometry(15, .24, 12), material(0x111518))
        platform.position.y = .08
        platform.receiveShadow = true
        platform.userData = {siteId: chapter.id, sequence: null}
        semanticMeshes.push(platform)
        site.add(platform)

        const landmark = landmarkFor(chapter)
        const landmarkSize = new THREE.Box3().setFromObject(landmark).getSize(new THREE.Vector3())
        const landmarkMaterials = []
        const focusEdges = []
        landmark.traverse((object) => {
          if (!object.isMesh) return
          object.userData = {siteId: chapter.id, sequence: null}
          semanticMeshes.push(object)
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
        site.add(makeTemporalCorridor(chapter, temporalCorridor))
        const towerFootprint = THREE.MathUtils.clamp(6.3 / Math.max(1, temporalCorridor.points.length), .24, .55)
        const markers = []
        let maximumTowerHeight = 0
        temporalCorridor.points.forEach((temporal, recordIndex) => {
          const record = {...temporal.record, temporal}
          const height = towerHeight(record)
          maximumTowerHeight = Math.max(maximumTowerHeight, height)
          const towerGeometry = new THREE.BoxGeometry(towerWidth(temporal, towerFootprint), height, towerFootprint)
          const tower = new THREE.Mesh(towerGeometry, glassTowerMaterial())
          const towerEdge = glassTowerEdge(towerGeometry)
          tower.add(towerEdge)
          tower.position.set(temporal.x, height / 2, temporal.z)
          tower.castShadow = true
          tower.userData = {siteId: chapter.id, sequence: record.sequence}
          site.add(tower)
          interactionMeshes.push(tower)
          markers.push({tower, edge: towerEdge, temporal, sequence: record.sequence})
        })
        const plaques = groupInteractionPlaques(temporalCorridor.points).map((group, plaqueIndex) => {
          const plaque = makeInteractionPlaque(group, chapter, plaqueIndex, (selection) => {
            onSelect(selectedRef.current?.sequence === selection.sequence ? null : selection)
          })
          plaque.label.position.set(group.x, .22, group.z + .18)
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
        label.position.y = Math.max(4.9, landmarkSize.y + 1.2, maximumTowerHeight + 2.15)
        site.add(label)
        scene.add(site)
        sites.push({
          chapter, group: site, platform, landmark, landmarkMaterials, focusEdges, label: root, markers, plaques, worldPosition: site.position.clone(),
          approachDistance: Math.max(12.5, landmarkSize.z * .5 + 8, landmarkSize.x * .38 + 8),
          eyeHeight: THREE.MathUtils.clamp(landmarkSize.y * .42, 2.5, 3.8),
        })
      })

      const traveler = new THREE.Mesh(
        new THREE.OctahedronGeometry(.18, 0),
        new THREE.MeshStandardMaterial({color: AMBER, emissive: AMBER, emissiveIntensity: 2.3, roughness: .28}),
      )
      traveler.castShadow = true
      scene.add(traveler)
      const focusRing = new THREE.Mesh(
        new THREE.RingGeometry(1.05, 1.14, 48),
        new THREE.MeshBasicMaterial({color: AMBER, transparent: true, opacity: .42, side: THREE.DoubleSide}),
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
        camera.aspect = width / Math.max(1, height)
        camera.updateProjectionMatrix()
        renderer.setSize(width, height, false)
        composer?.setSize(width, height)
        labels.setSize(width, height)
      }
      observer = new ResizeObserver(resize)
      observer.observe(host.current)
      resize()

      runtime.current = {sites, camera, traveler}
      const cameraTarget = new THREE.Vector3()
      const desiredCamera = new THREE.Vector3()
      const desiredLook = new THREE.Vector3()
      let previousReached = -1
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

          const focus = selectedRef.current?.sequence ? selectedRef.current.siteId : null
          const focusSite = sites.find((site) => site.chapter.id === focus)
          if (focusSite) {
            desiredCamera.copy(focusSite.worldPosition).add(new THREE.Vector3(focusSite.chapter.order % 2 === 0 ? -10 : 10, 5.2, 9.5))
            desiredLook.copy(focusSite.worldPosition).setY(2.3)
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
          amberLight.position.copy(traveler.position).setY(2.1)

          const reached = Math.max(0, Math.min(lastIndex, Math.floor(scaled + .001)))
          if (reached !== previousReached) {
            dismissed.current.delete(sites[reached]?.chapter.id)
            navigation.reset()
            previousReached = reached
          }
          focusRing.position.copy(positions[reached]).setY(.16)
          const ringPulse = 1 + Math.sin(elapsed * 2.2) * .045
          focusRing.scale.set(ringPulse, ringPulse, ringPulse)
          sites.forEach((site, siteIndex) => {
            site.group.visible = siteIndex <= reached + 1
            const isCurrent = siteIndex === reached
            const isSelectedSite = selectedRef.current?.siteId === site.chapter.id
            const isSelected = isSelectedSite && !selectedRef.current?.sequence
            const interactionEngaged = (isSelectedSite && Boolean(selectedRef.current?.sequence)) || site.plaques.some((plaque) => plaque.root.classList.contains('spread'))
            if (tutorialFocus) {
              site.landmark.position.y = isCurrent ? .08 + Math.sin(elapsed * 1.8) * .015 : 0
              site.platform.material.color.setHex(isCurrent ? 0x111518 : 0x060809)
              site.landmarkMaterials.forEach((state) => {
                state.material.color.copy(state.color)
                if (!isCurrent) state.material.color.multiplyScalar(.22)
                if (state.material.emissive && state.emissive) {
                  state.material.emissive.copy(state.emissive)
                  state.material.emissiveIntensity = isCurrent ? state.emissiveIntensity : 0
                }
              })
              site.focusEdges.forEach((edge) => {
                edge.visible = isCurrent
                edge.material.opacity = isCurrent ? .2 + Math.sin(elapsed * 1.9) * .045 : 0
              })
            }
            site.label.classList.toggle('expanded', isSelected || (isCurrent && !selectedRef.current && !dismissed.current.has(site.chapter.id)))
            site.label.classList.toggle('behind-interaction', interactionEngaged)
            site.label.classList.toggle('current', isCurrent)
            site.label.classList.toggle('frozen', isCurrent && frozenRef.current)
            site.label.classList.toggle('complete', siteIndex < reached)
            site.label.classList.toggle('next', siteIndex === reached + 1)
            site.label.classList.toggle('tutorial-dimmed', tutorialFocus && !isCurrent)
            site.markers.forEach((marker, markerIndex) => {
              const markerSelected = selectedRef.current?.sequence === marker.sequence
              const proximity = isCurrent || Boolean(markerSelected)
              const pulse = proximity
                ? frozenRef.current ? .88 : .42 + Math.max(0, Math.sin(elapsed * 2.3 - markerIndex * .72)) * .8
                : 0
              updateMarkerAppearance(marker, {
                selected: markerSelected,
                proximity,
                pulse,
                frozen: frozenRef.current,
              })
            })
            site.plaques.forEach((plaque) => {
              const plaqueSelected = plaque.sequences.includes(selectedRef.current?.sequence)
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
            })
          })
          if (focusPass) {
            const focusSite = sites[reached]
            const focusPoint = focusSite.worldPosition.clone().setY(Math.max(1.4, focusSite.eyeHeight))
            focusPass.uniforms.focus.value = camera.position.distanceTo(focusPoint)
            focusPass.uniforms.aperture.value = playingRef.current ? .000075 : .00013
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
  }, [interactions, onSelect, positions, story])

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
