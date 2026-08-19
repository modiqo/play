import React, {useEffect, useMemo, useRef, useState} from 'react'
import * as THREE from 'three'
import {CSS2DRenderer} from 'three/addons/renderers/CSS2DRenderer.js'
import {AMBER, GROUND, clampVisibleCallouts, journeyPositions, landmarkFor, makeCallout, makeInteractionCallout, material} from './world-elements.js'
import {createWorldNavigation} from './world-navigation.js'

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

  useEffect(() => { replayRef.current = replay }, [replay])
  useEffect(() => { selectedRef.current = selected }, [selected])
  useEffect(() => { playingRef.current = playing }, [playing])
  useEffect(() => { frozenRef.current = frozen }, [frozen])

  useEffect(() => {
    if (!host.current) return undefined
    let disposed = false
    let frame = 0
    let renderer
    try {
      const scene = new THREE.Scene()
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

      const labels = new CSS2DRenderer()
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
        landmark.traverse((object) => {
          if (!object.isMesh) return
          object.userData = {siteId: chapter.id, sequence: null}
          semanticMeshes.push(object)
        })
        site.add(landmark)
        const records = interactions?.sites?.[chapter.id] || []
        const markers = []
        records.forEach((record, recordIndex) => {
          const signal = Math.log2(2 + Number(record.duration_ms || 0) / 90 + Number(record.tokens || 0) / 700)
          const height = Math.max(.7, Math.min(5.8, signal))
          const tower = new THREE.Mesh(new THREE.BoxGeometry(.55, height, .55), material(record.status === 'error' ? 0x8d8f8e : 0x555a5d))
          const side = recordIndex % 2 === 0 ? -1 : 1
          const rank = Math.floor(recordIndex / 2)
          tower.position.set(side * (4.2 + (rank % 3) * .85), height / 2, 3.7 - Math.floor(rank / 3) * 1.15)
          tower.castShadow = true
          tower.userData = {siteId: chapter.id, sequence: record.sequence}
          site.add(tower)
          interactionMeshes.push(tower)
          const marker = makeInteractionCallout(record, chapter, recordIndex, (selection) => {
            onSelect(selectedRef.current?.sequence === selection.sequence ? null : selection)
          })
          marker.hovered = false
          marker.root.addEventListener('pointerenter', () => { marker.hovered = true })
          marker.root.addEventListener('pointerleave', () => { marker.hovered = false })
          marker.root.addEventListener('focus', () => { marker.hovered = true })
          marker.root.addEventListener('blur', () => { marker.hovered = false })
          marker.label.position.set(tower.position.x, height + .75, tower.position.z)
          site.add(marker.label)
          marker.tower = tower
          markers.push(marker)
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
        site.add(label)
        scene.add(site)
        sites.push({chapter, group: site, label: root, markers, worldPosition: site.position.clone()})
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

      const navigation = createWorldNavigation({
        canvas: renderer.domElement, camera, frozenRef, interactionMeshes, semanticMeshes, onSelect,
      })

      const resize = () => {
        if (!host.current) return
        const width = host.current.clientWidth
        const height = host.current.clientHeight
        camera.aspect = width / Math.max(1, height)
        camera.updateProjectionMatrix()
        renderer.setSize(width, height, false)
        labels.setSize(width, height)
      }
      const observer = new ResizeObserver(resize)
      observer.observe(host.current)
      resize()

      runtime.current = {sites, camera, traveler}
      const cameraTarget = new THREE.Vector3()
      const desiredCamera = new THREE.Vector3()
      const desiredLook = new THREE.Vector3()
      let previousReached = -1
      const render = () => {
        if (disposed) return
        const elapsed = performance.now() / 1000
        const progress = THREE.MathUtils.clamp(replayRef.current, 0, 1)
        const scaled = progress * Math.max(1, positions.length - 1)
        const index = Math.min(positions.length - 1, Math.floor(scaled))
        const nextIndex = Math.min(positions.length - 1, index + 1)
        const amount = scaled - index
        const current = positions[index].clone().lerp(positions[nextIndex], amount)
        const ahead = positions[Math.min(positions.length - 1, nextIndex + 1)].clone()
        const direction = ahead.clone().sub(current).normalize()
        if (direction.lengthSq() < .01) direction.set(0, 0, -1)

        const focus = selectedRef.current?.sequence ? selectedRef.current.siteId : null
        const focusSite = sites.find((site) => site.chapter.id === focus)
        if (focusSite) {
          desiredCamera.copy(focusSite.worldPosition).add(new THREE.Vector3(focusSite.chapter.order % 2 === 0 ? -10 : 10, 5.2, 9.5))
          desiredLook.copy(focusSite.worldPosition).setY(2.3)
        } else if (frozenRef.current) {
          navigation.applyFrozenView(current, direction, desiredCamera, desiredLook)
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

        const reached = Math.max(0, Math.floor(scaled + .001))
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
          const interactionEngaged = (isSelectedSite && Boolean(selectedRef.current?.sequence)) || site.markers.some((marker) => marker.hovered)
          site.label.classList.toggle('expanded', isSelected || (isCurrent && !selectedRef.current && !dismissed.current.has(site.chapter.id)))
          site.label.classList.toggle('behind-interaction', interactionEngaged)
          site.label.classList.toggle('current', isCurrent)
          site.label.classList.toggle('frozen', isCurrent && frozenRef.current)
          site.label.classList.toggle('complete', siteIndex < reached)
          site.label.classList.toggle('next', siteIndex === reached + 1)
          site.markers.forEach((marker, markerIndex) => {
            const markerSelected = selectedRef.current?.sequence === marker.sequence
            const proximity = isCurrent || Boolean(markerSelected)
            marker.label.visible = proximity
            marker.root.classList.toggle('arrived', isCurrent)
            marker.root.classList.toggle('proximity', proximity)
            marker.root.classList.toggle('frozen', isCurrent && frozenRef.current)
            marker.root.classList.toggle('selected', Boolean(markerSelected))
            const pulse = proximity
              ? frozenRef.current ? .88 : .42 + Math.max(0, Math.sin(elapsed * 2.3 - markerIndex * .72)) * .8
              : 0
            marker.tower.material.emissive.setHex(AMBER)
            marker.tower.material.emissiveIntensity = pulse
            marker.tower.scale.y = proximity && !frozenRef.current ? 1 + Math.max(0, Math.sin(elapsed * 2.3 - markerIndex * .72)) * .025 : 1
          })
        })
        renderer.render(scene, camera)
        labels.render(scene, camera)
        clampVisibleCallouts(labels.domElement, host.current)
        frame = requestAnimationFrame(render)
      }
      render()

      return () => {
        disposed = true
        cancelAnimationFrame(frame)
        observer.disconnect()
        navigation.dispose()
        scene.traverse((object) => {
          object.geometry?.dispose?.()
          if (Array.isArray(object.material)) object.material.forEach((item) => item.dispose?.())
          else object.material?.dispose?.()
        })
        renderer.dispose()
        labels.domElement.remove()
        renderer.domElement.remove()
        runtime.current = null
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
      renderer?.dispose?.()
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
    <div className="world-reticle"><i /><span>{frozen ? 'SITUATIONAL AWARENESS' : 'FOLLOWING THE AGENT'}</span></div>
    <div className="world-instruction">{frozen ? 'DRAG TO LOOK 360° · SCROLL TO MOVE FORWARD OR BACK · SELECT ANY ILLUMINATED CALLOUT FOR EVIDENCE' : 'THE PATH REVEALS AS THE WORK PROGRESSES · CLICK A VANTAGE TO FREEZE AND LOOK AROUND'}</div>
  </div>
}
