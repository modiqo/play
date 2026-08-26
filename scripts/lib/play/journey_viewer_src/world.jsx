import React, {useEffect, useMemo, useRef, useState} from 'react'
import * as THREE from 'three'
import {KIND_LABEL, MAP_MEANING, WORLD_ROLE, WORLD_STORY} from './semantics.js'
import {adaptiveRenderPixelRatio} from './render-quality.mjs'
import {buildDriveWorldPlan, sampleDriveRoute} from './drive-world-plan.mjs'
import {animateDriveEnvironment, createDriveEnvironment, createDriveEvents, createDriveFixture, DRIVE_COLORS, updateDriveFixture} from './drive-world-elements.js'
import {interactionStateLabel} from './interaction-affordance.mjs'
import {formatModelCost, playbackModelTelemetry} from './model-telemetry.mjs'

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

export default function JourneyWorld({story, interactions, replay, playing, frozen, selected, onSelect, onTogglePlayback}) {
  const host = useRef(null)
  const replayRef = useRef(replay)
  const playingRef = useRef(playing)
  const selectedRef = useRef(selected)
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

  useEffect(() => {
    if (!host.current || !story.chapters.length) return undefined
    setError('')
    let disposed = false
    let frame = 0
    let observer
    let renderer
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
          renderer.render(scene, camera)
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
        <button
          className={`drive-primary-play${playing ? ' playing' : frozen ? ' frozen' : ''}`}
          onClick={onTogglePlayback}
          aria-label={playing ? 'Pause journey playback' : frozen ? 'Resume journey playback' : progress >= .999 ? 'Replay journey' : 'Play journey'}
        >
          <i className="drive-play-glyph" aria-hidden="true" />
          <span><b>{playing ? 'PAUSE ROUTE' : frozen ? 'RESUME ROUTE' : progress >= .999 ? 'REPLAY ROUTE' : 'PLAY ROUTE'}</b><small>{playing ? 'HOLD AT CURRENT POSITION' : frozen ? 'CONTINUE TO NEXT SITE' : progress >= .999 ? 'RETURN TO THE START' : 'BEGIN THE RECORDED TRAVERSAL'}</small></span>
          <em>{playing ? 'Ⅱ' : '▶'}</em>
        </button>
      </div>
      {!nextIsCurrent && <div className="drive-next">
        <span>UP NEXT · {KIND_LABEL[nextChapter.kind] || nextChapter.kind}</span>
        <strong>{nextChapter.title}</strong>
      </div>}
      {!!records.length && <div className="drive-events" aria-label="Recorded interactions">
        <div className="drive-events-heading"><span>RECORDED EXCHANGES</span><b>{records.length}</b></div>
        {records.map((record) => <button
          key={record.sequence}
          className={selected?.sequence === record.sequence ? 'selected' : ''}
          onClick={() => onSelect(selected?.sequence === record.sequence ? null : {siteId: chapter.id, sequence: record.sequence})}
        >
          <i className="drive-event-evidence" aria-hidden="true"><u /><u /></i>
          <span className="drive-event-index">@{String(record.sequence).padStart(2, '0')}</span>
          <strong>{record.capability?.label || record.operation}</strong>
          <small>{interactionStateLabel(record)}</small>
          <span className="drive-event-action">
            <span className="drive-event-flow"><b>REQ</b><i>→</i><b>RES</b></span>
            <em>INSPECT</em><b className="drive-event-chevron">›</b>
          </span>
        </button>)}
      </div>}
    </section>
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
      <div className="drive-dashboard-clearance">
        <div
          className={`drive-cockpit gear-${gear || 'neutral'}${playing ? ' moving' : ''}`}
          role="status"
          aria-live="polite"
          aria-label={`Capability gear: ${activeGear?.system || 'neutral'}`}
        >
          <div className="drive-steering-column" aria-hidden="true">
            <div className="drive-steering-wheel">
              <i className="drive-wheel-rim" />
              <i className="drive-wheel-spoke drive-wheel-spoke-left" />
              <i className="drive-wheel-spoke drive-wheel-spoke-right" />
              <i className="drive-wheel-spoke drive-wheel-spoke-lower" />
              <span className="drive-wheel-hub"><b>PLAY</b><small>FOLLOW</small></span>
            </div>
          </div>
          <div className="drive-capability-shifter">
            <span>CAPABILITY GEAR</span>
            <strong>{activeGear?.system || 'NEUTRAL'}</strong>
            <div className="drive-shift-gate" aria-hidden="true">
              <i className="drive-shift-rail" />
              <i className="drive-shift-lever"><b /></i>
              {CAPABILITY_GEARS.map((item) => <span
                className={`drive-shift-option${gear === item.id ? ' active' : ''}`}
                key={item.id}
              ><b>{item.action}</b><small>{item.system}</small></span>)}
            </div>
          </div>
        </div>
      </div>
      <div className="drive-cluster-right">
        <div className="drive-readouts drive-readouts-right">
        <DriveMetric label="SUCCESS" value={telemetry.success} tone="green" />
        <DriveMetric label="ERRORS" value={telemetry.error} tone={telemetry.error ? 'red' : ''} />
        </div>
      </div>
    </div>
  </div>
}
