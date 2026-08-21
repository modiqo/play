import * as THREE from 'three'
import {CSS2DObject} from 'three/addons/renderers/CSS2DRenderer.js'
import {horizontalCalloutOffsets} from './callout-layout.mjs'
import {formatNumber} from './format.js'
import {journeyCoordinates} from './journey-layout.mjs'
import {KIND_LABEL, MAP_MEANING, WORLD_ROLE, WORLD_STORY, worldSpec} from './semantics.js'

export const STRUCTURE_COLORS = Object.freeze({
  pale: 0x3a3732,
  soft: 0x292826,
  dark: 0x1b1c1b,
})
const INK_SOFT = STRUCTURE_COLORS.soft
const INK_DARK = STRUCTURE_COLORS.dark
export const GROUND = 0x1b2225
export const AMBER = 0xe88413

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]))
}

export function journeyPositions(chapters) {
  return journeyCoordinates(chapters).map(({x, y, z}) => new THREE.Vector3(x, y, z))
}

export function material(color = INK_SOFT, options = {}) {
  return new THREE.MeshStandardMaterial({
    color, roughness: options.roughness ?? .88, metalness: options.metalness ?? .035,
    emissive: options.emissive ?? color, emissiveIntensity: options.emissiveIntensity ?? .025,
    transparent: options.opacity !== undefined, opacity: options.opacity ?? 1,
    dithering: true,
  })
}

export function glassBeadMaterial() {
  return new THREE.MeshPhysicalMaterial({
    color: 0x748084,
    roughness: .2,
    metalness: .04,
    transmission: .12,
    thickness: .64,
    ior: 1.34,
    clearcoat: .86,
    clearcoatRoughness: .16,
    transparent: true,
    opacity: .4,
    depthWrite: true,
    side: THREE.DoubleSide,
    emissive: 0x8e999d,
    emissiveIntensity: .012,
  })
}

export function glassBeadGeometry(radius = 1) {
  return new THREE.IcosahedronGeometry(radius, 3)
}

export function eventHaloMaterial() {
  return new THREE.MeshBasicMaterial({color: AMBER, transparent: true, opacity: .14, depthTest: true})
}

export function makeInteractionIndex(record, onActivate) {
  const root = document.createElement('button')
  root.type = 'button'
  root.className = 'world-interaction-index'
  root.textContent = `@${String(record.sequence).padStart(2, '0')}`
  root.setAttribute('aria-label', `Inspect interaction ${record.sequence}: ${record.operation}`)
  root.addEventListener('click', (event) => {
    event.stopPropagation()
    onActivate({siteId: record.siteId, sequence: record.sequence})
  })
  const label = new CSS2DObject(root)
  label.center.set(.5, .5)
  return {label, root}
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
  const pale = STRUCTURE_COLORS.pale
  const gray = INK_SOFT
  const dark = INK_DARK
  const landmark = worldSpec(chapter.kind).landmark
  const modality = chapter.modalities?.[0]

  if (landmark === 'gate') {
    box(group, [.7, 5.4, .7], [-3.8, 2.7, 0], pale)
    box(group, [.7, 5.4, .7], [3.8, 2.7, 0], pale)
    box(group, [8.3, .7, .7], [0, 5.1, 0], pale)
  } else if (landmark === 'fork') {
    beamBetween(group, new THREE.Vector3(0, .18, 3), new THREE.Vector3(-4.8, .18, -3.8), .32, pale)
    beamBetween(group, new THREE.Vector3(0, .18, 3), new THREE.Vector3(4.8, .18, -3.8), .32, pale)
    box(group, [.8, 3.8, .8], [0, 1.9, 1], gray)
  } else if (landmark === 'station') {
    box(group, [2.5, 5.8, 2.5], [-3.8, 2.9, 0], pale)
    box(group, [2.5, 5.8, 2.5], [3.8, 2.9, 0], pale)
    box(group, [4.6, .35, .9], [0, 1.15, -1.8], gray)
    if (modality === 'call') {
      for (const x of [-1.4, 0, 1.4]) box(group, [.55, .55, .55], [x, 2.15, -2.05], AMBER)
    } else if (modality === 'shell') {
      box(group, [4.4, 2.7, .28], [0, 3.1, -2.05], dark)
      box(group, [3.4, .18, .2], [0, 2.65, -2.23], AMBER)
    } else if (modality === 'drive') {
      const lens = new THREE.Mesh(new THREE.TorusGeometry(1.35, .18, 10, 36), material(AMBER))
      lens.position.set(0, 3.2, -2.15)
      group.add(lens)
    }
  } else if (landmark === 'checkpoint') {
    box(group, [.55, 6.2, .55], [-4.2, 3.1, 0], pale)
    box(group, [.55, 6.2, .55], [4.2, 3.1, 0], pale)
    box(group, [9, .55, .55], [0, 5.9, 0], pale)
    for (let x = -3; x <= 3; x += 1.5) box(group, [.18, 4.5, .18], [x, 2.25, 0], gray)
  } else if (landmark === 'crater') {
    effectCrater(group)
  } else if (landmark === 'observatory') {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(3.5, .22, 12, 64), material(pale))
    ring.rotation.x = Math.PI / 2
    ring.position.y = 3.6
    ring.castShadow = true
    group.add(ring)
    box(group, [.35, 4.8, .35], [0, 2.4, 0], gray)
  } else if (landmark === 'barricade') {
    beamBetween(group, new THREE.Vector3(-4.6, .4, 0), new THREE.Vector3(4.6, 5.5, 0), .72, pale)
    beamBetween(group, new THREE.Vector3(4.6, .4, 0), new THREE.Vector3(-4.6, 5.5, 0), .72, pale)
  } else if (landmark === 'bridge') {
    box(group, [.7, 4.5, .7], [-4.2, 2.25, 0], pale)
    box(group, [.7, 4.5, .7], [4.2, 2.25, 0], pale)
    const arch = new THREE.Mesh(new THREE.TorusGeometry(4.2, .36, 12, 48, Math.PI), material(pale))
    arch.position.y = 4.4
    arch.rotation.z = Math.PI
    group.add(arch)
  } else if (landmark === 'monument') {
    const obelisk = new THREE.Mesh(new THREE.CylinderGeometry(.45, 1.5, 8.2, 4), material(pale))
    obelisk.position.y = 4.1
    obelisk.rotation.y = Math.PI / 4
    obelisk.castShadow = true
    group.add(obelisk)
  } else if (landmark === 'archive') {
    box(group, [6.4, 5.2, 1.2], [0, 2.6, 0], dark)
    for (const y of [1.1, 2.6, 4.1]) box(group, [5.7, .2, 1.45], [0, y, 0], pale)
    for (const x of [-2.1, -.7, .7, 2.1]) box(group, [.16, 4.4, 1.4], [x, 2.6, 0], gray)
  } else if (landmark === 'blueprint') {
    box(group, [7.2, .22, 5.2], [0, .18, 0], dark)
    beamBetween(group, new THREE.Vector3(-3.1, .42, -2), new THREE.Vector3(3.1, .42, 2), .16, pale)
    beamBetween(group, new THREE.Vector3(3.1, .42, -2), new THREE.Vector3(-3.1, .42, 2), .16, pale)
    for (const x of [-3.1, 3.1]) for (const z of [-2, 2]) box(group, [.24, 2.8, .24], [x, 1.4, z], AMBER)
  } else if (landmark === 'gateway') {
    box(group, [.7, 5.4, .7], [-3.8, 2.7, 0], pale)
    box(group, [.7, 5.4, .7], [3.8, 2.7, 0], pale)
    const gateway = new THREE.Mesh(new THREE.TorusGeometry(3.8, .42, 12, 48, Math.PI), material(AMBER))
    gateway.position.y = 5.2
    gateway.rotation.z = Math.PI
    group.add(gateway)
  } else if (landmark === 'destination') {
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

export function makeInteractionPlaque(group, chapter, index, onActivate) {
  const root = document.createElement('div')
  root.className = 'world-interaction-callout world-interaction-plaque'
  root.dataset.rank = String(index)
  root.dataset.side = Number(group.x || 0) < 0 ? 'left' : 'right'
  root.style.setProperty('--arrival-delay', `${index * 110}ms`)

  const trigger = document.createElement('button')
  trigger.type = 'button'
  trigger.className = 'plaque-trigger'
  trigger.setAttribute('aria-expanded', 'false')
  trigger.setAttribute('aria-label', group.count > 1
    ? `Open ${group.count} related interactions ${group.label}`
    : `Inspect interaction ${group.sequences[0]}`)
  trigger.innerHTML = `
    <span>${escapeHtml(group.label)}</span>
    <strong>${escapeHtml(group.system)}${group.count > 1 ? ` · ${group.count}` : ''}</strong>
    <i>${escapeHtml(group.deltaLabel)} · ${escapeHtml(group.posture.toUpperCase())} · ${group.count > 1 ? 'OPEN GROUP' : 'OPEN EVIDENCE'}</i>`

  const tray = document.createElement('div')
  tray.className = 'plaque-tray'
  group.records.forEach((record) => {
    const item = document.createElement('button')
    item.type = 'button'
    item.innerHTML = `<span>@${String(record.sequence).padStart(2, '0')}</span><b>${escapeHtml(record.operation)}</b>`
    item.addEventListener('click', (event) => {
      event.stopPropagation()
      onActivate({siteId: chapter.id, sequence: record.sequence})
    })
    tray.appendChild(item)
  })

  trigger.addEventListener('click', (event) => {
    event.stopPropagation()
    if (group.count === 1) {
      onActivate({siteId: chapter.id, sequence: group.sequences[0]})
      return
    }
    const spread = root.classList.toggle('spread')
    trigger.setAttribute('aria-expanded', String(spread))
  })
  root.append(trigger, tray)

  const anchor = document.createElement('div')
  anchor.className = 'world-interaction-anchor world-interaction-plaque-anchor'
  anchor.appendChild(root)
  const label = new CSS2DObject(anchor)
  label.center.set(.5, 0)
  return {label, root, trigger, sequences: group.sequences, records: group.records}
}

export function makeTemporalCorridor(site, corridor) {
  const group = new THREE.Group()
  const timeLabels = []
  const [start, end] = corridor.spine
  beamBetween(
    group,
    new THREE.Vector3(start.x, .13, start.z),
    new THREE.Vector3(end.x, .13, end.z),
    .055,
    AMBER,
  )
  corridor.points.forEach((point) => {
    box(group, [.035, .12, .42], [point.baseX, .13, point.baseZ], point.order === corridor.points.length - 1 ? AMBER : INK_SOFT)
  })
  for (const [position, copy, side] of [
    [corridor.entrance, corridor.labels?.entrance || 'PAST', 'past'],
    [corridor.exit, corridor.labels?.exit || 'PRESENT', 'present'],
  ]) {
    const root = document.createElement('span')
    root.className = `world-time-label ${side}`
    root.textContent = copy
    const label = new CSS2DObject(root)
    label.position.set(position.x, .08, position.z + .34)
    group.add(label)
    timeLabels.push(root)
  }
  group.userData = {siteId: site.id, temporalCorridor: true, timeLabels}
  return group
}

export function clampVisibleCallouts(labelLayer, viewport) {
  const bounds = viewport.getBoundingClientRect()
  const horizontalInset = 16
  const topInset = 76
  const bottomInset = 66
  const gap = 9
  const callouts = [...labelLayer.querySelectorAll(
    '.world-callout.expanded:not(.in-transit), .world-callout.current:not(.in-transit), .world-callout.frozen:not(.in-transit), .world-interaction-callout.proximity, .world-interaction-callout.selected',
  )]
  const shell = viewport.closest('main') || viewport.parentElement
  const obstacles = shell ? [...shell.querySelectorAll('.follow-instruments, .journey-guide, .landmark-panel.visible, .capability-rail')]
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
    callout.classList.remove('layout-hidden')
  })
  callouts.sort((left, right) => {
    const priority = (node) => node.classList.contains('world-callout') ? 0 : node.classList.contains('selected') ? 1 : 2
    return priority(left) - priority(right) || Number(left.dataset.rank || 0) - Number(right.dataset.rank || 0)
  }).forEach((callout) => {
    const rect = callout.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const edgeX = Math.max(bounds.left + horizontalInset - rect.left, Math.min(0, bounds.right - horizontalInset - rect.right))
    const edgeY = Math.max(bounds.top + topInset - rect.top, Math.min(0, bounds.bottom - bottomInset - rect.bottom))
    const direction = callout.dataset.side === 'right' ? 1 : -1
    const xOffsets = horizontalCalloutOffsets({
      edgeX,
      width: rect.width,
      worldCallout: callout.classList.contains('world-callout'),
      direction,
    })
    const verticalStep = rect.height + gap
    const yOffsets = [edgeY]
    for (let level = 1; level <= callouts.length; level += 1) {
      yOffsets.push(edgeY + verticalStep * level, edgeY - verticalStep * level)
    }
    let chosen = null
    let chosenOffset = [edgeX, edgeY]
    const worldCallout = callout.classList.contains('world-callout')
    const primaryOffsets = worldCallout ? yOffsets : xOffsets
    const secondaryOffsets = worldCallout ? xOffsets : yOffsets
    search: for (const primary of primaryOffsets) {
      for (const secondary of secondaryOffsets) {
        const offsetX = worldCallout ? secondary : primary
        const offsetY = worldCallout ? primary : secondary
        const candidate = translated(rect, offsetX, offsetY)
        if (!inside(candidate)) continue
        if (obstacles.some((obstacle) => intersects(candidate, obstacle))) continue
        if (placed.some((other) => intersects(candidate, other))) continue
        chosen = candidate
        chosenOffset = [offsetX, offsetY]
        break search
      }
    }
    if (!chosen) {
      if (callout.classList.contains('world-interaction-callout')) callout.classList.add('layout-hidden')
      return
    }
    callout.style.marginLeft = `${Math.round(chosenOffset[0])}px`
    callout.style.marginTop = `${Math.round(chosenOffset[1])}px`
    placed.push(chosen)
  })
}
