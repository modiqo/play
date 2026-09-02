import * as THREE from 'three'
import {RoundedBoxGeometry} from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import {capabilityIdentity} from './world-elements.js'

export const DRIVE_COLORS = Object.freeze({
  sky: 0x071018,
  ground: 0x0a1015,
  road: 0x151b21,
  shoulder: 0x27313a,
  lane: 0xbcc8ce,
  route: 0x20a7ff,
  cyan: 0x36d8e8,
  amber: 0xffb13b,
  red: 0xff4f46,
  green: 0x4ee39a,
})

function material(color, {emissive = 0x000000, emissiveIntensity = 0, roughness = .54, metalness = .08, opacity = 1, map = null, bumpMap = null, bumpScale = 0} = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    emissive,
    emissiveIntensity,
    roughness,
    metalness,
    transparent: opacity < 1,
    opacity,
    map,
    bumpMap,
    bumpScale,
    dithering: true,
  })
}

function mesh(group, geometry, color, options = {}) {
  const object = new THREE.Mesh(geometry, material(color, options.material))
  object.position.set(...(options.position || [0, 0, 0]))
  object.rotation.set(...(options.rotation || [0, 0, 0]))
  object.castShadow = options.castShadow !== false
  object.receiveShadow = options.receiveShadow !== false
  if (options.motion) object.userData.motion = options.motion
  object.userData.basePosition = object.position.clone()
  group.add(object)
  return object
}

function orientToTangent(object, tangent) {
  const forward = new THREE.Vector3(0, 0, -1)
  const target = new THREE.Vector3(tangent.x, 0, tangent.z).normalize()
  object.quaternion.setFromUnitVectors(forward, target)
}

function ribbonGeometry(samples, halfWidth, y = .04) {
  const positions = []
  const normals = []
  const uvs = []
  const indices = []
  samples.forEach((sample, index) => {
    const normalX = -sample.tangent.z
    const normalZ = sample.tangent.x
    positions.push(
      sample.x + normalX * halfWidth, y, sample.z + normalZ * halfWidth,
      sample.x - normalX * halfWidth, y, sample.z - normalZ * halfWidth,
    )
    normals.push(0, 1, 0, 0, 1, 0)
    const v = index / Math.max(1, samples.length - 1)
    uvs.push(0, v, 1, v)
    if (index < samples.length - 1) {
      const base = index * 2
      indices.push(base, base + 1, base + 2, base + 1, base + 3, base + 2)
    }
  })
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3))
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2))
  geometry.setIndex(indices)
  geometry.computeBoundingSphere()
  return geometry
}

function ribbonWallGeometry(samples, offset, topY, bottomY) {
  const positions = []
  const indices = []
  samples.forEach((sample, index) => {
    const normalX = -sample.tangent.z
    const normalZ = sample.tangent.x
    positions.push(
      sample.x + normalX * offset, topY, sample.z + normalZ * offset,
      sample.x + normalX * offset, bottomY, sample.z + normalZ * offset,
    )
    if (index < samples.length - 1) {
      const base = index * 2
      indices.push(base, base + 1, base + 2, base + 1, base + 3, base + 2)
    }
  })
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  geometry.computeBoundingSphere()
  return geometry
}

function laneMarkings(group, plan) {
  const geometry = new THREE.BoxGeometry(.08, .025, 1.15)
  const laneMaterial = material(DRIVE_COLORS.lane, {emissive: DRIVE_COLORS.lane, emissiveIntensity: .25, roughness: .35})
  const edgeMaterial = material(0x687883, {emissive: 0x687883, emissiveIntensity: .12, roughness: .42})
  const routeMaterial = material(DRIVE_COLORS.route, {emissive: DRIVE_COLORS.route, emissiveIntensity: 3.1, roughness: .22})
  plan.samples.forEach((sample, index) => {
    if (index % 7 !== 0) return
    const normal = new THREE.Vector3(-sample.tangent.z, 0, sample.tangent.x)
    for (const offset of [-plan.roadHalfWidth, -plan.roadHalfWidth / 3, plan.roadHalfWidth / 3, plan.roadHalfWidth]) {
      const mark = new THREE.Mesh(geometry, Math.abs(offset) === plan.roadHalfWidth ? edgeMaterial : laneMaterial)
      mark.position.set(sample.x, .14, sample.z).addScaledVector(normal, offset)
      orientToTangent(mark, sample.tangent)
      mark.receiveShadow = true
      group.add(mark)
    }
    const route = new THREE.Mesh(new THREE.BoxGeometry(.18, .035, 1.35), routeMaterial)
    route.position.set(sample.x, .15, sample.z)
    orientToTangent(route, sample.tangent)
    route.userData.motion = 'route-light'
    group.add(route)
  })
}

function asphaltTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = 384
  canvas.height = 384
  const context = canvas.getContext('2d')
  context.fillStyle = '#59636a'
  context.fillRect(0, 0, canvas.width, canvas.height)
  let seed = 7361
  const random = () => {
    seed = Math.imul(seed, 1664525) + 1013904223 >>> 0
    return seed / 0xffffffff
  }
  for (let index = 0; index < 7200; index += 1) {
    const shade = 58 + Math.floor(random() * 48)
    context.fillStyle = `rgba(${shade},${shade + 3},${shade + 5},${.08 + random() * .18})`
    const size = .35 + random() * 1.25
    context.fillRect(random() * canvas.width, random() * canvas.height, size, size)
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(5, 42)
  texture.anisotropy = 8
  return texture
}

function citySilhouettes(group, plan) {
  const buildingMaterial = material(0x26343d, {
    emissive: 0x17262f,
    emissiveIntensity: .12,
    roughness: .84,
    metalness: .05,
    opacity: .48,
  })
  const roofMaterial = material(0x33434c, {
    emissive: 0x1c2d36,
    emissiveIntensity: .1,
    roughness: .78,
    opacity: .42,
  })
  let state = (plan.seed ^ 0x9e3779b9) >>> 0
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 0xffffffff
  }
  for (let index = 8; index < plan.samples.length - 5; index += 11) {
    const sample = plan.samples[index]
    const normal = new THREE.Vector3(-sample.tangent.z, 0, sample.tangent.x)
    for (const side of [-1, 1]) {
      if (random() < .2) continue
      const width = 1.5 + random() * 2.5
      const depth = 1.5 + random() * 2.9
      const height = 2.2 + random() * 6.8
      const distance = plan.roadHalfWidth + 4.1 + random() * 4.6
      const building = new THREE.Mesh(new RoundedBoxGeometry(width, height, depth, 3, .12), buildingMaterial)
      building.position.set(sample.x, height / 2 - .02, sample.z).addScaledVector(normal, side * distance)
      orientToTangent(building, sample.tangent)
      building.castShadow = true
      building.receiveShadow = true
      group.add(building)
      if (random() > .48) {
        const roof = new THREE.Mesh(new RoundedBoxGeometry(width * .28, .24, depth * .28, 2, .05), roofMaterial)
        roof.position.copy(building.position)
        roof.position.y = height + .1
        roof.quaternion.copy(building.quaternion)
        group.add(roof)
      }
    }
  }
}

function routeCurve(plan, offset = 0) {
  const points = plan.samples.map((sample) => {
    const normalX = -sample.tangent.z
    const normalZ = sample.tangent.x
    return new THREE.Vector3(sample.x + normalX * offset, .16, sample.z + normalZ * offset)
  })
  return new THREE.CatmullRomCurve3(points)
}

export function createDriveEnvironment(plan) {
  const group = new THREE.Group()
  group.name = 'drive-world'
  const ground = mesh(group, new THREE.PlaneGeometry(520, 520), DRIVE_COLORS.ground, {
    rotation: [-Math.PI / 2, 0, 0], position: [0, -.08, -120], castShadow: false,
    material: {roughness: .96, metalness: .02},
  })
  ground.receiveShadow = true
  const texture = asphaltTexture()
  const shoulder = new THREE.Mesh(
    ribbonGeometry(plan.samples, plan.roadHalfWidth + .78, .035),
    material(0x253039, {roughness: .9, metalness: .03}),
  )
  shoulder.receiveShadow = true
  group.add(shoulder)
  const road = new THREE.Mesh(
    ribbonGeometry(plan.samples, plan.roadHalfWidth, .105),
    material(0xb9c1c5, {roughness: .91, metalness: .025, map: texture, bumpMap: texture, bumpScale: .026}),
  )
  road.receiveShadow = true
  group.add(road)
  for (const side of [-1, 1]) {
    const roadFace = new THREE.Mesh(
      ribbonWallGeometry(plan.samples, side * plan.roadHalfWidth, .105, .035),
      material(0x35434b, {roughness: .76, metalness: .08}),
    )
    roadFace.castShadow = true
    roadFace.receiveShadow = true
    group.add(roadFace)
    const wall = new THREE.Mesh(
      ribbonWallGeometry(plan.samples, side * (plan.roadHalfWidth + .78), .035, -.34),
      material(0x101a20, {roughness: .82, metalness: .08}),
    )
    wall.castShadow = true
    wall.receiveShadow = true
    group.add(wall)
    const curb = mesh(group, new THREE.TubeGeometry(routeCurve(plan, side * plan.roadHalfWidth), plan.samples.length, .075, 6, false), 0xa8b7be, {
      castShadow: false,
      material: {emissive: 0x5c747f, emissiveIntensity: .18, roughness: .38, metalness: .14},
    })
    curb.userData.roadEdge = true
  }
  laneMarkings(group, plan)
  mesh(group, new THREE.TubeGeometry(routeCurve(plan), plan.samples.length, .065, 6, false), DRIVE_COLORS.route, {
    castShadow: false, motion: 'route-light', material: {emissive: DRIVE_COLORS.route, emissiveIntensity: 2.4, roughness: .24},
  })
  const postGeometry = new THREE.CylinderGeometry(.045, .055, .42, 8)
  const postMaterial = material(0x8aa0aa, {emissive: 0x4b6875, emissiveIntensity: .32, roughness: .36})
  plan.samples.forEach((sample, index) => {
    if (index % 18 !== 0) return
    const normal = new THREE.Vector3(-sample.tangent.z, 0, sample.tangent.x)
    for (const side of [-1, 1]) {
      const post = new THREE.Mesh(postGeometry, postMaterial)
      post.position.set(sample.x, .2, sample.z).addScaledVector(normal, side * (plan.roadHalfWidth + .78))
      post.castShadow = true
      group.add(post)
    }
  })
  citySilhouettes(group, plan)
  return group
}

function arch(group, color, motion = '') {
  for (let index = 0; index < 3; index += 1) {
    mesh(group, new THREE.TorusGeometry(4.65 - index * .08, .055, 8, 48, Math.PI), color, {
      position: [0, .08, -.7 - index * .48], motion,
      material: {emissive: color, emissiveIntensity: 1.25 - index * .2, roughness: .24, opacity: .92 - index * .16},
    })
  }
}

function roadChevron(group, z, color, side = 0) {
  const chevron = mesh(group, new THREE.ConeGeometry(.48, 1.4, 3), color, {
    position: [side, .12, z], rotation: [-Math.PI / 2, 0, 0], castShadow: false,
    material: {emissive: color, emissiveIntensity: 1.5, roughness: .25},
    motion: 'chevron',
  })
  chevron.scale.x = .65
}

function curveSamples(curve, segments = 30) {
  return Array.from({length: segments + 1}, (_, index) => {
    const amount = index / segments
    const point = curve.getPoint(amount)
    const tangent = curve.getTangent(amount).normalize()
    return {x: point.x, y: point.y, z: point.z, tangent}
  })
}

function curveRoad(group, curve, {accent, motion, halfWidth = 1.65} = {}) {
  const samples = curveSamples(curve)
  const shoulder = mesh(group, ribbonGeometry(samples, halfWidth + .32, .045), DRIVE_COLORS.shoulder, {
    castShadow: false,
    material: {roughness: .9, metalness: .02},
  })
  shoulder.userData.motion = motion
  const road = mesh(group, ribbonGeometry(samples, halfWidth, .065), DRIVE_COLORS.road, {
    castShadow: false,
    material: {roughness: .82, metalness: .04},
  })
  road.userData.motion = motion
  for (const side of [-1, 1]) {
    const edgePoints = samples.map((sample) => {
      const normalX = -sample.tangent.z
      const normalZ = sample.tangent.x
      return new THREE.Vector3(sample.x + normalX * halfWidth * side, .1, sample.z + normalZ * halfWidth * side)
    })
    mesh(group, new THREE.TubeGeometry(new THREE.CatmullRomCurve3(edgePoints), 30, .035, 5, false), 0xa9bac2, {
      castShadow: false,
      material: {emissive: 0x6f8792, emissiveIntensity: .28, roughness: .38},
    })
  }
  mesh(group, new THREE.TubeGeometry(curve, 30, .09, 6, false), accent, {
    castShadow: false,
    material: {emissive: accent, emissiveIntensity: 2.4, roughness: .24},
    motion: 'route-light',
  })
}

function capabilityStation(group, chapter, shoulder) {
  const identity = capabilityIdentity(chapter)
  for (let index = -3; index <= 3; index += 1) {
    mesh(group, new THREE.BoxGeometry(7.4, .025, .055), identity.color, {
      position: [0, .115, index * .72], castShadow: false, motion: 'capability-lane',
      material: {emissive: identity.color, emissiveIntensity: .75 + (3 - Math.abs(index)) * .16, roughness: .22, opacity: .48},
    })
  }
  const x = shoulder * 5.75
  mesh(group, new RoundedBoxGeometry(.38, .72, .38, 4, .08), 0x8397a0, {
    position: [x, .38, 0], motion: 'capability-lane', material: {metalness: .38, roughness: .28},
  })
  const signal = mesh(group, new THREE.SphereGeometry(.085, 16, 12), identity.color, {
    position: [x, .72, 0], motion: 'capability-tool', castShadow: false,
    material: {emissive: identity.color, emissiveIntensity: 2.4, roughness: .14},
  })
  signal.userData.basePosition = signal.position.clone()
  const light = new THREE.PointLight(identity.color, 2.5, 10, 2)
  light.position.set(x, 1, 0)
  group.add(light)
}

function authorityGate(group) {
  const frame = 0x627681
  mesh(group, new RoundedBoxGeometry(10.8, .24, .72, 4, .08), frame, {
    position: [0, 3.25, -.7], motion: 'authority-frame',
    material: {metalness: .42, roughness: .35},
  })
  for (const x of [-5.1, 5.1]) mesh(group, new RoundedBoxGeometry(.26, 3.35, .44, 4, .07), frame, {
    position: [x, 1.68, -.7], motion: 'authority-frame', material: {metalness: .42, roughness: .35},
  })
  for (const x of [-3.45, 0, 3.45]) {
    mesh(group, new RoundedBoxGeometry(.78, 1.55, 1.08, 5, .12), 0x31414a, {
      position: [x - 1.52, .78, -.1], motion: 'toll-booth', material: {metalness: .34, roughness: .38},
    })
    mesh(group, new THREE.BoxGeometry(.72, .68, .05), 0x17242a, {
      position: [x - 1.52, 1.02, .46], castShadow: false, material: {emissive: 0x4b6976, emissiveIntensity: .48, roughness: .18},
    })
    const signal = mesh(group, new THREE.CylinderGeometry(.22, .22, .12, 18), DRIVE_COLORS.red, {
      position: [x, 2.96, -.02], rotation: [Math.PI / 2, 0, 0], motion: 'toll-signal', castShadow: false,
      material: {emissive: DRIVE_COLORS.red, emissiveIntensity: 2.4, roughness: .18},
    })
    signal.userData.closedColor = new THREE.Color(DRIVE_COLORS.red)
    signal.userData.openColor = new THREE.Color(DRIVE_COLORS.green)
    const pivot = new THREE.Group()
    pivot.position.set(x - 1.5, .94, .45)
    pivot.userData.motion = 'toll-arm'
    const arm = mesh(pivot, new THREE.BoxGeometry(2.75, .14, .14), 0xe8edf0, {
      position: [1.38, 0, 0], castShadow: false,
      material: {emissive: DRIVE_COLORS.red, emissiveIntensity: .72, roughness: .32},
    })
    arm.userData.tollArm = true
    group.add(pivot)
  }
}

function decisionFork(group) {
  for (const side of [-1, 1]) {
    const curve = new THREE.QuadraticBezierCurve3(
      new THREE.Vector3(side * .72, .11, 5.2),
      new THREE.Vector3(side * 2.4, .11, -1.5),
      new THREE.Vector3(side * 5.7, .11, -10.5),
    )
    curveRoad(group, curve, {
      accent: side < 0 ? DRIVE_COLORS.cyan : DRIVE_COLORS.amber,
      motion: 'decision-lane',
      halfWidth: 1.7,
    })
  }
  roadChevron(group, -3.4, DRIVE_COLORS.cyan, -2.25)
  roadChevron(group, -3.4, DRIVE_COLORS.amber, 2.25)
}

function blocker(group, _chapter, site) {
  const side = site?.shoulder || 1
  const curve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(side * .9, .11, 5.5),
    new THREE.Vector3(side * 4.5, .11, -1),
    new THREE.Vector3(side * 8.3, .11, -9.5),
  )
  curveRoad(group, curve, {accent: DRIVE_COLORS.red, motion: 'error-off-ramp', halfWidth: 1.55})
  const stop = mesh(group, new THREE.BoxGeometry(3.2, .42, .34), DRIVE_COLORS.red, {
    position: [side * 8.3, .72, -9.15], rotation: [0, side * -.35, 0], motion: 'blocker',
    material: {emissive: DRIVE_COLORS.red, emissiveIntensity: 1.45, roughness: .34},
  })
  stop.userData.basePosition = stop.position.clone()
}

function recoveryMerge(group, _chapter, site) {
  const side = site?.shoulder || 1
  const curve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(side * 8.2, .11, 7.5),
    new THREE.Vector3(side * 4.1, .11, .5),
    new THREE.Vector3(side * .65, .11, -6.5),
  )
  curveRoad(group, curve, {accent: DRIVE_COLORS.green, motion: 'recovery-on-ramp', halfWidth: 1.55})
  roadChevron(group, -4.7, DRIVE_COLORS.green, side * 1.45)
}

function evidenceScanner(group) {
  arch(group, DRIVE_COLORS.cyan, 'scanner-frame')
  mesh(group, new THREE.BoxGeometry(9.2, .08, .12), DRIVE_COLORS.cyan, {
    position: [0, 2.4, 0], motion: 'scanner-beam', castShadow: false,
    material: {emissive: DRIVE_COLORS.cyan, emissiveIntensity: 2.6, opacity: .72, roughness: .2},
  })
}

function destination(group, color = DRIVE_COLORS.green) {
  for (let index = -4; index <= 4; index += 1) {
    mesh(group, new THREE.BoxGeometry(1.05, .028, .2), index % 2 ? color : 0xe1eaed, {
      position: [index * 1.12, .115, 0], castShadow: false, motion: 'destination',
      material: {emissive: index % 2 ? color : 0xa5b8c0, emissiveIntensity: .72, roughness: .3},
    })
  }
  for (const z of [3.1, 1.55, -1.55, -3.1]) roadChevron(group, z, color)
}

function roadTarget(group, color, motion = 'waypoint') {
  for (const radius of [1.15, 1.72]) {
    mesh(group, new THREE.TorusGeometry(radius, .045, 7, 42), color, {
      position: [0, .105, 0], rotation: [-Math.PI / 2, 0, 0], castShadow: false, motion,
      material: {emissive: color, emissiveIntensity: radius < 1.5 ? 1.6 : .78, roughness: .22, opacity: radius < 1.5 ? .9 : .58},
    })
  }
  for (const z of [3.2, 1.7]) roadChevron(group, z, color)
}

export function createDriveFixture(chapter, site) {
  const group = new THREE.Group()
  group.name = `drive-site:${chapter.id}`
  group.position.set(site.x, site.y, site.z)
  const ahead = chapter.kind === 'decision' ? decisionFork
    : chapter.kind === 'capability' ? null
      : chapter.kind === 'authority' ? authorityGate
        : chapter.kind === 'blocker' ? blocker
          : chapter.kind === 'recovery' ? recoveryMerge
            : chapter.kind === 'evidence' ? evidenceScanner
              : null
  if (ahead) ahead(group, chapter, site)
  else if (chapter.kind === 'capability') capabilityStation(group, chapter, site.shoulder)
  else if (chapter.kind === 'phase') arch(group, DRIVE_COLORS.cyan, 'phase-gate')
  else if (chapter.kind === 'artifact' || chapter.kind === 'play') destination(group, DRIVE_COLORS.green)
  else if (chapter.kind === 'intent') roadTarget(group, DRIVE_COLORS.route, 'intent-target')
  else if (chapter.kind === 'effect') {
    for (const z of [-3.3, -1.65, 0, 1.65, 3.3]) roadChevron(group, z, DRIVE_COLORS.amber)
  } else if (chapter.kind === 'milestone') roadTarget(group, DRIVE_COLORS.amber, 'milestone')
  else if (chapter.kind === 'learning' || chapter.kind === 'play_candidate') capabilityStation(group, chapter, site.shoulder)
  else roadTarget(group, 0x7a8d96, 'generic-site')
  const materials = []
  group.traverse((object) => {
    if (object.isMesh) materials.push({material: object.material, opacity: object.material.opacity, emissiveIntensity: object.material.emissiveIntensity || 0})
  })
  group.userData = {materials, kind: chapter.kind}
  return group
}

const PYLON_TONES = {read: 0x5ce1ff, write: 0xffb84d, hazard: 0xff6054, error: 0xff6054}

function pylonTone(record) {
  const status = String(record.status || '').toLowerCase()
  const profile = record.effect_profile || {}
  const posture = String(profile.posture || record.effect || '').toLowerCase()
  if (status === 'failed' || status === 'error' || status === 'errored') return 'error'
  if (profile.destructive === true || posture === 'destructive') return 'hazard'
  if (posture === 'write' || posture === 'mutate') return 'write'
  return 'read'
}

/**
 * Exchange pylons: a thin lit post with a floating ring, one per recorded
 * exchange, in the same tone language as the heads-up display. The reticle
 * locks onto the ring.
 */
export function createDriveEvents(records = [], site) {
  const group = new THREE.Group()
  group.name = `drive-events:${site.id}`
  group.position.set(site.x, site.y, site.z)
  const markers = []
  records.forEach((record, index) => {
    const lane = index % 3 - 1
    const row = Math.floor(index / 3)
    const color = PYLON_TONES[pylonTone(record)]
    const marker = new THREE.Group()
    marker.position.set(lane * 2.45, 0, 5.4 + row * 1.9)
    marker.userData.motion = 'event-marker'
    const base = mesh(marker, new THREE.CylinderGeometry(.34, .4, .05, 40), 0x0b1216, {
      position: [0, .025, 0], castShadow: false,
      material: {roughness: .6, metalness: .3, emissive: color, emissiveIntensity: .05},
    })
    base.userData.baseEventEmissive = .05
    const halo = mesh(marker, new THREE.RingGeometry(.36, .44, 48), color, {
      position: [0, .06, 0], rotation: [-Math.PI / 2, 0, 0], castShadow: false,
      material: {emissive: color, emissiveIntensity: .9, roughness: .4, opacity: .85},
    })
    halo.userData.baseEventEmissive = .9
    const post = mesh(marker, new THREE.CylinderGeometry(.022, .03, 1.5, 12), color, {
      position: [0, .8, 0], castShadow: false,
      material: {emissive: color, emissiveIntensity: 1.4, roughness: .3, metalness: .1},
    })
    post.userData.baseEventEmissive = 1.4
    const ring = mesh(marker, new THREE.TorusGeometry(.26, .018, 10, 48), color, {
      position: [0, 1.62, 0], rotation: [Math.PI / 2, 0, 0], castShadow: false, motion: 'event-ring',
      material: {emissive: color, emissiveIntensity: 1.6, roughness: .3},
    })
    ring.userData.baseEventEmissive = 1.6
    const core = mesh(marker, new THREE.SphereGeometry(.06, 14, 12), 0xffffff, {
      position: [0, 1.62, 0], castShadow: false,
      material: {emissive: color, emissiveIntensity: 2.4, roughness: .2},
    })
    core.userData.baseEventEmissive = 2.4
    marker.userData.sequence = record.sequence
    marker.userData.ring = ring
    group.add(marker)
    markers.push(marker)
  })
  group.userData.markers = markers
  return group
}

export function updateDriveFixture(group, {active = false, approaching = false, completed = false, elapsed = 0} = {}) {
  const energy = active ? 1 : approaching ? .58 : completed ? .16 : .07
  group.userData.materials?.forEach((state) => {
    state.material.opacity = state.opacity * (active ? 1 : approaching ? .78 : completed ? .32 : .18)
    state.material.transparent = state.material.opacity < .999
    state.material.emissiveIntensity = state.emissiveIntensity * energy
  })
  group.traverse((object) => {
    const motion = object.userData.motion
    if (motion === 'toll-arm') object.rotation.z = THREE.MathUtils.lerp(object.rotation.z, completed ? -Math.PI * .47 : 0, .1)
    if (motion === 'toll-signal') {
      const target = completed ? object.userData.openColor : object.userData.closedColor
      object.material.color.lerp(target, .1)
      object.material.emissive.lerp(target, .1)
    }
    if (motion === 'scanner-beam') object.position.y = 1.2 + (Math.sin(elapsed * 1.8) * .5 + .5) * 2.4
    if (motion === 'chevron' || motion === 'route-light') object.material.emissiveIntensity *= .82 + Math.sin(elapsed * 3.2 + object.id) * .18
    if (motion === 'capability-tool') object.position.y = object.userData.basePosition.y + Math.sin(elapsed * 1.7) * .12
    if (motion === 'blocker') object.position.y = object.userData.basePosition.y + Math.sin(elapsed * 2.2 + object.id) * .035
  })
}

export function animateDriveEnvironment(group, elapsed) {
  group.traverse((object) => {
    if (object.userData.motion === 'route-light' && object.material) {
      object.material.emissiveIntensity = 2.5 + Math.sin(elapsed * 3.1 + object.id * .1) * .6
    }
  })
}
