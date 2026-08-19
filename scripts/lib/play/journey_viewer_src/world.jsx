import React, {useEffect, useMemo, useRef, useState} from 'react'
import * as THREE from 'three'
import {CSS2DObject, CSS2DRenderer} from 'three/addons/renderers/CSS2DRenderer.js'

export const KIND_LABEL = {
  intent: 'Intent', decision: 'Decision', capability: 'Capability', authority: 'Authority',
  phase: 'Phase', effect: 'Effect', evidence: 'Evidence', artifact: 'Artifact',
  blocker: 'Blocker', recovery: 'Recovery', milestone: 'Milestone', learning: 'Learning',
  play_candidate: 'Play candidate', play: 'Play',
}

export const MAP_MEANING = {
  intent: 'Defines the outcome the agent is trying to reach.',
  decision: 'Records a choice between possible routes.',
  capability: 'Identifies the tool or service that can advance the work.',
  authority: 'Confirms permission before an external effect occurs.',
  phase: 'Groups several interactions serving one understandable purpose.',
  effect: 'Performs outcome-bearing work in an external system.',
  evidence: 'Checks what actually happened before accepting the result.',
  artifact: 'Packages the verified result into something usable.',
  blocker: 'Makes the condition that stopped progress visible.',
  recovery: 'Shows how the agent returned to a valid route.',
  milestone: 'Marks a meaningful achievement in the journey.',
  learning: 'Preserves knowledge discovered during the work.',
  play_candidate: 'Shapes verified work into a reusable procedure.',
  play: 'Makes the verified procedure available for future journeys.',
}

export const WORLD_ROLE = {
  intent: 'Starting gate',
  decision: 'Fork in the road',
  capability: 'Station',
  authority: 'Checkpoint',
  phase: 'Journey chamber',
  effect: 'Worksite',
  evidence: 'Observatory',
  artifact: 'Destination',
  blocker: 'Barricade',
  recovery: 'Bridge',
  milestone: 'Monument',
  learning: 'Knowledge marker',
  play_candidate: 'Reusable blueprint',
  play: 'Published gateway',
}

export const WORLD_STORY = {
  intent: 'The journey begins by fixing the destination before choosing a route.',
  decision: 'The agent pauses here because more than one valid route is available.',
  capability: 'The agent equips a tool or service here before it can act.',
  authority: 'The route cannot continue until the required permission is present.',
  phase: 'Several low-level interactions become one understandable stretch of the journey.',
  effect: 'This is where the agent touches the outside world to advance the outcome.',
  evidence: 'The agent looks back from here and checks whether the work really succeeded.',
  artifact: 'Verified work arrives here as something the user can keep or use.',
  blocker: 'Progress stopped here; the obstruction remains visible rather than being hidden.',
  recovery: 'A corrected route reconnects the agent to the intended journey.',
  milestone: 'The journey crosses a boundary worth remembering.',
  learning: 'Knowledge discovered on the route is preserved here.',
  play_candidate: 'A successful route is compressed here into a reusable blueprint.',
  play: 'The blueprint becomes a route that another journey can follow.',
}

const INK_SOFT = 0x565c5f
const INK_DARK = 0x24282b
const GROUND = 0x080a0c
const AMBER = 0xe88413

function formatNumber(value) {
  const number = Number(value || 0)
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`
  if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 1 : 2)}K`
  return String(number)
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]))
}

function journeyPositions(chapters) {
  return chapters.map((chapter, index) => {
    const x = Math.sin(index * .72) * 12 + Math.sin(index * .23) * 4
    return new THREE.Vector3(x, 0, index * -21)
  })
}

function material(color = INK_SOFT, options = {}) {
  return new THREE.MeshStandardMaterial({
    color, roughness: options.roughness ?? .82, metalness: options.metalness ?? .08,
    transparent: options.opacity !== undefined, opacity: options.opacity ?? 1,
  })
}

function box(group, size, position, color = INK_SOFT) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material(color))
  mesh.position.set(...position)
  mesh.castShadow = true
  mesh.receiveShadow = true
  group.add(mesh)
  return mesh
}

function beamBetween(group, source, target, width = .22, color = INK_SOFT) {
  const delta = target.clone().sub(source)
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, width, delta.length()), material(color))
  mesh.position.copy(source).add(target).multiplyScalar(.5)
  mesh.lookAt(target)
  mesh.castShadow = true
  group.add(mesh)
  return mesh
}

function landmarkFor(chapter) {
  const group = new THREE.Group()
  const pale = 0x767c7e
  const gray = INK_SOFT
  const dark = INK_DARK

  if (chapter.kind === 'intent') {
    box(group, [.7, 5.4, .7], [-3.8, 2.7, 0], pale)
    box(group, [.7, 5.4, .7], [3.8, 2.7, 0], pale)
    box(group, [8.3, .7, .7], [0, 5.1, 0], pale)
  } else if (chapter.kind === 'decision') {
    beamBetween(group, new THREE.Vector3(0, .18, 3), new THREE.Vector3(-4.8, .18, -3.8), .32, pale)
    beamBetween(group, new THREE.Vector3(0, .18, 3), new THREE.Vector3(4.8, .18, -3.8), .32, pale)
    box(group, [.8, 3.8, .8], [0, 1.9, 1], gray)
  } else if (chapter.kind === 'capability') {
    box(group, [2.5, 5.8, 2.5], [-3.8, 2.9, 0], pale)
    box(group, [2.5, 5.8, 2.5], [3.8, 2.9, 0], pale)
    box(group, [4.6, .35, .9], [0, 1.15, -1.8], gray)
  } else if (chapter.kind === 'authority') {
    box(group, [.55, 6.2, .55], [-4.2, 3.1, 0], pale)
    box(group, [.55, 6.2, .55], [4.2, 3.1, 0], pale)
    box(group, [9, .55, .55], [0, 5.9, 0], pale)
    for (let x = -3; x <= 3; x += 1.5) box(group, [.18, 4.5, .18], [x, 2.25, 0], gray)
  } else if (chapter.kind === 'effect') {
    box(group, [2.8, 7.6, 2.8], [-4, 3.8, .4], pale)
    box(group, [2.2, 4.9, 2.2], [3.7, 2.45, -.8], gray)
    box(group, [1.7, 3, 1.7], [5.4, 1.5, 1.4], dark)
  } else if (chapter.kind === 'evidence') {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(3.5, .22, 12, 64), material(pale))
    ring.rotation.x = Math.PI / 2
    ring.position.y = 3.6
    ring.castShadow = true
    group.add(ring)
    box(group, [.35, 4.8, .35], [0, 2.4, 0], gray)
  } else if (chapter.kind === 'blocker') {
    beamBetween(group, new THREE.Vector3(-4.6, .4, 0), new THREE.Vector3(4.6, 5.5, 0), .72, pale)
    beamBetween(group, new THREE.Vector3(4.6, .4, 0), new THREE.Vector3(-4.6, 5.5, 0), .72, pale)
  } else if (chapter.kind === 'recovery') {
    box(group, [.7, 4.5, .7], [-4.2, 2.25, 0], pale)
    box(group, [.7, 4.5, .7], [4.2, 2.25, 0], pale)
    const arch = new THREE.Mesh(new THREE.TorusGeometry(4.2, .36, 12, 48, Math.PI), material(pale))
    arch.position.y = 4.4
    arch.rotation.z = Math.PI
    group.add(arch)
  } else if (chapter.kind === 'milestone') {
    const obelisk = new THREE.Mesh(new THREE.CylinderGeometry(.45, 1.5, 8.2, 4), material(pale))
    obelisk.position.y = 4.1
    obelisk.rotation.y = Math.PI / 4
    obelisk.castShadow = true
    group.add(obelisk)
  } else if (chapter.kind === 'artifact' || chapter.kind === 'play_candidate' || chapter.kind === 'play') {
    box(group, [6.5, 4.5, 5], [0, 2.25, 0], pale)
    box(group, [3.4, 3.2, .32], [0, 1.6, 2.64], dark)
    box(group, [.35, 1.3, .35], [0, 1.6, 2.86], gray)
  } else {
    box(group, [5.8, .45, 5.8], [0, .22, 0], gray)
    box(group, [.45, 3.8, .45], [-2.7, 1.9, -2.7], pale)
    box(group, [.45, 3.8, .45], [2.7, 1.9, -2.7], pale)
    box(group, [5.8, .45, .45], [0, 3.7, -2.7], pale)
  }
  return group
}

function makeCallout(chapter, count, total, onActivate) {
  const root = document.createElement('button')
  root.type = 'button'
  root.className = 'world-callout'
  root.dataset.site = chapter.id
  root.innerHTML = `
    <span class="callout-index">${String(chapter.order + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}</span>
    <span class="callout-kind">${escapeHtml(KIND_LABEL[chapter.kind] || chapter.kind)}</span>
    <strong>${escapeHtml(chapter.title)}</strong>
    <span class="callout-body">
      <i>WORLD ROLE</i><b>${escapeHtml(WORLD_ROLE[chapter.kind] || 'Journey stage')} · ${escapeHtml(MAP_MEANING[chapter.kind] || 'Advances the requested outcome.')}</b>
      <i>WHAT HAPPENED</i><b>${escapeHtml(chapter.detail || chapter.title)}</b>
      <i>STORY</i><b>${escapeHtml(WORLD_STORY[chapter.kind] || 'The agent advances the requested outcome here.')}</b>
      <i>PROOF</i><b>${count} recorded interaction${count === 1 ? '' : 's'} · ${formatNumber(chapter.telemetry?.duration_ms)} ms · ${formatNumber(chapter.telemetry?.payload_tokens)} tokens</b>
    </span>`
  root.addEventListener('click', (event) => {
    event.stopPropagation()
    onActivate(chapter.id)
  })
  const label = new CSS2DObject(root)
  label.position.set(0, 4.9, 0)
  label.center.set(.5, 1)
  return {label, root}
}

function makeInteractionCallout(record, chapter, index, onActivate) {
  const root = document.createElement('button')
  root.type = 'button'
  root.className = 'world-interaction-callout'
  root.style.setProperty('--arrival-delay', `${index * 110}ms`)
  root.setAttribute('aria-label', `Inspect interaction ${record.sequence}: ${record.operation}`)
  root.innerHTML = `<span>@${String(record.sequence).padStart(2, '0')}</span><strong>${escapeHtml(record.operation)}</strong><i>OPEN EVIDENCE</i>`
  root.addEventListener('click', (event) => {
    event.stopPropagation()
    onActivate({siteId: chapter.id, sequence: record.sequence})
  })
  const anchor = document.createElement('div')
  anchor.className = 'world-interaction-anchor'
  anchor.appendChild(root)
  const label = new CSS2DObject(anchor)
  label.center.set(.5, 1)
  return {label, root, sequence: record.sequence}
}

function clampVisibleCallouts(labelLayer, viewport) {
  const bounds = viewport.getBoundingClientRect()
  const horizontalInset = 18
  const topInset = 18
  const bottomInset = 82
  const callouts = labelLayer.querySelectorAll(
    '.world-callout.expanded, .world-callout.current, .world-callout.frozen, .world-interaction-callout.proximity, .world-interaction-callout.selected',
  )
  callouts.forEach((callout) => {
    callout.style.marginLeft = '0px'
    callout.style.marginTop = '0px'
    const rect = callout.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    let offsetX = 0
    let offsetY = 0
    if (rect.left < bounds.left + horizontalInset) offsetX = bounds.left + horizontalInset - rect.left
    else if (rect.right > bounds.right - horizontalInset) offsetX = bounds.right - horizontalInset - rect.right
    if (rect.top < bounds.top + topInset) offsetY = bounds.top + topInset - rect.top
    else if (rect.bottom > bounds.bottom - bottomInset) offsetY = bounds.bottom - bottomInset - rect.bottom
    callout.style.marginLeft = `${Math.round(offsetX)}px`
    callout.style.marginTop = `${Math.round(offsetY)}px`
  })
}

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

      const actionableMeshes = interactionMeshes.concat(semanticMeshes)
      const raycaster = new THREE.Raycaster()
      const pointer = new THREE.Vector2()
      let lookYaw = 0
      let lookPitch = 0
      let pointerDown = false
      let pointerMoved = false
      let pointerX = 0
      let pointerY = 0
      const walkOffset = new THREE.Vector3()
      const currentLookDirection = new THREE.Vector3(0, 0, -1)
      const onPointerDown = (event) => {
        if (!frozenRef.current || event.button !== 0) return
        pointerDown = true
        pointerMoved = false
        pointerX = event.clientX
        pointerY = event.clientY
        renderer.domElement.classList.add('looking')
        renderer.domElement.setPointerCapture?.(event.pointerId)
      }
      const onPointerMove = (event) => {
        if (!pointerDown) {
          const bounds = renderer.domElement.getBoundingClientRect()
          pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
          pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
          raycaster.setFromCamera(pointer, camera)
          const actionable = raycaster.intersectObjects(actionableMeshes, false)[0]
          renderer.domElement.classList.toggle('vantage-hover', Boolean(actionable))
          return
        }
        if (!frozenRef.current) return
        const deltaX = event.clientX - pointerX
        const deltaY = event.clientY - pointerY
        if (Math.abs(deltaX) + Math.abs(deltaY) > 2) pointerMoved = true
        lookYaw -= deltaX * .006
        lookPitch = THREE.MathUtils.clamp(lookPitch - deltaY * .0045, -.82, .82)
        pointerX = event.clientX
        pointerY = event.clientY
      }
      const onPointerUp = (event) => {
        pointerDown = false
        renderer.domElement.classList.remove('looking')
        renderer.domElement.releasePointerCapture?.(event.pointerId)
      }
      const onWheel = (event) => {
        if (!frozenRef.current) return
        event.preventDefault()
        const stride = THREE.MathUtils.clamp(-event.deltaY * .008, -1.8, 1.8)
        const groundDirection = currentLookDirection.clone().setY(0)
        if (groundDirection.lengthSq() < .001) return
        groundDirection.normalize()
        walkOffset.addScaledVector(groundDirection, stride)
        if (walkOffset.length() > 12) walkOffset.setLength(12)
      }
      const onPointer = (event) => {
        if (pointerMoved) {
          pointerMoved = false
          return
        }
        const bounds = renderer.domElement.getBoundingClientRect()
        pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
        pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
        raycaster.setFromCamera(pointer, camera)
        const interactionHit = raycaster.intersectObjects(interactionMeshes, false)[0]
        if (interactionHit) {
          onSelect(interactionHit.object.userData)
          return
        }
        const semanticHit = raycaster.intersectObjects(semanticMeshes, false)[0]
        if (semanticHit) {
          onSelect(semanticHit.object.userData)
          return
        }
        if (frozenRef.current) onSelect(null)
      }
      const onKeyDown = (event) => {
        if (!frozenRef.current || event.target instanceof HTMLInputElement || event.target instanceof HTMLButtonElement) return
        const horizontal = event.key === 'ArrowLeft' || event.key.toLowerCase() === 'a' ? .16 : event.key === 'ArrowRight' || event.key.toLowerCase() === 'd' ? -.16 : 0
        const vertical = event.key === 'ArrowUp' || event.key.toLowerCase() === 'w' ? .1 : event.key === 'ArrowDown' || event.key.toLowerCase() === 's' ? -.1 : 0
        if (!horizontal && !vertical) return
        event.preventDefault()
        lookYaw += horizontal
        lookPitch = THREE.MathUtils.clamp(lookPitch + vertical, -.82, .82)
      }
      renderer.domElement.addEventListener('pointerdown', onPointerDown)
      renderer.domElement.addEventListener('pointermove', onPointerMove)
      renderer.domElement.addEventListener('pointerup', onPointerUp)
      renderer.domElement.addEventListener('pointercancel', onPointerUp)
      renderer.domElement.addEventListener('wheel', onWheel, {passive: false})
      renderer.domElement.addEventListener('click', onPointer)
      window.addEventListener('keydown', onKeyDown)

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
          const baseYaw = Math.atan2(direction.x, -direction.z)
          const yaw = baseYaw + lookYaw
          const lookDirection = new THREE.Vector3(
            Math.sin(yaw) * Math.cos(lookPitch),
            Math.sin(lookPitch),
            -Math.cos(yaw) * Math.cos(lookPitch),
          )
          currentLookDirection.copy(lookDirection)
          desiredCamera.copy(current).addScaledVector(direction, -1.4)
          desiredCamera.add(walkOffset)
          desiredCamera.y = 2.25
          desiredLook.copy(desiredCamera).addScaledVector(lookDirection, 12)
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
          lookYaw = 0
          lookPitch = 0
          walkOffset.set(0, 0, 0)
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
        window.removeEventListener('keydown', onKeyDown)
        renderer.domElement.removeEventListener('pointerdown', onPointerDown)
        renderer.domElement.removeEventListener('pointermove', onPointerMove)
        renderer.domElement.removeEventListener('pointerup', onPointerUp)
        renderer.domElement.removeEventListener('pointercancel', onPointerUp)
        renderer.domElement.removeEventListener('wheel', onWheel)
        renderer.domElement.removeEventListener('click', onPointer)
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
