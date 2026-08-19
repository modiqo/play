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

export function makeCallout(chapter, count, total, onActivate) {
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

export function makeInteractionCallout(record, chapter, index, onActivate) {
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

export function clampVisibleCallouts(labelLayer, viewport) {
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


