import * as THREE from 'three'
import {CSS2DObject} from 'three/addons/renderers/CSS2DRenderer.js'
import {horizontalCalloutOffsets} from './callout-layout.mjs'
import {formatNumber} from './format.js'
import {journeyCoordinates} from './journey-layout.mjs'
import {KIND_LABEL, MAP_MEANING, WORLD_ROLE, WORLD_STORY, worldSpec} from './semantics.js'

export const STRUCTURE_COLORS = Object.freeze({
  pale: 0xc99a59,
  soft: 0x6f5843,
  dark: 0x263a3b,
})
const INK_SOFT = STRUCTURE_COLORS.soft
const INK_DARK = STRUCTURE_COLORS.dark
export const GROUND = 0x22383b
export const AMBER = 0xffa52f
const SITE_VERB = Object.freeze({
  intent: 'AIM', decision: 'CHOOSE', capability: 'EQUIP', authority: 'AUTHORIZE', phase: 'ENTER',
  effect: 'ACT', evidence: 'VERIFY', artifact: 'KEEP', blocker: 'BLOCKED', recovery: 'RECOVER',
  milestone: 'REACHED', learning: 'REMEMBER', play_candidate: 'SHAPE', play: 'RECALL',
})

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]))
}

export function journeyPositions(chapters) {
  return journeyCoordinates(chapters).map(({x, y, z}) => new THREE.Vector3(x, y, z))
}

export function material(color = INK_SOFT, options = {}) {
  return new THREE.MeshStandardMaterial({
    color, roughness: options.roughness ?? .84, metalness: options.metalness ?? .025,
    emissive: options.emissive ?? color, emissiveIntensity: options.emissiveIntensity ?? .025,
    transparent: options.opacity !== undefined, opacity: options.opacity ?? 1,
    dithering: true, flatShading: options.flatShading ?? true,
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

export function makeVantageBubble(chapter) {
  const group = new THREE.Group()
  group.name = `vantage-bubble:${chapter.id}`
  const color = chapter.kind === 'authority' || chapter.kind === 'blocker'
    ? 0xff7043
    : chapter.kind === 'capability'
      ? capabilityIdentity(chapter).color
      : chapter.kind === 'recovery'
        ? 0x65e2b1
        : 0xffc857
  const shell = new THREE.Mesh(
    new THREE.IcosahedronGeometry(.3, 2),
    new THREE.MeshPhysicalMaterial({
      color, emissive: color, emissiveIntensity: .32, roughness: .12, metalness: .02,
      transmission: .28, thickness: .65, ior: 1.32, clearcoat: 1, clearcoatRoughness: .1,
      transparent: true, opacity: .72,
    }),
  )
  shell.castShadow = true
  shell.userData.worldMotion = 'vantage-bubble'
  const nucleus = new THREE.Mesh(
    new THREE.SphereGeometry(.075, 14, 9),
    new THREE.MeshBasicMaterial({color: 0xfff2ce}),
  )
  nucleus.userData.worldMotion = 'vantage-nucleus'
  group.add(shell, nucleus)
  group.userData = {color, shell, nucleus}
  return group
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

function mesh(group, geometry, color = INK_SOFT, {position = [0, 0, 0], rotation = [0, 0, 0], materialOptions = {}, motion = ''} = {}) {
  const object = new THREE.Mesh(geometry, material(color, materialOptions))
  object.position.set(...position)
  object.rotation.set(...rotation)
  object.castShadow = true
  object.receiveShadow = true
  if (motion) object.userData.worldMotion = motion
  object.userData.baseY = object.position.y
  group.add(object)
  return object
}

function taperedPillar(group, x, height, color = STRUCTURE_COLORS.pale, radius = 1.05) {
  return mesh(group, new THREE.CylinderGeometry(radius * .72, radius, height, 6), color, {position: [x, height / 2, 0]})
}

function portalRing(group, radius, color, {y = radius, tube = .48, motion = 'portal'} = {}) {
  return mesh(group, new THREE.TorusGeometry(radius, tube, 6, 32), color, {
    position: [0, y, 0],
    materialOptions: {emissive: color, emissiveIntensity: .34, roughness: .48},
    motion,
  })
}

function steppedBase(group, color = STRUCTURE_COLORS.dark) {
  mesh(group, new THREE.CylinderGeometry(4.6, 5.2, .7, 8), color, {position: [0, .35, 0]})
  mesh(group, new THREE.CylinderGeometry(3.5, 4.2, .75, 8), STRUCTURE_COLORS.soft, {position: [0, 1.05, 0]})
}

export function capabilityIdentity(chapter = {}) {
  const description = `${chapter.title || ''} ${chapter.detail || ''}`.toLowerCase()
  if (description.includes('posthog')) return {name: 'POSTHOG', mark: 'PH', color: 0xffc94a, shape: 'burst'}
  if (description.includes('github')) return {name: 'GITHUB', mark: 'GH', color: 0xa98bff, shape: 'gem'}
  if (description.includes('notion')) return {name: 'NOTION', mark: 'N', color: 0xf3eee4, shape: 'tablet'}
  if (description.includes('browser') || chapter.modalities?.includes('drive')) return {name: 'BROWSER', mark: '◎', color: 0x5be5dc, shape: 'orb'}
  if (chapter.modalities?.includes('shell')) return {name: 'SHELL', mark: '>_', color: 0xff7b43, shape: 'terminal'}
  return {name: 'ADAPTER', mark: 'API', color: 0xffc857, shape: 'gem'}
}

function addToolSigil(group, chapter, color) {
  const identity = capabilityIdentity(chapter)
  let geometry
  if (identity.shape === 'tablet') geometry = new THREE.BoxGeometry(2.45, 2.7, .72)
  else if (identity.shape === 'burst') geometry = new THREE.IcosahedronGeometry(1.55, 0)
  else if (identity.shape === 'orb') geometry = new THREE.SphereGeometry(1.52, 20, 14)
  else if (identity.shape === 'terminal') geometry = new THREE.BoxGeometry(2.8, 1.9, .76)
  else geometry = new THREE.DodecahedronGeometry(1.55, 0)
  const tool = mesh(group, geometry, identity.color || color, {
    position: [0, 5.95, 0],
    materialOptions: {emissive: identity.color || color, emissiveIntensity: 1.45, roughness: .16, metalness: .06},
    motion: 'capability-tool',
  })
  tool.userData.toolName = identity.name
  if (typeof document !== 'undefined') {
    const labelRoot = document.createElement('span')
    labelRoot.className = 'world-tool-label'
    labelRoot.innerHTML = `<b>${escapeHtml(identity.mark)}</b><i>${escapeHtml(identity.name)}</i>`
    const label = new CSS2DObject(labelRoot)
    label.position.set(0, 2.35, 0)
    tool.add(label)
  }
  const light = new THREE.PointLight(identity.color || color, 4.2, 13, 2)
  light.position.set(0, 7.2, 1.5)
  group.add(light)
  return identity
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
    steppedBase(group)
    taperedPillar(group, 0, 10.8, pale, 1.3)
    mesh(group, new THREE.OctahedronGeometry(1.15, 0), 0x56ddd0, {
      position: [0, 11.5, 0], materialOptions: {emissive: 0x56ddd0, emissiveIntensity: 1.5, roughness: .24}, motion: 'beacon',
    })
    portalRing(group, 3.2, AMBER, {y: 5.3, tube: .26, motion: 'beacon-ring'})
  } else if (landmark === 'fork') {
    const entrance = new THREE.LineCurve3(new THREE.Vector3(0, .42, 7.5), new THREE.Vector3(0, .42, 1.25))
    mesh(group, new THREE.TubeGeometry(entrance, 12, .82, 7, false), dark)
    for (const [side, color] of [[-1, 0x5be5dc], [1, AMBER]]) {
      const branch = new THREE.QuadraticBezierCurve3(
        new THREE.Vector3(0, .42, 1.4),
        new THREE.Vector3(side * 2.4, .48, -1.2),
        new THREE.Vector3(side * 7.2, .42, -5.3),
      )
      mesh(group, new THREE.TubeGeometry(branch, 28, .82, 7, false), dark)
      mesh(group, new THREE.TubeGeometry(branch, 28, .105, 5, false), color, {
        materialOptions: {emissive: color, emissiveIntensity: .95, roughness: .34}, motion: `decision-branch-${side < 0 ? 'left' : 'right'}`,
      })
      taperedPillar(group, side * 4.2, 5.6, side < 0 ? gray : pale, .58)
      mesh(group, new THREE.ConeGeometry(.72, 1.9, 4), color, {
        position: [side * 4.2, 5.7, -2.1], rotation: [0, 0, side * -.72],
        materialOptions: {emissive: color, emissiveIntensity: .7}, motion: 'decision-signal',
      })
    }
    mesh(group, new THREE.OctahedronGeometry(.78, 0), 0xf7d889, {
      position: [0, 1.65, .7], materialOptions: {emissive: AMBER, emissiveIntensity: 1.1}, motion: 'decision-core',
    })
  } else if (landmark === 'station') {
    const capability = capabilityIdentity(chapter)
    const powerColor = capability.color || (modality === 'shell' ? 0xff7b43 : modality === 'drive' ? 0x5be5dc : 0xffc857)
    steppedBase(group)
    for (const angle of [0, Math.PI * 2 / 3, Math.PI * 4 / 3]) {
      const x = Math.cos(angle) * 3.35
      const z = Math.sin(angle) * 3.35
      mesh(group, new THREE.CylinderGeometry(.52, .82, 4.5, 6), pale, {position: [x, 3.25, z]})
      mesh(group, new THREE.TorusGeometry(.72, .12, 5, 16), powerColor, {
        position: [x, 5.3, z], rotation: [Math.PI / 2, 0, 0], materialOptions: {emissive: powerColor, emissiveIntensity: .85},
      })
    }
    addToolSigil(group, chapter, powerColor)
    portalRing(group, 3.15, powerColor, {y: 5.8, tube: .12, motion: 'capability-orbit'})
  } else if (landmark === 'checkpoint') {
    taperedPillar(group, -4.25, 9.2, dark, 1.65)
    taperedPillar(group, 4.25, 9.2, dark, 1.65)
    portalRing(group, 4.25, pale, {y: 7.8, tube: .78, motion: 'authority-arch'})
    for (let x = -3.1; x <= 3.1; x += 1.55) {
      mesh(group, new THREE.CylinderGeometry(.16, .23, 6.7, 5), 0xff6b3d, {
        position: [x, 3.55, .05], materialOptions: {emissive: 0xff442c, emissiveIntensity: 1.35, roughness: .35}, motion: 'authority-bar',
      })
    }
    mesh(group, new THREE.IcosahedronGeometry(1.05, 1), AMBER, {
      position: [0, 4.6, .45], materialOptions: {emissive: AMBER, emissiveIntensity: 1.6, roughness: .22}, motion: 'authority-seal',
    })
  } else if (landmark === 'chamber') {
    steppedBase(group)
    taperedPillar(group, -4.6, 8.4, dark, 1.4)
    taperedPillar(group, 4.6, 8.4, dark, 1.4)
    portalRing(group, 4.35, 0x5be5dc, {y: 5.1, tube: .72, motion: 'phase-portal'})
    portalRing(group, 3.45, 0xffb64d, {y: 5.1, tube: .16, motion: 'phase-inner'})
    mesh(group, new THREE.CircleGeometry(3.25, 32), 0x2c7f80, {
      position: [0, 5.1, .32], materialOptions: {emissive: 0x4bd8cd, emissiveIntensity: .38, opacity: .22, roughness: .18}, motion: 'portal-surface',
    })
  } else if (landmark === 'crater') {
    effectCrater(group)
    mesh(group, new THREE.CylinderGeometry(.62, 1.35, 3.8, 7), dark, {position: [0, 1.9, 0]})
    mesh(group, new THREE.OctahedronGeometry(.78, 0), 0xff7b43, {
      position: [0, 4.65, 0], materialOptions: {emissive: 0xff542f, emissiveIntensity: 1.4}, motion: 'effect-core',
    })
  } else if (landmark === 'observatory') {
    steppedBase(group)
    mesh(group, new THREE.CylinderGeometry(.75, 1.4, 6.8, 7), pale, {position: [0, 4.2, 0]})
    mesh(group, new THREE.TorusGeometry(3.4, .35, 6, 32), 0x64e7df, {
      position: [0, 7.15, 0], rotation: [Math.PI / 2.7, 0, 0], materialOptions: {emissive: 0x64e7df, emissiveIntensity: .65}, motion: 'evidence-lens',
    })
    mesh(group, new THREE.OctahedronGeometry(.85, 1), 0xe9fffd, {
      position: [0, 7.15, 0], materialOptions: {emissive: 0x8ff8f1, emissiveIntensity: 1.5}, motion: 'evidence-core',
    })
  } else if (landmark === 'barricade') {
    for (const [index, x] of [-4.8, -2.8, -1, 1.1, 3, 4.8].entries()) {
      const height = 4.4 + (index % 3) * 1.65
      mesh(group, new THREE.ConeGeometry(1.15, height, 5), index % 2 ? dark : gray, {
        position: [x, height / 2, (index % 2 ? -.5 : .5)], rotation: [0, 0, (index - 2.5) * .07], motion: 'blocker-shard',
      })
    }
    beamBetween(group, new THREE.Vector3(-5.4, 2.1, .8), new THREE.Vector3(5.4, 4.8, -.6), .28, 0xff4f35)
    mesh(group, new THREE.IcosahedronGeometry(.78, 0), 0xff4f35, {
      position: [0, 3.6, .9], materialOptions: {emissive: 0xff2f24, emissiveIntensity: 1.55}, motion: 'blocker-core',
    })
  } else if (landmark === 'bridge') {
    taperedPillar(group, -4.5, 5.1, dark, 1.2)
    taperedPillar(group, 4.5, 5.1, dark, 1.2)
    const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(-5.2, 1.1, 0), new THREE.Vector3(0, 6.8, 0), new THREE.Vector3(5.2, 1.1, 0))
    mesh(group, new THREE.TubeGeometry(curve, 32, .62, 7, false), pale, {motion: 'recovery-bridge'})
    mesh(group, new THREE.TubeGeometry(curve, 32, .11, 5, false), 0x65e2b1, {
      materialOptions: {emissive: 0x65e2b1, emissiveIntensity: 1.1, roughness: .3}, motion: 'recovery-current',
    })
  } else if (landmark === 'monument') {
    steppedBase(group)
    mesh(group, new THREE.CylinderGeometry(.55, 1.65, 10.5, 5), pale, {position: [0, 6.1, 0], rotation: [0, Math.PI / 5, 0]})
    mesh(group, new THREE.TorusGeometry(2.2, .18, 5, 24), AMBER, {
      position: [0, 8.7, 0], rotation: [Math.PI / 2, 0, 0], materialOptions: {emissive: AMBER, emissiveIntensity: .8}, motion: 'milestone-ring',
    })
  } else if (landmark === 'archive') {
    steppedBase(group)
    for (const [index, y] of [2.2, 3.65, 5.1, 6.55].entries()) {
      mesh(group, new THREE.CylinderGeometry(3.65 - index * .42, 4.05 - index * .42, .72, 8), index % 2 ? pale : gray, {position: [0, y, 0]})
    }
    mesh(group, new THREE.DodecahedronGeometry(1.2, 0), 0x72ded0, {
      position: [0, 8.2, 0], materialOptions: {emissive: 0x72ded0, emissiveIntensity: .9}, motion: 'archive-core',
    })
  } else if (landmark === 'blueprint') {
    steppedBase(group)
    const geometry = new THREE.IcosahedronGeometry(4.1, 1)
    const wireframe = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 18), new THREE.LineBasicMaterial({color: 0x64e7df, transparent: true, opacity: .62}))
    wireframe.position.y = 5.1
    wireframe.userData.worldMotion = 'blueprint-wire'
    wireframe.userData.baseY = wireframe.position.y
    group.add(wireframe)
    mesh(group, new THREE.OctahedronGeometry(.9, 0), AMBER, {
      position: [0, 5.1, 0], materialOptions: {emissive: AMBER, emissiveIntensity: 1.2}, motion: 'blueprint-core',
    })
  } else if (landmark === 'gateway') {
    steppedBase(group)
    taperedPillar(group, -5, 10.5, dark, 1.5)
    taperedPillar(group, 5, 10.5, dark, 1.5)
    portalRing(group, 4.7, AMBER, {y: 6, tube: .72, motion: 'play-gateway'})
    portalRing(group, 3.55, 0x5be5dc, {y: 6, tube: .18, motion: 'play-gateway-inner'})
    mesh(group, new THREE.CircleGeometry(3.3, 36), 0x49cfc4, {
      position: [0, 6, .36], materialOptions: {emissive: 0x5be5dc, emissiveIntensity: .65, opacity: .3, roughness: .18}, motion: 'portal-surface',
    })
  } else if (landmark === 'destination') {
    steppedBase(group)
    for (const [index, y] of [1.9, 3.2, 4.5].entries()) {
      const radius = 4.6 - index * 1.05
      mesh(group, new THREE.CylinderGeometry(radius * .82, radius, 1.1, 8), index === 2 ? pale : dark, {position: [0, y, 0]})
    }
    for (const x of [-2.7, 2.7]) taperedPillar(group, x, 7.8, pale, .9)
    mesh(group, new THREE.DodecahedronGeometry(1.45, 1), 0xeaffe9, {
      position: [0, 7.4, 0], materialOptions: {emissive: 0x7ef2db, emissiveIntensity: 1.4, roughness: .12}, motion: 'artifact-core',
    })
    portalRing(group, 3.15, 0x7ef2db, {y: 7.4, tube: .18, motion: 'artifact-ring'})
  } else {
    steppedBase(group)
    portalRing(group, 3.4, 0x5be5dc, {y: 4.2, tube: .52, motion: 'phase-portal'})
  }
  return group
}

export function animateLandmark(group, elapsed, state = false) {
  const active = typeof state === 'boolean' ? state : Boolean(state.active)
  const completed = typeof state === 'object' && Boolean(state.completed)
  const approaching = typeof state === 'object' && Boolean(state.approaching)
  const arrivalProgress = typeof state === 'object' ? THREE.MathUtils.clamp(Number(state.arrivalProgress) || 0, 0, 1) : 0
  const gateOpen = completed || (active && arrivalProgress > .52) || (!active && !approaching)
  group.traverse((object) => {
    const motion = object.userData?.worldMotion
    if (!motion) return
    const baseY = Number(object.userData.baseY || 0)
    const energy = active ? 1 : .38
    if (/core|beacon$/.test(motion)) {
      object.position.y = baseY + Math.sin(elapsed * 1.45 + object.id) * .18
      object.rotation.y = elapsed * .42
    }
    if (motion === 'capability-tool') {
      object.position.y = baseY + Math.sin(elapsed * 2.15) * (active ? .22 : .08)
      object.rotation.y = elapsed * (active ? .72 : .18)
      const activeScale = active ? 1.08 + Math.sin(elapsed * 3.4) * .045 : 1
      object.scale.setScalar(activeScale)
      if (object.material?.emissiveIntensity !== undefined) object.material.emissiveIntensity = active ? 1.7 : .34
    }
    if (motion.startsWith('decision-branch')) {
      const phase = motion.endsWith('left') ? 0 : Math.PI
      object.material.emissiveIntensity = (active ? .72 : .18) + Math.max(0, Math.sin(elapsed * 2.35 + phase)) * (active ? .82 : .18)
    }
    if (motion === 'decision-signal') {
      object.rotation.y = elapsed * (active ? .75 : .18)
      object.scale.setScalar(active ? 1 + Math.sin(elapsed * 2.8 + object.id) * .08 : 1)
    }
    if (motion === 'blocker-shard') {
      object.rotation.y = Math.sin(elapsed * (active ? 5.2 : 1.4) + object.id) * (active ? .045 : .012)
    }
    if (motion === 'recovery-current' && object.material?.emissiveIntensity !== undefined) {
      object.material.emissiveIntensity = active ? 1.45 + Math.sin(elapsed * 3.1) * .35 : .28
    }
    if (/ring|orbit|portal|gateway|lens|arch/.test(motion)) {
      object.rotation.z = elapsed * (active ? .28 : .07)
      if (object.material?.emissiveIntensity !== undefined) object.material.emissiveIntensity = (.26 + Math.sin(elapsed * 1.8 + object.id) * .1) * energy
    }
    if (/seal|bar|blocker/.test(motion) && object.material?.emissiveIntensity !== undefined) {
      object.material.emissiveIntensity = (.62 + Math.max(0, Math.sin(elapsed * 3.2 + object.id)) * 1.05) * energy
    }
    if (motion === 'authority-bar') {
      object.position.y = THREE.MathUtils.lerp(object.position.y, baseY + (gateOpen ? 7.5 : 0), gateOpen ? .065 : .11)
    }
    if (motion === 'authority-seal') {
      const sealScale = gateOpen ? .22 : approaching ? 1.18 + Math.sin(elapsed * 4.2) * .08 : 1
      object.scale.lerp(new THREE.Vector3(sealScale, sealScale, sealScale), .09)
    }
    if (motion === 'portal-surface' && object.material) {
      object.material.opacity = (.12 + Math.sin(elapsed * 1.4) * .035) * energy
    }
  })
}

export function makeCallout(chapter, count, total, onActivate) {
  const root = document.createElement('button')
  root.type = 'button'
  root.className = 'world-callout'
  root.dataset.site = chapter.id
  root.innerHTML = `
    <span class="vantage-glyph"><i></i></span>
    <span class="vantage-summary">
      <b>${escapeHtml(SITE_VERB[chapter.kind] || 'ENTER')}</b>
      <strong>${escapeHtml(chapter.title)}</strong>
      <em>${count ? `${count} EVIDENCE ${count === 1 ? 'BUBBLE' : 'BUBBLES'}` : 'OPEN VANTAGE'}</em>
    </span>
    <span class="callout-body">
      <i>VANTAGE</i><b>${String(chapter.order + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')} · ${escapeHtml(WORLD_ROLE[chapter.kind] || 'Journey stage')} · ${escapeHtml(KIND_LABEL[chapter.kind] || chapter.kind)}</b>
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
    ? `Open request and response details for ${group.count} related interactions ${group.label}`
    : `Open request and response details for interaction ${group.sequences[0]}`)
  trigger.innerHTML = `
    <span>${escapeHtml(group.label)}</span>
    <strong>${escapeHtml(group.system)}${group.count > 1 ? ` · ${group.count}` : ''}</strong>
    <i>${escapeHtml(group.deltaLabel)} · ${escapeHtml(group.posture.toUpperCase())} · ${group.count > 1 ? 'OPEN REQUESTS + RESPONSES' : 'OPEN REQUEST + RESPONSE'}</i>`

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
