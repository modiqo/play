import * as THREE from 'three'
import {CSS2DObject} from 'three/addons/renderers/CSS2DRenderer.js'
import {formatNumber} from './format.js'
import {KIND_LABEL, MAP_MEANING, WORLD_ROLE, WORLD_STORY} from './semantics.js'

const INK_SOFT = 0x565c5f
const INK_DARK = 0x24282b
export const GROUND = 0x080a0c
export const AMBER = 0xe88413

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]))
}

export function journeyPositions(chapters) {
  return chapters.map((chapter, index) => {
    const x = Math.sin(index * .72) * 12 + Math.sin(index * .23) * 4
    return new THREE.Vector3(x, 0, index * -21)
  })
}

export function material(color = INK_SOFT, options = {}) {
  return new THREE.MeshStandardMaterial({
    color, roughness: options.roughness ?? .82, metalness: options.metalness ?? .08,
    transparent: options.opacity !== undefined, opacity: options.opacity ?? 1,
  })
}

export function glassTowerMaterial() {
  return new THREE.MeshPhysicalMaterial({
    color: 0x555d61,
    roughness: .24,
    metalness: .08,
    transmission: .24,
    thickness: .72,
    ior: 1.38,
    clearcoat: .72,
    clearcoatRoughness: .2,
    transparent: true,
    opacity: .34,
    depthWrite: false,
    emissive: AMBER,
    emissiveIntensity: .015,
  })
}

export function glassTowerEdge(geometry) {
  const edge = new THREE.LineSegments(
    new THREE.EdgesGeometry(geometry, 24),
    new THREE.LineBasicMaterial({color: AMBER, transparent: true, opacity: .14}),
  )
  edge.renderOrder = 3
  return edge
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

function effectCrater(group) {
  const radialSegments = 40
  const angularSegments = 128
  const radius = 4.25
  const baseHeight = .215
  const positions = [0, baseHeight, 0]
  const indices = []
  const colors = []
  const basinColor = new THREE.Color(0x171b1d)
  const terrainColor = new THREE.Color(0x303638)
  const rimColor = new THREE.Color(0x596062)
  colors.push(basinColor.r, basinColor.g, basinColor.b)

  for (let ring = 1; ring <= radialSegments; ring += 1) {
    const radial = ring / radialSegments * radius
    const edgeFade = 1 - THREE.MathUtils.smoothstep(radial, 3.55, radius)
    for (let segment = 0; segment < angularSegments; segment += 1) {
      const angle = segment / angularSegments * Math.PI * 2
      const rimVariation = 1 + Math.sin(angle * 5 + .7) * .055 + Math.sin(angle * 9 - .4) * .025
      const effectiveRadius = radial / rimVariation
      const bowl = effectiveRadius < 2.55
        ? .18 * Math.pow(effectiveRadius / 2.55, 1.7)
        : .18 * Math.exp(-Math.pow((effectiveRadius - 2.55) / .72, 2))
      const raisedRim = .58 * Math.exp(-Math.pow((effectiveRadius - 2.82) / .38, 2))
      const erosion = (
        Math.sin(angle * 7 + radial * 2.1) * .022 +
        Math.sin(angle * 13 - radial * 1.35) * .012
      ) * edgeFade
      const height = baseHeight + (bowl + raisedRim) * edgeFade + erosion
      positions.push(Math.cos(angle) * radial, height, Math.sin(angle) * radial)

      const elevation = THREE.MathUtils.clamp((height - baseHeight) / .72, 0, 1)
      const color = terrainColor.clone().lerp(rimColor, elevation)
      if (effectiveRadius < 1.55) color.lerp(basinColor, .72 * (1 - effectiveRadius / 1.55))
      colors.push(color.r, color.g, color.b)
    }
  }

  for (let segment = 0; segment < angularSegments; segment += 1) {
    indices.push(0, 1 + (segment + 1) % angularSegments, 1 + segment)
  }
  for (let ring = 1; ring < radialSegments; ring += 1) {
    const inner = 1 + (ring - 1) * angularSegments
    const outer = inner + angularSegments
    for (let segment = 0; segment < angularSegments; segment += 1) {
      const next = (segment + 1) % angularSegments
      indices.push(inner + segment, inner + next, outer + next)
      indices.push(inner + segment, outer + next, outer + segment)
    }
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  const crater = new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({vertexColors: true, roughness: .92, metalness: .01, side: THREE.DoubleSide}),
  )
  crater.castShadow = true
  crater.receiveShadow = true
  group.add(crater)
}

export function landmarkFor(chapter) {
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
    effectCrater(group)
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

export function makeCallout(chapter, count, total, onActivate) {
  const root = document.createElement('button')
  root.type = 'button'
  root.className = 'world-callout'
  root.dataset.site = chapter.id
  root.innerHTML = `
    <span class="callout-index">${String(chapter.order + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}</span>
    <span class="callout-kind">${escapeHtml(WORLD_ROLE[chapter.kind] || 'Journey stage')} · ${escapeHtml(KIND_LABEL[chapter.kind] || chapter.kind)}</span>
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

export function makeInteractionCallout(record, chapter, index, onActivate) {
  const root = document.createElement('button')
  root.type = 'button'
  root.className = 'world-interaction-callout'
  root.dataset.rank = String(index)
  root.dataset.side = Number(record.temporal?.x || 0) < 0 ? 'left' : 'right'
  root.style.setProperty('--arrival-delay', `${index * 110}ms`)
  root.setAttribute('aria-label', `Inspect interaction ${record.sequence}: ${record.operation}`)
  const posture = String(record.effect_profile?.posture || record.effect || 'unknown').toUpperCase()
  const temporal = record.temporal?.deltaLabel ? `${record.temporal.deltaLabel} · ` : ''
  root.innerHTML = `<span>@${String(record.sequence).padStart(2, '0')}</span><strong>${escapeHtml(record.operation)}</strong><i>${escapeHtml(temporal)}${escapeHtml(posture)} · OPEN EVIDENCE</i>`
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

export function clampVisibleCallouts(labelLayer, viewport) {
  const bounds = viewport.getBoundingClientRect()
  const horizontalInset = 16
  const topInset = 76
  const bottomInset = 66
  const gap = 9
  const callouts = [...labelLayer.querySelectorAll(
    '.world-callout.expanded, .world-callout.current, .world-callout.frozen, .world-interaction-callout.proximity, .world-interaction-callout.selected',
  )]
  const shell = viewport.closest('main') || viewport.parentElement
  const obstacles = shell ? [...shell.querySelectorAll('.journey-guide, .landmark-panel.visible, .capability-rail')]
    .filter((node) => node.offsetWidth > 0 && node.offsetHeight > 0)
    .map((node) => node.getBoundingClientRect()) : []
  const intersects = (left, right) => !(
    left.right + gap <= right.left || left.left >= right.right + gap ||
    left.bottom + gap <= right.top || left.top >= right.bottom + gap
  )
  const translated = (rect, x, y) => ({left: rect.left + x, right: rect.right + x, top: rect.top + y, bottom: rect.bottom + y})
  const inside = (rect) => rect.left >= bounds.left + horizontalInset && rect.right <= bounds.right - horizontalInset && rect.top >= bounds.top + topInset && rect.bottom <= bounds.bottom - bottomInset
  const placed = []
  callouts.forEach((callout) => {
    callout.style.marginLeft = '0px'
    callout.style.marginTop = '0px'
  })
  callouts.sort((left, right) => {
    const priority = (node) => node.classList.contains('selected') ? 0 : node.classList.contains('world-callout') ? 1 : 2
    return priority(left) - priority(right) || Number(left.dataset.rank || 0) - Number(right.dataset.rank || 0)
  }).forEach((callout) => {
    const rect = callout.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const edgeX = Math.max(bounds.left + horizontalInset - rect.left, Math.min(0, bounds.right - horizontalInset - rect.right))
    const edgeY = Math.max(bounds.top + topInset - rect.top, Math.min(0, bounds.bottom - bottomInset - rect.bottom))
    const direction = callout.dataset.side === 'right' ? 1 : -1
    const xOffsets = callout.classList.contains('world-callout') ? [edgeX] : [edgeX, edgeX + direction * 38, edgeX - direction * 38, edgeX + direction * 78]
    const verticalStep = rect.height + gap
    const yOffsets = [edgeY]
    for (let level = 1; level <= callouts.length; level += 1) {
      yOffsets.push(edgeY + verticalStep * level, edgeY - verticalStep * level)
    }
    let chosen = translated(rect, edgeX, edgeY)
    let chosenOffset = [edgeX, edgeY]
    search: for (const offsetX of xOffsets) {
      for (const offsetY of yOffsets) {
        const candidate = translated(rect, offsetX, offsetY)
        if (!inside(candidate)) continue
        if (obstacles.some((obstacle) => intersects(candidate, obstacle))) continue
        if (placed.some((other) => intersects(candidate, other))) continue
        chosen = candidate
        chosenOffset = [offsetX, offsetY]
        break search
      }
    }
    callout.style.marginLeft = `${Math.round(chosenOffset[0])}px`
    callout.style.marginTop = `${Math.round(chosenOffset[1])}px`
    placed.push(chosen)
  })
}
