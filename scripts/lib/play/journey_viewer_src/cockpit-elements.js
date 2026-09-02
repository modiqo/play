/**
 * First-person cockpit: steering wheel, capability dial, dash, and visor glass.
 *
 * Everything here is procedural so it ships inside the bundle under the
 * viewer's self-only content policy. The group is a child of the camera, so
 * the driver's hands stay fixed while the world moves. Kinematics come from
 * `steering-model.mjs`; this module only builds and paints geometry.
 */

import * as THREE from 'three'
import {RoomEnvironment} from 'three/examples/jsm/environments/RoomEnvironment.js'
import {DIAL_DETENTS} from './steering-model.mjs'

const DEG = Math.PI / 180
export const COCKPIT_ACCENT = 0x3fc3ff
const LEATHER = 0x151b20
const CHARCOAL = 0x0b1014
const ALUMINIUM = 0xb7c3c9
const GUNMETAL = 0x3a454c

function canvasTexture(width, height, paint) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  paint(context, width, height)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.anisotropy = 4
  return texture
}

function grainTexture(size = 256, strength = 26) {
  const texture = canvasTexture(size, size, (context, width, height) => {
    const image = context.createImageData(width, height)
    for (let index = 0; index < image.data.length; index += 4) {
      const value = 128 + (Math.random() - .5) * strength
      image.data[index] = image.data[index + 1] = image.data[index + 2] = value
      image.data[index + 3] = 255
    }
    context.putImageData(image, 0, 0)
  })
  texture.colorSpace = THREE.NoColorSpace
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(6, 2)
  return texture
}

function knurlTexture(count = 72) {
  const texture = canvasTexture(1024, 64, (context, width, height) => {
    const step = width / count
    for (let index = 0; index < count; index += 1) {
      const gradient = context.createLinearGradient(index * step, 0, (index + 1) * step, 0)
      gradient.addColorStop(0, '#2c2c2c')
      gradient.addColorStop(.5, '#ffffff')
      gradient.addColorStop(1, '#2c2c2c')
      context.fillStyle = gradient
      context.fillRect(index * step, 0, step, height)
    }
  })
  texture.colorSpace = THREE.NoColorSpace
  texture.wrapS = THREE.RepeatWrapping
  return texture
}

function perforationTexture(size = 256, pitch = 14) {
  const texture = canvasTexture(size, size, (context, width, height) => {
    context.fillStyle = '#808080'
    context.fillRect(0, 0, width, height)
    for (let y = pitch / 2; y < height; y += pitch) {
      for (let x = pitch / 2 + ((y / pitch) % 2) * (pitch / 2); x < width; x += pitch) {
        const dot = context.createRadialGradient(x, y, 0, x, y, pitch * .28)
        dot.addColorStop(0, '#101010')
        dot.addColorStop(.7, '#303030')
        dot.addColorStop(1, '#808080')
        context.fillStyle = dot
        context.beginPath()
        context.arc(x, y, pitch * .28, 0, Math.PI * 2)
        context.fill()
      }
    }
  })
  texture.colorSpace = THREE.NoColorSpace
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(10, 2)
  return texture
}

function stitchTexture(count = 96) {
  const texture = canvasTexture(1024, 16, (context, width, height) => {
    context.clearRect(0, 0, width, height)
    const step = width / count
    context.fillStyle = '#d9dee2'
    for (let index = 0; index < count; index += 1) {
      context.fillRect(index * step + step * .18, 5, step * .5, 6)
    }
  })
  texture.wrapS = THREE.RepeatWrapping
  return texture
}

function carbonTexture(size = 256, cell = 16) {
  const texture = canvasTexture(size, size, (context, width, height) => {
    for (let y = 0; y < height; y += cell) {
      for (let x = 0; x < width; x += cell) {
        const across = ((x + y) / cell) % 2 === 0
        const gradient = across
          ? context.createLinearGradient(x, y, x + cell, y)
          : context.createLinearGradient(x, y, x, y + cell)
        gradient.addColorStop(0, '#1a1f23')
        gradient.addColorStop(.5, '#3a434a')
        gradient.addColorStop(1, '#161a1e')
        context.fillStyle = gradient
        context.fillRect(x, y, cell, cell)
      }
    }
  })
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping
  texture.repeat.set(3, 1)
  return texture
}

function dialLabelTexture(letter, word, active) {
  const texture = canvasTexture(512, 208, (context, width, height) => {
    context.clearRect(0, 0, width, height)
    // Engraved plate: a near-black inset with a bright edge so the label
    // reads against the dash from the driver's seat.
    context.fillStyle = active ? 'rgba(6,30,40,.96)' : 'rgba(3,8,12,.96)'
    context.beginPath()
    context.roundRect(10, 10, width - 20, height - 20, 16)
    context.fill()
    context.lineWidth = 5
    context.strokeStyle = active ? '#5ce1ff' : 'rgba(200,222,232,.7)'
    context.stroke()
    context.textAlign = 'center'
    context.shadowColor = active ? 'rgba(92,225,255,1)' : 'rgba(255,255,255,.45)'
    context.shadowBlur = active ? 26 : 8
    context.fillStyle = active ? '#c9f6ff' : '#ffffff'
    context.font = '700 104px "Departure Mono", "Berkeley Mono", Menlo, monospace'
    context.fillText(letter, width / 2, 116)
    context.shadowBlur = 0
    context.fillStyle = active ? '#ffffff' : '#e3eef3'
    context.font = '700 38px "Departure Mono", "Berkeley Mono", Menlo, monospace'
    context.fillText(word, width / 2, 176)
  })
  texture.anisotropy = 8
  return texture
}

function badgeTexture(title, subtitle, accent = '#3fc3ff') {
  return canvasTexture(256, 256, (context, width, height) => {
    context.fillStyle = '#0d1418'
    context.fillRect(0, 0, width, height)
    const ring = context.createRadialGradient(width / 2, height / 2, 40, width / 2, height / 2, 128)
    ring.addColorStop(0, 'rgba(255,255,255,.05)')
    ring.addColorStop(1, 'rgba(0,0,0,.55)')
    context.fillStyle = ring
    context.fillRect(0, 0, width, height)
    context.strokeStyle = 'rgba(190,210,220,.28)'
    context.lineWidth = 3
    context.beginPath()
    context.arc(width / 2, height / 2, 112, 0, Math.PI * 2)
    context.stroke()
    context.textAlign = 'center'
    context.fillStyle = '#e3ecf0'
    context.font = '600 46px "Departure Mono", "Berkeley Mono", Menlo, monospace'
    context.fillText(title, width / 2, height / 2 + 6)
    context.fillStyle = accent
    context.font = '500 20px "Departure Mono", "Berkeley Mono", Menlo, monospace'
    context.fillText(subtitle, width / 2, height / 2 + 44)
  })
}

function readoutTexture(label, value, accent = '#3fc3ff') {
  return canvasTexture(512, 160, (context, width, height) => {
    context.fillStyle = '#070b0e'
    context.fillRect(0, 0, width, height)
    const glow = context.createLinearGradient(0, 0, 0, height)
    glow.addColorStop(0, 'rgba(63,195,255,.08)')
    glow.addColorStop(1, 'rgba(0,0,0,0)')
    context.fillStyle = glow
    context.fillRect(0, 0, width, height)
    context.strokeStyle = 'rgba(120,150,165,.35)'
    context.lineWidth = 2
    context.strokeRect(6, 6, width - 12, height - 12)
    context.textAlign = 'center'
    context.fillStyle = '#7f99a5'
    context.font = '600 22px "Departure Mono", "Berkeley Mono", Menlo, monospace'
    context.fillText(label, width / 2, 50)
    context.fillStyle = accent
    context.font = '700 56px "Departure Mono", "Berkeley Mono", Menlo, monospace'
    context.fillText(value, width / 2, 118)
  })
}

function physical(options) {
  return new THREE.MeshPhysicalMaterial(options)
}

function add(parent, geometry, material, {position = [0, 0, 0], rotation = [0, 0, 0], scale = null, name = ''} = {}) {
  const item = new THREE.Mesh(geometry, material)
  item.position.set(...position)
  item.rotation.set(...rotation)
  if (scale) item.scale.set(...scale)
  item.castShadow = false
  item.receiveShadow = false
  item.name = name
  parent.add(item)
  return item
}

function buildWheel(materials) {
  const wheel = new THREE.Group()
  wheel.name = 'cockpit-wheel'
  const rimRadius = .175
  const tube = .02
  // Smooth leather rim, flattened toward the driver like a sports wheel.
  const rim = add(wheel, new THREE.TorusGeometry(rimRadius, tube, 40, 180), materials.leather, {name: 'rim'})
  rim.scale.z = .8
  // Perforated leather on the two hand positions.
  for (const [start, length] of [[20 * DEG, 50 * DEG], [110 * DEG, 50 * DEG]]) {
    const grip = add(wheel, new THREE.TorusGeometry(rimRadius, tube + .0015, 40, 60, length), materials.perforated, {
      rotation: [0, 0, start], name: 'grip',
    })
    grip.scale.z = .8
  }
  // Contrast stitching runs along the inside of the rim.
  const stitch = add(wheel, new THREE.TorusGeometry(rimRadius - tube * .55, .0028, 8, 180), materials.stitch, {position: [0, 0, tube * .55], name: 'stitching'})
  stitch.renderOrder = 2
  // A polished trim ring where the rim meets the spokes.
  add(wheel, new THREE.TorusGeometry(rimRadius - tube - .006, .0035, 12, 180), materials.chrome, {name: 'trim'})
  // Three-spoke layout with a carbon face and a chrome edge.
  const arms = [
    {angle: 12, length: rimRadius - .028, width: .034},
    {angle: 168, length: rimRadius - .028, width: .034},
    {angle: 270, length: rimRadius - .036, width: .026},
  ]
  for (const arm of arms) {
    const radians = arm.angle * DEG
    const center = [Math.cos(radians) * (arm.length / 2 + .018), Math.sin(radians) * (arm.length / 2 + .018), 0]
    add(wheel, new THREE.BoxGeometry(arm.length, arm.width, .013), materials.gunmetal, {position: center, rotation: [0, 0, radians], name: `spoke-${arm.angle}`})
    add(wheel, new THREE.PlaneGeometry(arm.length - .012, arm.width - .01), materials.carbon, {position: [center[0], center[1], .0068], rotation: [0, 0, radians], name: `spoke-face-${arm.angle}`})
    add(wheel, new THREE.BoxGeometry(arm.length - .008, .0025, .014), materials.chrome, {position: [center[0], center[1], .0005], rotation: [0, 0, radians], name: `spoke-edge-${arm.angle}`})
  }
  // Hub: machined cap, chrome bezel, illuminated ring, badge.
  add(wheel, new THREE.CylinderGeometry(.05, .056, .034, 72), materials.gunmetal, {rotation: [Math.PI / 2, 0, 0], name: 'hub'})
  add(wheel, new THREE.TorusGeometry(.052, .0025, 12, 120), materials.chrome, {position: [0, 0, .017], name: 'hub-bezel'})
  add(wheel, new THREE.TorusGeometry(.044, .0012, 8, 120), materials.accentSoft, {position: [0, 0, .0182], name: 'hub-light'})
  add(wheel, new THREE.CircleGeometry(.041, 72), materials.badge, {position: [0, 0, .0175], name: 'badge'})
  // Top-dead-centre marker.
  add(wheel, new THREE.BoxGeometry(.022, .005, .008), materials.accentSoft, {position: [0, rimRadius, tube * .9], name: 'tdc'})
  return wheel
}

const DIAL_LABELS = {call: ['A', 'ADAPTER'], drive: ['B', 'BROWSER'], shell: ['S', 'SHELL']}

function buildDial(materials) {
  const dial = new THREE.Group()
  dial.name = 'cockpit-dial'
  add(dial, new THREE.CylinderGeometry(.084, .09, .012, 64), materials.gunmetal, {position: [0, -.012, 0], name: 'base'})
  add(dial, new THREE.TorusGeometry(.082, .004, 10, 96), materials.chrome, {rotation: [Math.PI / 2, 0, 0], position: [0, -.004, 0], name: 'bezel'})
  add(dial, new THREE.TorusGeometry(.086, .0012, 8, 96), materials.accentSoft, {rotation: [Math.PI / 2, 0, 0], position: [0, -.002, 0], name: 'bezel-light'})
  const knob = new THREE.Group()
  knob.name = 'knob'
  add(knob, new THREE.CylinderGeometry(.064, .066, .034, 96, 1, false), materials.knurl, {position: [0, .017, 0], name: 'knurl'})
  add(knob, new THREE.CylinderGeometry(.052, .054, .012, 64), materials.brushed, {position: [0, .04, 0], name: 'cap'})
  add(knob, new THREE.BoxGeometry(.008, .006, .03), materials.accent, {position: [0, .047, -.036], name: 'needle'})
  dial.add(knob)
  const lamps = {}
  const labels = {}
  for (const [gear, angle] of Object.entries(DIAL_DETENTS)) {
    const radians = angle * DEG
    const lamp = add(dial, new THREE.SphereGeometry(.0055, 12, 10), materials.lamp.clone(), {
      position: [Math.sin(radians) * .096, .002, -Math.cos(radians) * .096],
      name: `lamp-${gear}`,
    })
    lamps[gear] = lamp
    // Engraved label on the dash, fanned around the detent it names.
    const [letter, word] = DIAL_LABELS[gear]
    const material = new THREE.MeshBasicMaterial({map: dialLabelTexture(letter, word, false), transparent: true, toneMapped: false, depthWrite: false})
    const fan = radians * 1.7
    const label = add(dial, new THREE.PlaneGeometry(.17, .069), material, {
      position: [Math.sin(fan) * .21, .04, -Math.cos(fan) * .21],
      rotation: [-Math.PI / 2 + 1.25, 0, 0],
      name: `dial-label-${gear}`,
    })
    label.userData.letter = letter
    label.userData.word = word
    label.renderOrder = 3
    labels[gear] = label
  }
  const readout = add(dial, new THREE.PlaneGeometry(.001, .001), materials.readout, {position: [0, -1, 0], name: 'readout'})
  readout.visible = false
  dial.userData.knob = knob
  dial.userData.lamps = lamps
  dial.userData.labels = labels
  dial.userData.readout = readout
  return dial
}

function buildVisor(materials, tier) {
  const visor = new THREE.Group()
  visor.name = 'cockpit-visor'
  const radius = 1.18
  const arc = 1.32
  const glass = add(visor, new THREE.CylinderGeometry(radius, radius, .26, 96, 1, true, -arc / 2 - Math.PI / 2, arc), materials.glass, {name: 'glass'})
  glass.material.side = THREE.DoubleSide
  add(visor, new THREE.TorusGeometry(radius, .0028, 8, 128, arc), materials.gunmetal, {
    position: [0, .13, 0], rotation: [Math.PI / 2, 0, -arc / 2 - Math.PI / 2], name: 'visor-top-rail',
  })
  visor.userData.tier = tier
  return visor
}

/**
 * Build the cockpit. Returns the group to attach to the camera and an update
 * handle. `tier` from `renderQualityTier` chooses refractive or tinted glass.
 */
export function createCockpit(renderer, {tier = 'balanced'} = {}) {
  const pmrem = new THREE.PMREMGenerator(renderer)
  const environment = pmrem.fromScene(new RoomEnvironment(), .04).texture
  pmrem.dispose()

  const grain = grainTexture()
  const materials = {
    leather: physical({color: 0x0b0e11, roughness: .78, metalness: 0, clearcoat: .3, clearcoatRoughness: .5, sheen: .18, sheenRoughness: .9, sheenColor: new THREE.Color(0x1f272d), bumpMap: grain, bumpScale: .0016, envMap: environment, envMapIntensity: .06}),
    gunmetal: physical({color: 0x1d242a, roughness: .5, metalness: .8, envMap: environment, envMapIntensity: .28}),
    chrome: physical({color: 0xc4ced3, roughness: .2, metalness: 1, envMap: environment, envMapIntensity: .9}),
    brushed: physical({color: 0x4d585f, roughness: .48, metalness: .9, bumpMap: grain, bumpScale: .0009, envMap: environment, envMapIntensity: .55}),
    knurl: physical({color: 0x3f4a51, roughness: .42, metalness: .9, bumpMap: knurlTexture(), bumpScale: .0028, envMap: environment, envMapIntensity: .6}),
    perforated: physical({color: 0x0c0f12, roughness: .82, metalness: 0, clearcoat: .08, clearcoatRoughness: .8, bumpMap: perforationTexture(), bumpScale: .0045, envMap: environment, envMapIntensity: .05}),
    stitch: new THREE.MeshStandardMaterial({map: stitchTexture(), transparent: true, alphaTest: .4, roughness: .9, metalness: 0, color: 0xd9dee2}),
    carbon: physical({map: carbonTexture(), roughness: .32, metalness: .2, clearcoat: .9, clearcoatRoughness: .12, envMap: environment, envMapIntensity: .5}),
    dash: physical({color: 0x090d10, roughness: .74, metalness: 0, clearcoat: .08, clearcoatRoughness: .8, bumpMap: grain, bumpScale: .0012, envMap: environment, envMapIntensity: .15}),
    accent: new THREE.MeshStandardMaterial({color: COCKPIT_ACCENT, emissive: COCKPIT_ACCENT, emissiveIntensity: 1.2, roughness: .3}),
    accentSoft: new THREE.MeshStandardMaterial({color: 0x123846, emissive: COCKPIT_ACCENT, emissiveIntensity: .22, roughness: .5}),
    lamp: new THREE.MeshStandardMaterial({color: 0x30404a, emissive: COCKPIT_ACCENT, emissiveIntensity: .1, roughness: .4}),
    badge: new THREE.MeshStandardMaterial({map: badgeTexture('PLAY', 'FOLLOW'), roughness: .55, metalness: .05}),
    readout: new THREE.MeshBasicMaterial({map: readoutTexture('CAPABILITY', 'NEUTRAL'), toneMapped: false}),
    glass: tier === 'high'
      ? physical({color: 0xb8d6e4, roughness: .06, metalness: 0, transmission: .97, thickness: .02, ior: 1.42, clearcoat: .6, clearcoatRoughness: .15, envMap: environment, envMapIntensity: .35, transparent: true, opacity: 1})
      : physical({color: 0x9fc4d8, roughness: .1, metalness: 0, clearcoat: .6, clearcoatRoughness: .15, envMap: environment, envMapIntensity: .3, transparent: true, opacity: .06}),
  }

  const cockpit = new THREE.Group()
  cockpit.name = 'cockpit'

  const dash = add(cockpit, new THREE.BoxGeometry(3.2, .16, .7), materials.dash, {position: [0, -.56, -1.02], rotation: [.14, 0, 0], name: 'dash'})
  add(cockpit, new THREE.BoxGeometry(2.8, .003, .008), materials.accentSoft, {position: [0, -.482, -.72], rotation: [.14, 0, 0], name: 'dash-glow'})
  add(cockpit, new THREE.CylinderGeometry(.03, .042, .34, 24), materials.gunmetal, {position: [-.14, -.5, -.86], rotation: [1.05, 0, 0], name: 'column'})

  const wheelMount = new THREE.Group()
  wheelMount.position.set(-.13, -.275, -.86)
  wheelMount.rotation.x = .44
  const wheel = buildWheel(materials)
  wheelMount.add(wheel)
  cockpit.add(wheelMount)

  const dial = buildDial(materials)
  dial.position.set(.42, -.265, -.92)
  dial.rotation.x = .22
  dial.scale.setScalar(.66)
  cockpit.add(dial)

  const visor = buildVisor(materials, tier)
  visor.position.set(0, .33, 0)
  cockpit.add(visor)

  // Cabin lighting: a cool key from above the windshield draws the rim
  // highlight, and a faint warm fill keeps the leather from going flat.
  const key = new THREE.DirectionalLight(0xdfeef7, 1.05)
  key.position.set(.15, 1, -.1)
  key.target.position.set(-.1, -.4, -.9)
  cockpit.add(key, key.target)
  const rimLight = new THREE.DirectionalLight(0x9fd6ff, .55)
  rimLight.position.set(-.6, .4, -1.2)
  rimLight.target.position.set(-.13, -.3, -.86)
  cockpit.add(rimLight, rimLight.target)
  const fill = new THREE.PointLight(0xffd9b8, .18, 2.2, 2)
  fill.position.set(.4, -.05, -.5)
  cockpit.add(fill)
  const wash = new THREE.PointLight(COCKPIT_ACCENT, .28, 1.8, 2)
  wash.position.set(-.1, -.3, -.6)
  cockpit.add(wash)

  cockpit.userData = {
    wheel, dial, visor, dash, wash, materials, environment,
    readoutValue: 'NEUTRAL',
    lampGear: '',
  }
  return cockpit
}

const READOUT_LABELS = {call: 'ADAPTER', drive: 'BROWSER', shell: 'SHELL'}

export function gearReadoutLabel(gear) {
  return READOUT_LABELS[gear] || 'NEUTRAL'
}

/** Paint the cockpit for one frame. Angles are degrees from the steering model. */
export function updateCockpit(cockpit, {wheelDeg = 0, dialDeg = 0, gear = '', moving = false, elapsed = 0, glow = 1} = {}) {
  const {wheel, dial, materials, wash} = cockpit.userData
  wheel.rotation.z = -wheelDeg * DEG
  dial.userData.knob.rotation.y = -dialDeg * DEG
  const label = gearReadoutLabel(gear)
  if (label !== cockpit.userData.readoutValue) {
    const previous = dial.userData.readout.material.map
    dial.userData.readout.material.map = readoutTexture('CAPABILITY', label)
    dial.userData.readout.material.needsUpdate = true
    previous?.dispose()
    cockpit.userData.readoutValue = label
  }
  if (gear !== cockpit.userData.lampGear) {
    for (const [lampGear, lamp] of Object.entries(dial.userData.lamps)) {
      lamp.material.emissiveIntensity = lampGear === gear ? 2.2 : .12
    }
    for (const [labelGear, label] of Object.entries(dial.userData.labels)) {
      const previous = label.material.map
      label.material.map = dialLabelTexture(label.userData.letter, label.userData.word, labelGear === gear)
      label.material.needsUpdate = true
      previous?.dispose()
    }
    cockpit.userData.lampGear = gear
  }
  const pulse = moving ? .82 + Math.sin(elapsed * 2.1) * .12 : .55
  materials.accent.emissiveIntensity = 1.2 * pulse * glow + .3
  materials.accentSoft.emissiveIntensity = .14 + .12 * pulse * glow
  wash.intensity = (moving ? .34 : .22) * glow
}

export function disposeCockpit(cockpit) {
  cockpit.traverse((object) => {
    if (object.geometry) object.geometry.dispose()
    if (object.material && !Object.values(cockpit.userData.materials).includes(object.material)) object.material.dispose?.()
  })
  for (const material of Object.values(cockpit.userData.materials)) {
    material.map?.dispose?.()
    material.bumpMap?.dispose?.()
    material.dispose()
  }
  cockpit.userData.environment?.dispose?.()
}
