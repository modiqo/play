import React, {useEffect, useMemo, useRef, useState} from 'react'
import * as THREE from 'three'
import {EffectComposer} from 'three/examples/jsm/postprocessing/EffectComposer.js'
import {RenderPass} from 'three/examples/jsm/postprocessing/RenderPass.js'
import {UnrealBloomPass} from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import {OutputPass} from 'three/examples/jsm/postprocessing/OutputPass.js'
import {KIND_LABEL, MAP_MEANING, WORLD_ROLE, WORLD_STORY} from './semantics.js'
import {adaptiveRenderPixelRatio, renderQualityTier} from './render-quality.mjs'
import {buildDriveWorldPlan, sampleDriveRoute} from './drive-world-plan.mjs'
import {animateDriveEnvironment, createDriveEnvironment, createDriveEvents, createDriveFixture, DRIVE_COLORS, updateDriveFixture} from './drive-world-elements.js'
import {createCockpit, disposeCockpit, updateCockpit} from './cockpit-elements.js'
import {dampAngle, dialAngleForGear, wheelAngleFromTangents, wheelMicroCorrectionDeg} from './steering-model.mjs'
import {formatModelCost, playbackModelTelemetry} from './model-telemetry.mjs'
import Visor from './visor.jsx'

function orientToRoute(object, tangent) {
  object.quaternion.setFromUnitVectors(
    new THREE.Vector3(0, 0, -1),
    new THREE.Vector3(tangent.x, 0, tangent.z).normalize(),
  )
}

function formatTokens(value) {
  const count = Number(value || 0)
  return new Intl.NumberFormat('en-US', {maximumFractionDigits: 0}).format(Math.round(count))
}

function capabilityGear(chapters, sites, index) {
  const records = chapters.slice(0, index + 1).flatMap((item) => sites?.[item.id] || [])
  const record = records.at(-1)
  const explicit = record?.modality || chapters[index]?.modalities?.[0]
  if (!record && !explicit) return ''
  const family = record?.capability?.family
  if (explicit === 'drive' || family === 'browser') return 'drive'
  if (explicit === 'shell' || family === 'proc') return 'shell'
  return 'call'
}

const CAPABILITY_GEARS = [
  {id: 'call', action: 'A', system: 'ADAPTER'},
  {id: 'drive', action: 'B', system: 'BROWSER'},
  {id: 'shell', action: 'S', system: 'SHELL'},
]

function DialPlates({anchorsRef, gear}) {
  const host = useRef(null)
  useEffect(() => {
    let frame = 0
    const paint = () => {
      frame = requestAnimationFrame(paint)
      const node = host.current
      if (!node) return
      for (const plate of node.children) {
        const anchor = anchorsRef.current?.[plate.dataset.gear]
        if (!anchor || !anchor.visible) {
          plate.style.opacity = '0'
          continue
        }
        plate.style.opacity = '1'
        plate.style.transform = `translate(${anchor.x}px, ${anchor.y}px) translate(-50%, -50%)`
      }
    }
    frame = requestAnimationFrame(paint)
    return () => cancelAnimationFrame(frame)
  }, [anchorsRef])
  return <div className="dial-plates" ref={host} aria-hidden="true">
    {CAPABILITY_GEARS.map((item) => <span key={item.id} data-gear={item.id} className={`dial-plate${gear === item.id ? ' active' : ''}`}>
      <b>{item.action}</b><small>{item.system}</small>
    </span>)}
  </div>
}

function Ignition({anchorRef, playing, frozen, progress, departure, onToggle}) {
  const host = useRef(null)
  const [armed, setArmed] = useState(false)
  useEffect(() => { if (playing) setArmed(true) }, [playing])
  useEffect(() => {
    let frame = 0
    const paint = () => {
      frame = requestAnimationFrame(paint)
      const node = host.current
      const anchor = anchorRef.current
      if (!node) return
      if (!anchor || !anchor.visible) { node.style.opacity = '0'; return }
      node.style.opacity = '1'
      node.style.transform = `translate(${anchor.x}px, ${anchor.y}px) translate(-50%, -50%)`
    }
    frame = requestAnimationFrame(paint)
    return () => cancelAnimationFrame(frame)
  }, [anchorRef])
  useEffect(() => {
    const onKey = (event) => {
      const target = event.target
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable || target.tagName === 'BUTTON')) return
      if (event.key === ' ' || event.code === 'Space') { event.preventDefault(); onToggle() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onToggle])
  const state = departure !== null ? 'departing' : playing ? 'driving' : progress >= .999 ? 'arrived' : frozen || armed ? 'held' : 'ready'
  const label = departure !== null ? `${departure || 'GO'}` : playing ? 'PAUSE' : progress >= .999 ? 'REPLAY' : frozen || armed ? 'RESUME' : 'START'
  const ring = departure !== null ? 'DEPARTING' : playing ? 'DRIVING' : progress >= .999 ? 'ARRIVED' : frozen || armed ? 'HELD' : 'IGNITION'
  return <button ref={host} type="button" className={`ignition state-${state}`} onClick={onToggle} aria-label={`${label} the route (Space)`} title="Space">
    <i className="ignition-ring" aria-hidden="true" />
    <b>{label}</b>
    <small>{ring}</small>
  </button>
}

function DriveMetric({label, value, tone = ''}) {
  const previous = useRef(value)
  const [changed, setChanged] = useState(false)
  useEffect(() => {
    if (previous.current === value) return undefined
    previous.current = value
    setChanged(true)
    const timer = window.setTimeout(() => setChanged(false), 460)
    return () => window.clearTimeout(timer)
  }, [value])
  return <div className={`drive-metric ${tone}${changed ? ' changed' : ''}`}>
    <strong title={String(value)}>{value}</strong><span>{label}</span>
  </div>
}

export default function JourneyWorld({story, interactions, replay, playing, frozen, selected, onSelect, onTogglePlayback, exchange, departure = null, destination = null, onChangeJourney, upcoming = [], onChooseJourney}) {
  const host = useRef(null)
  const replayRef = useRef(replay)
  const playingRef = useRef(playing)
  const selectedRef = useRef(selected)
  const gearRef = useRef('')
  const anchorsRef = useRef({})
  const headingRef = useRef(0)
  const dialAnchorsRef = useRef({})
  const hubAnchorRef = useRef(null)
  const [error, setError] = useState('')
  const plan = useMemo(() => buildDriveWorldPlan(story), [story])
  const replayNumber = Number(replay)
  const progress = Number.isFinite(replayNumber) ? THREE.MathUtils.clamp(replayNumber, 0, 1) : 0
  const scaled = progress * Math.max(1, story.chapters.length - 1)
  const currentIndex = Math.max(0, Math.min(story.chapters.length - 1, Math.floor(scaled + .001)))
  const chapter = story.chapters[currentIndex]
  const nextChapter = story.chapters[Math.min(story.chapters.length - 1, currentIndex + 1)]
  const records = interactions?.sites?.[chapter?.id] || []
  const runtimeRecord = interactions?.runtime?.[0] || null
  const telemetry = useMemo(
    () => playbackModelTelemetry(story.chapters, interactions?.sites || {}, currentIndex, records.length, interactions?.runtime || []).journey,
    [currentIndex, interactions?.runtime, interactions?.sites, records.length, story.chapters],
  )
  const gear = useMemo(
    () => capabilityGear(story.chapters, interactions?.sites || {}, currentIndex),
    [currentIndex, interactions?.sites, story.chapters],
  )
  const activeGear = CAPABILITY_GEARS.find((item) => item.id === gear)

  useEffect(() => { replayRef.current = replay }, [replay])
  useEffect(() => { playingRef.current = playing }, [playing])
  useEffect(() => { selectedRef.current = selected }, [selected])
  useEffect(() => { gearRef.current = gear }, [gear])

  useEffect(() => {
    if (!host.current || !story.chapters.length) return undefined
    setError('')
    let disposed = false
    let frame = 0
    let observer
    let renderer
    let composer = null
    let cockpit = null
    try {
      const scene = new THREE.Scene()
      scene.background = new THREE.Color(DRIVE_COLORS.sky)
      scene.fog = new THREE.FogExp2(DRIVE_COLORS.sky, .012)

      const camera = new THREE.PerspectiveCamera(47, 1, .1, 340)
      const desiredCamera = new THREE.Vector3()
      const desiredLook = new THREE.Vector3()
      const cameraLook = new THREE.Vector3()
      const current = new THREE.Vector3()
      const direction = new THREE.Vector3()
      const introStartedAt = performance.now()
      let lastFrameAt = performance.now()

      renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, powerPreference: 'high-performance'})
      renderer.domElement.className = 'world-canvas drive-canvas'
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = THREE.PCFSoftShadowMap
      renderer.outputColorSpace = THREE.SRGBColorSpace
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = 1.04
      host.current.appendChild(renderer.domElement)

      const tier = renderQualityTier({
        devicePixelRatio: window.devicePixelRatio,
        hardwareConcurrency: navigator.hardwareConcurrency,
        width: host.current.clientWidth,
        height: host.current.clientHeight,
        reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true,
      })
      // The driver's hands: a child of the camera so the cockpit never lags
      // the chase. The camera must live in the scene for its children to draw.
      cockpit = createCockpit(renderer, {tier})
      camera.add(cockpit)
      scene.add(camera)
      let wheelDeg = 0
      let dialDeg = dialAngleForGear(gearRef.current)
      const aheadTangent = new THREE.Vector3()
      const projected = new THREE.Vector3()

      scene.add(new THREE.HemisphereLight(0xa8cde4, 0x11181d, 1.9))
      scene.add(new THREE.AmbientLight(0x7891a0, .36))
      const key = new THREE.DirectionalLight(0xd9e9f1, 3.2)
      key.position.set(-26, 38, 18)
      key.castShadow = true
      key.shadow.mapSize.set(2048, 2048)
      key.shadow.camera.left = -34
      key.shadow.camera.right = 34
      key.shadow.camera.top = 42
      key.shadow.camera.bottom = -22
      scene.add(key)

      const environment = createDriveEnvironment(plan)
      scene.add(environment)
      const fixtures = story.chapters.map((item, index) => {
        const site = plan.sites[index]
        const tangent = sampleDriveRoute(plan, index).tangent
        const fixture = createDriveFixture(item, site)
        const events = createDriveEvents(interactions?.sites?.[item.id] || [], site)
        orientToRoute(fixture, tangent)
        orientToRoute(events, tangent)
        scene.add(fixture, events)
        return {fixture, events, chapter: item}
      })

      const statusLight = new THREE.PointLight(DRIVE_COLORS.route, 5.4, 19, 2)
      scene.add(statusLight)

      const resize = () => {
        if (!host.current) return
        const width = host.current.clientWidth
        const height = host.current.clientHeight
        camera.aspect = width / Math.max(1, height)
        camera.updateProjectionMatrix()
        renderer.setPixelRatio(adaptiveRenderPixelRatio(window.devicePixelRatio, width, height))
        renderer.setSize(width, height, false)
        composer?.setSize(width, height)
      }
      if (tier === 'high') {
        composer = new EffectComposer(renderer)
        composer.addPass(new RenderPass(scene, camera))
        const bloom = new UnrealBloomPass(new THREE.Vector2(host.current.clientWidth, host.current.clientHeight), .22, .45, .92)
        composer.addPass(bloom)
        composer.addPass(new OutputPass())
      }
      observer = new ResizeObserver(resize)
      observer.observe(host.current)
      resize()

      const render = () => {
        if (disposed) return
        try {
          const frameAt = performance.now()
          const elapsed = frameAt / 1000
          const deltaSeconds = Math.min(.05, Math.max(1 / 240, (frameAt - lastFrameAt) / 1000))
          lastFrameAt = frameAt
          const replayValue = Number(replayRef.current)
          const boundedReplay = Number.isFinite(replayValue) ? THREE.MathUtils.clamp(replayValue, 0, 1) : 0
          const routeProgress = boundedReplay * Math.max(1, story.chapters.length - 1)
          const sample = sampleDriveRoute(plan, routeProgress)
          current.set(sample.x, sample.y, sample.z)
          direction.set(sample.tangent.x, 0, sample.tangent.z).normalize()

          const intro = THREE.MathUtils.clamp((frameAt - introStartedAt) / 2600, 0, 1)
          const introEase = 1 - Math.pow(1 - intro, 3)
          const chaseDistance = THREE.MathUtils.lerp(21, 12.5, introEase)
          const chaseHeight = THREE.MathUtils.lerp(16, 7.8, introEase)
          desiredCamera.copy(current).addScaledVector(direction, -chaseDistance)
          desiredCamera.y += chaseHeight
          desiredLook.copy(current).addScaledVector(direction, 13.5)
          desiredLook.y += .9

          if (intro < .02) {
            camera.position.copy(desiredCamera)
            cameraLook.copy(desiredLook)
          } else {
            const positionDamping = 1 - Math.exp(-deltaSeconds * (playingRef.current ? 4.8 : 7.2))
            const lookDamping = 1 - Math.exp(-deltaSeconds * 6.4)
            camera.position.lerp(desiredCamera, positionDamping)
            cameraLook.lerp(desiredLook, lookDamping)
          }
          camera.lookAt(cameraLook)

          const reached = Math.max(0, Math.min(fixtures.length - 1, Math.floor(routeProgress + .001)))
          const next = Math.min(fixtures.length - 1, reached + 1)
          const amount = routeProgress - reached
          fixtures.forEach((site, index) => {
            const selectedSite = selectedRef.current?.siteId === site.chapter.id
            updateDriveFixture(site.fixture, {
              active: index === reached,
              approaching: index === next && amount > .18,
              completed: index < reached,
              elapsed,
            })
            site.fixture.visible = index >= reached - 1 && index <= reached + 3
            site.events.visible = index === reached || selectedSite
            site.events.userData.markers?.forEach((marker) => {
              const selectedMarker = selectedSite && marker.userData.sequence === selectedRef.current?.sequence
              marker.scale.setScalar(selectedMarker ? 1.22 : 1)
              if (marker.userData.ring) marker.userData.ring.rotation.z = elapsed * (selectedMarker ? 1.6 : .5)
              marker.traverse((object) => {
                if (!object.material || !Number.isFinite(object.userData.baseEventEmissive)) return
                object.material.emissiveIntensity = selectedMarker
                  ? Math.max(1.1, object.userData.baseEventEmissive * 1.55)
                  : object.userData.baseEventEmissive
              })
            })
          })
          statusLight.position.copy(current).addScaledVector(direction, 3.2)
          statusLight.position.y += 1.3
          statusLight.intensity = playingRef.current ? 6.8 : 4.4
          animateDriveEnvironment(environment, elapsed)

          // Steer by the road ahead, never by the gear.
          const lookAhead = sampleDriveRoute(plan, Math.min(story.chapters.length - 1, routeProgress + .09))
          aheadTangent.set(lookAhead.tangent.x, 0, lookAhead.tangent.z).normalize()
          const moving = Boolean(playingRef.current)
          const wheelTarget = wheelAngleFromTangents(direction, aheadTangent) + wheelMicroCorrectionDeg(elapsed, moving)
          wheelDeg = dampAngle(wheelDeg, wheelTarget, deltaSeconds, moving ? 5.2 : 3.4)
          headingRef.current = wheelDeg
          dialDeg = dampAngle(dialDeg, dialAngleForGear(gearRef.current), deltaSeconds, 7)
          updateCockpit(cockpit, {wheelDeg, dialDeg, gear: gearRef.current, moving, elapsed, glow: 1})

          // Screen anchors for the visor tethers: one per visible bead.
          const width = renderer.domElement.clientWidth
          const height = renderer.domElement.clientHeight
          const anchors = {}
          const reachedSite = fixtures[reached]
          if (reachedSite?.events.visible) {
            for (const marker of reachedSite.events.userData.markers || []) {
              marker.getWorldPosition(projected)
              projected.project(camera)
              // A bead close to the bumper projects below the frame; a real HUD
              // pins the reticle to the edge rather than losing the lock.
              const ahead = projected.z < 1
              const rawX = (projected.x + 1) / 2 * width
              const rawY = (1 - projected.y) / 2 * height
              const margin = 64
              const x = Math.max(margin, Math.min(width - margin, rawX))
              const y = Math.max(margin + 40, Math.min(height - 190, rawY))
              anchors[marker.userData.sequence] = {
                x, y, visible: ahead, clamped: ahead && (x !== rawX || y !== rawY),
              }
            }
          }
          anchorsRef.current = anchors
          const dialAnchors = {}
          for (const [gearId, label] of Object.entries(cockpit.userData.dial.userData.labels)) {
            label.getWorldPosition(projected)
            projected.project(camera)
            dialAnchors[gearId] = {
              x: (projected.x + 1) / 2 * width,
              y: (1 - projected.y) / 2 * height,
              visible: projected.z < 1,
            }
          }
          dialAnchorsRef.current = dialAnchors
          const badge = cockpit.userData.wheel.getObjectByName('badge')
          if (badge) {
            badge.getWorldPosition(projected)
            projected.project(camera)
            hubAnchorRef.current = {x: (projected.x + 1) / 2 * width, y: (1 - projected.y) / 2 * height, visible: projected.z < 1}
          }

          if (composer) composer.render()
          else renderer.render(scene, camera)
          frame = requestAnimationFrame(render)
        } catch (caught) {
          setError(caught instanceof Error ? caught.message : String(caught))
        }
      }
      render()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    }

    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      observer?.disconnect()
      if (cockpit) disposeCockpit(cockpit)
      composer?.dispose?.()
      if (renderer) {
        renderer.dispose()
        renderer.domElement.remove()
      }
    }
  }, [interactions, plan, story])

  if (!chapter) return <div className="journey-world drive-world" ref={host} />
  const stageNumber = String(currentIndex + 1).padStart(2, '0')
  const stageTotal = String(story.chapters.length).padStart(2, '0')
  const nextIsCurrent = nextChapter?.id === chapter.id
  return <div className="journey-world drive-world" ref={host}>
    {error && <div className="world-error">DRIVE VISUALIZATION UNAVAILABLE · {error}</div>}
    <section className="drive-hud" aria-live="polite">
      <div className="drive-now">
        <span><b>{stageNumber}</b> / {stageTotal} · {KIND_LABEL[chapter.kind] || chapter.kind}</span>
        <h2>{chapter.title}</h2>
        <p><strong>{WORLD_ROLE[chapter.kind] || 'Stage'}.</strong> {MAP_MEANING[chapter.kind] || chapter.detail}</p>
        <small>{WORLD_STORY[chapter.kind] || chapter.detail}</small>
      </div>
      {!nextIsCurrent && <div className="drive-next">
        <span>UP NEXT · {KIND_LABEL[nextChapter.kind] || nextChapter.kind}</span>
        <strong>{nextChapter.title}</strong>
      </div>}
    </section>
    <Visor chapter={chapter} records={records} selected={selected} onSelect={onSelect} exchange={exchange} anchorsRef={anchorsRef} headingRef={headingRef} playing={playing} />
    <div className="drive-dashboard" aria-label="Run telemetry dashboard">
      <div className="drive-cluster-left">
        <span className={`drive-motion-state${playing ? ' moving' : ''}`}>{playing && progress < .002 ? 'DEPARTING' : playing ? 'ROUTE ENGAGED' : frozen ? 'VANTAGE HELD' : 'READY'}</span>
        <div className="drive-readouts drive-readouts-left">
          <DriveMetric label="TOKENS" value={formatTokens(Number(telemetry.input_tokens || 0) + Number(telemetry.output_tokens || 0))} />
          <DriveMetric label="COST" value={formatModelCost(telemetry.cost_usd)} />
        </div>
        {runtimeRecord && <button
          className={`drive-runtime-control${selected?.runtime && selected.sequence === runtimeRecord.sequence ? ' selected' : ''}`}
          onClick={() => onSelect({
            siteId: runtimeRecord.site_id || story.chapters[0]?.id,
            sequence: runtimeRecord.sequence,
            runtime: true,
          })}
          title={`Inspect Play runtime @${runtimeRecord.sequence}`}
        >RUNTIME <b>@{String(runtimeRecord.sequence).padStart(2, '0')}</b></button>}
      </div>
      <div className="drive-dashboard-clearance" data-gear={activeGear?.system || 'NEUTRAL'}>
        {destination && <div className="drive-destination">
          <span>DESTINATION</span>
          <strong title={destination.title}>{destination.title}</strong>
          <em>{destination.status}</em>
          <button type="button" onClick={onChangeJourney} title="Open the departure board (J)">CHANGE · J</button>
        </div>}
      </div>
    </div>
    <DialPlates anchorsRef={dialAnchorsRef} gear={gear} />
    <Ignition anchorRef={hubAnchorRef} playing={playing} frozen={frozen} progress={progress} departure={departure} onToggle={onTogglePlayback} />
    {progress >= .999 && !playing && <section className="hud-arrival" aria-label="Arrived">
      <i className="hud-corner tl" /><i className="hud-corner tr" /><i className="hud-corner bl" /><i className="hud-corner br" />
      <span>ARRIVED</span>
      <strong>{destination?.title || story.outcome}</strong>
      {upcoming.length > 0 && <div className="hud-arrival-next">
        <small>NEXT JOURNEYS</small>
        {upcoming.map((item) => <button key={item.id} type="button" onClick={() => onChooseJourney?.(item)}>
          <b>{item.journey_mode === 'live' ? 'LIVE' : item.tutorial ? 'START HERE' : item.journey_mode === 'workspace' ? 'WORKSPACE' : 'RECORDED'}</b>
          <span>{item.intent}</span>
        </button>)}
      </div>}
      <button type="button" className="hud-arrival-again" onClick={onTogglePlayback}>DRIVE AGAIN · SPACE</button>
      <button type="button" className="hud-arrival-board" onClick={onChangeJourney}>DEPARTURE BOARD · J</button>
    </section>}
    <aside className="drive-side-strip" aria-label="Run outcome readouts">
      <DriveMetric label="SUCCESS" value={telemetry.success} tone="green" />
      <DriveMetric label="ERRORS" value={telemetry.error} tone={telemetry.error ? 'red' : ''} />
    </aside>
  </div>
}
