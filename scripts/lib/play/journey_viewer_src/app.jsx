import React from 'react'
import Cartography from './atlas.jsx'
import {formatNumber} from './format.js'
import {KIND_LABEL, MAP_MEANING} from './semantics.js'
import {journeyTrackerIndexes} from './journey-position.mjs'
import {journeyActivityLabel, journeyKind, journeyPickerItems} from './journey-picker.mjs'
import {EXPERIENCE_SCALES, adjacentExperienceScale, defaultExperienceScale, markerScaleForExperience, storedExperienceScale} from './experience-scale.mjs'
import {useJourneyRuntime} from './use-journey-runtime.js'
import JourneyWorld from './world.jsx'
import DepartureBoard from './board.jsx'
import {departureCountdown, nextJourneys} from './departure-board.mjs'
import {workspaceFromLocation} from './api.js'

export default function App() {
  const [viewport, setViewport] = React.useState(() => ({width: window.innerWidth, height: window.innerHeight}))
  const [experienceScale, setExperienceScale] = React.useState(() => {
    try {
      const stored = storedExperienceScale(window.localStorage.getItem('play-journey:experience-scale:v1'))
      if (stored) return stored
    } catch {}
    return defaultExperienceScale(window.innerWidth, window.innerHeight)
  })
  React.useEffect(() => {
    const update = () => setViewport({width: window.innerWidth, height: window.innerHeight})
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  React.useEffect(() => {
    try { window.localStorage.setItem('play-journey:experience-scale:v1', String(experienceScale)) } catch {}
  }, [experienceScale])
  const markerScale = markerScaleForExperience(experienceScale, viewport.width, viewport.height)
  // The departure board is the opening scene unless a deep link named a journey.
  const [boardOpen, setBoardOpen] = React.useState(() => !workspaceFromLocation)
  const [departure, setDeparture] = React.useState(null)
  const autoDepartRef = React.useRef(workspaceFromLocation ? 'initial' : null)
  const panelScale = 1 + (experienceScale - 1) * .48
  const {
    index, workspace, story, interactions, selected, setSelected, exchange,
    replay, playing, observing, trackingLive, snapshotCountdown, lastSnapshotAt, fitSignal, setFitSignal,
    mode, setMode, message, loadError, journeysOpen, setJourneysOpen,
    refreshing,
    choose, refreshWorkspaces, togglePlayback, toggleLiveTracking, jumpToChapter, selectVantage, freezeAtProgress,
  } = useJourneyRuntime()
  const chapter = story?.chapters.find((item) => item.id === selected?.siteId)
  const interaction = selected?.sequence
    ? selected.runtime
      ? interactions?.runtime?.find((item) => item.sequence === selected.sequence)
      : interactions?.sites?.[selected.siteId]?.find((item) => item.sequence === selected.sequence)
    : null
  const runtimeInteraction = interaction?.presentation_role === 'play_runtime'
  const presentedKind = interaction?.semantic_kind || chapter?.kind
  const selectedWorkspace = index?.workspaces.find((item) => item.id === workspace)
  const liveCapture = selectedWorkspace?.journey_mode === 'live'
  const liveActivity = Boolean(liveCapture && selectedWorkspace?.active_recently)
  const recalled = story?.origin?.kind === 'recalled_play'
  const isTutorial = story?.origin?.kind === 'tutorial'
  const status = isTutorial ? 'START HERE' : recalled ? 'RECALLED PLAY' : trackingLive ? 'LIVE · TRACKING' : liveActivity ? 'LIVE · UPDATING' : liveCapture ? 'LIVE · QUIET' : 'RECORDED'
  const replayChapter = story ? Math.min(story.chapters.length - 1, Math.floor(replay * Math.max(1, story.chapters.length - 1) + .001)) : 0
  const currentReplayChapter = story?.chapters[replayChapter]
  const trackerIndexes = journeyTrackerIndexes(story?.chapters || [], replayChapter)
  const pickerItems = journeyPickerItems(index?.workspaces || [])
  const journeyCount = pickerItems.filter((item) => !item.tutorial).length
  const frozen = mode === 'follow' && observing && !playing
  const upcoming = React.useMemo(() => nextJourneys(index?.workspaces || [], workspace, 3), [index?.workspaces, workspace])
  const pick = React.useCallback((item) => {
    autoDepartRef.current = item.id
    setBoardOpen(false)
    return choose(item)
  }, [choose])
  const playingRef = React.useRef(playing)
  React.useEffect(() => { playingRef.current = playing }, [playing])
  const replayRef = React.useRef(replay)
  React.useEffect(() => { replayRef.current = replay }, [replay])
  // A chosen journey departs on its own after a short countdown; the driver
  // only ever has to pause. Live tracking already follows the harness.
  React.useEffect(() => {
    if (!story || mode !== 'follow' || !workspace) return undefined
    const pending = autoDepartRef.current
    if (pending !== workspace && pending !== 'initial') return undefined
    // The story for a freshly chosen journey arrives after `workspace`
    // changes, so the pending flag stays set until the countdown actually
    // completes; an interrupted countdown simply restarts with the new story.
    const seconds = departureCountdown({live: liveCapture, tracking: trackingLive})
    if (seconds === 0) {
      autoDepartRef.current = null
      return undefined
    }
    setDeparture(seconds)
    const timers = []
    for (let tick = 1; tick <= seconds; tick += 1) timers.push(window.setTimeout(() => setDeparture(seconds - tick), tick * 1000))
    timers.push(window.setTimeout(() => {
      autoDepartRef.current = null
      setDeparture(null)
      if (!playingRef.current && replayRef.current < .999) togglePlayback()
    }, seconds * 1000 + 250))
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer))
      setDeparture(null)
    }
  }, [story?.journey_key, mode, workspace])
  React.useEffect(() => {
    const onKey = (event) => {
      const target = event.target
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
      if ((event.key === 'j' || event.key === 'J') && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault()
        setBoardOpen((value) => !value)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  // In Follow, the visor unfolds exchanges on the windshield; the aside is for Atlas.
  const showEvidencePanel = chapter && mode !== 'follow'
  const changeMode = (nextMode) => {
    if (nextMode === mode) {
      if (nextMode !== 'follow') setFitSignal((value) => value + 1)
      return
    }
    freezeAtProgress(replay)
    setSelected(null)
    setMode(nextMode)
    if (nextMode !== 'follow') setFitSignal((value) => value + 1)
  }

  return <main
    className={`dark mode-${mode}${frozen ? ' is-frozen' : ''}${trackingLive ? ' is-live-tracking' : ''}${showEvidencePanel ? ' evidence-open' : ''}`}
    style={{'--experience-scale': experienceScale, '--experience-panel-scale': panelScale, '--experience-marker-scale': markerScale}}
  >
    <section className="atlas-stage">
      {story && interactions
        ? mode === 'follow'
          ? <JourneyWorld key={`follow:${story.journey_key}`} story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} selected={selected} onSelect={selectVantage} onTogglePlayback={togglePlayback} markerScale={markerScale} exchange={exchange} departure={departure} destination={{title: selectedWorkspace?.intent || story?.outcome || 'Captured exploration', status}} onChangeJourney={() => setBoardOpen(true)} upcoming={upcoming} onChooseJourney={pick} />
          : <Cartography key={`${mode}:${story.journey_key}`} story={story} interactions={interactions} replay={replay} playing={playing} selected={selected} onSelect={setSelected} fitSignal={fitSignal} markerScale={markerScale} />
        : loadError
          ? <div className="loading failed"><strong>JOURNEY CONNECTION LOST</strong><span>{loadError}</span><code>play-journey view --active</code></div>
          : <div className="loading"><i />CONSTRUCTING JOURNEY ATLAS</div>}
    </section>
    <header>
      <div className="header-launcher">
        <div className="brand"><strong>PLAY</strong><small>{mode === 'follow' ? 'FOLLOW' : 'ATLAS'}</small></div>
        <button
          className={`journey-picker-trigger${boardOpen ? ' active' : ''}`}
          onClick={() => setBoardOpen((value) => !value)}
          aria-expanded={boardOpen}
          aria-controls="departure-board"
          title="Open the departure board (J)"
        >
          <i className="file-picker-icon" aria-hidden="true" />
          <span>JOURNEYS</span>
          <small>{journeyCount}</small>
          <b aria-hidden="true">⌄</b>
        </button>
      </div>
      <div className={`header-title${liveActivity ? ' live' : ''}`}>
        <i />
        <div className="header-identity" title={`${selectedWorkspace?.intent || story?.outcome || 'Captured exploration'}\n${selectedWorkspace?.workspace_path || selectedWorkspace?.workspace || workspace || ''}`}>
          <span>{selectedWorkspace?.intent || story?.outcome || 'Captured exploration'}</span>
          <code>{liveActivity ? `LIVE · NEXT ${String(snapshotCountdown).padStart(2, '0')}s` : status}</code>
        </div>
      </div>
      <div className="header-actions">
        <button className={`header-refresh${refreshing ? ' refreshing' : ''}`} disabled={refreshing} onClick={refreshWorkspaces} title="Refresh Play projections" aria-label="Refresh Play projections">↻</button>
        <div className="view-switch" aria-label="View">
          <button className={mode === 'follow' ? 'active' : ''} onClick={() => changeMode('follow')}>FOLLOW</button>
          <button className={mode === 'atlas' ? 'active' : ''} onClick={() => changeMode('atlas')}>ATLAS</button>
        </div>
        {mode !== 'follow' && <button onClick={() => setFitSignal((value) => value + 1)}>FIT</button>}
        <button
          className="experience-scale-cycle"
          onClick={() => setExperienceScale((value) => value === EXPERIENCE_SCALES.at(-1) ? EXPERIENCE_SCALES[0] : adjacentExperienceScale(value, 1))}
          title="Cycle experience scale"
          aria-label={`Experience scale ${Math.round(experienceScale * 100)} percent; activate to cycle`}
        >A·{Math.round(experienceScale * 100)}</button>
      </div>
    </header>
    <aside
      className={`landmark-panel${showEvidencePanel ? ' visible' : ''}${runtimeInteraction ? ' runtime-evidence' : ''}`}
      onMouseLeave={interaction ? () => setSelected(null) : undefined}
    >
      {showEvidencePanel && <>
        <div className="panel-heading"><span>{runtimeInteraction ? `PLAY RUNTIME @${interaction.sequence}` : interaction ? `INTERACTION @${interaction.sequence}` : `DISTRICT ${String(chapter.order + 1).padStart(2, '0')}`}</span><button onClick={() => setSelected(null)}>×</button></div>
        <span className="kind">{runtimeInteraction ? 'RUNTIME ENVELOPE' : KIND_LABEL[presentedKind] || presentedKind}</span>
        <h1>{interaction ? interaction.capability?.label || interaction.operation : chapter.title}</h1>
        <p>{runtimeInteraction ? `${interaction.operation} · executes the unfurled Play` : interaction ? `${interaction.operation} · situated at ${chapter.title}` : chapter.detail}</p>
        <div className="meaning"><strong>WHY THIS STEP EXISTS</strong><span>{runtimeInteraction ? 'Runs the Play and contributes telemetry without becoming a capability or route site.' : MAP_MEANING[presentedKind] || 'Advances the requested outcome while preserving evidence.'}</span></div>
        {interaction ? <>
          <dl>
            <dt>OPERATION</dt><dd>{interaction.operation}</dd><dt>STATE</dt><dd>{interaction.status}</dd>
            <dt>ACCESS</dt><dd>{(interaction.effect_profile?.posture || interaction.effect || 'unknown').toUpperCase()}</dd>
            <dt>SCOPE</dt><dd>{interaction.effect_profile?.scopes?.join(' · ') || 'not declared'}</dd>
            <dt>BASIS</dt><dd>{interaction.effect_profile?.source?.replaceAll('_', ' ') || 'legacy projection'}</dd>
            <dt>LATENCY</dt><dd>{formatNumber(interaction.duration_ms)} ms</dd><dt>TOKENS</dt><dd>{formatNumber(interaction.tokens)}</dd>
            <dt>INPUT</dt><dd>{formatNumber(interaction.input_tokens)}</dd><dt>OUTPUT</dt><dd>{formatNumber(interaction.output_tokens)}</dd>
            <dt>COST*</dt><dd>{Number.isFinite(interaction.estimated_cost_usd) ? `$${interaction.estimated_cost_usd.toFixed(6)}` : 'not priced'}</dd>
            <dt>AVOIDED</dt><dd>{formatNumber(interaction.tokens_saved)}</dd>
            {interaction.provider && <><dt>PROVIDER</dt><dd>{interaction.provider}</dd></>}
            {interaction.capability && <>
              <dt>CAPABILITY</dt><dd>{interaction.capability.family} · {interaction.capability.interface}</dd>
              {interaction.capability_ref && <><dt>INSTANCE</dt><dd>{interaction.capability_ref}</dd></>}
              {interaction.modality && <><dt>MODALITY</dt><dd>{interaction.modality.toUpperCase()}</dd></>}
              {interaction.lifecycle_phase && <><dt>LIFECYCLE</dt><dd>{interaction.lifecycle_phase.toUpperCase()}</dd></>}
              <dt>SYSTEM</dt><dd>{interaction.capability.label}</dd>
              {interaction.capability.mode && <><dt>MODE</dt><dd>{interaction.capability.mode}</dd></>}
              {interaction.capability.primitive && <><dt>PRIMITIVE</dt><dd>{interaction.capability.primitive}</dd></>}
              {interaction.capability.transport && <><dt>TRANSPORT</dt><dd>{interaction.capability.transport}</dd></>}
              {interaction.capability.manifest?.spec_type && <><dt>MANIFEST</dt><dd>{interaction.capability.manifest.spec_type} · schema {interaction.capability.manifest.schema}</dd></>}
              {interaction.capability.manifest?.operation_scope && <><dt>ACCESS</dt><dd>{interaction.capability.manifest.operation_scope}</dd></>}
            </>}
          </dl>
          <section className="exchange">
            {exchange?.loading && <p>LOADING OWNER-PRIVATE EVIDENCE…</p>}
            {exchange?.error && <p>{exchange.error}</p>}
            {exchange?.schema && <>
              <div className="evidence-note">REDACTED DISPLAY COPY{exchange.truncated ? ' · TRUNCATED' : ''}</div>
              <h2>REQUEST</h2><pre>{JSON.stringify(exchange.request, null, 2)}</pre>
              <h2>RESPONSE</h2><pre>{JSON.stringify(exchange.response, null, 2)}</pre>
            </>}
          </section>
        </> : <>
          <dl>
            <dt>STATE</dt><dd>{chapter.status}</dd><dt>EVENTS</dt><dd>{interactions?.sites?.[chapter.id]?.length || 0}</dd>
            <dt>LATENCY</dt><dd>{formatNumber(chapter.telemetry.duration_ms)} ms</dd><dt>TOKENS</dt><dd>{formatNumber(chapter.telemetry.payload_tokens)}</dd>
            <dt>AVOIDED</dt><dd>{formatNumber(chapter.telemetry.tokens_saved)}</dd>
            {chapter.provider && <><dt>PROVIDER</dt><dd>{chapter.provider}</dd></>}
          </dl>
          <details><summary>EVIDENCE REFERENCES</summary><pre>{Object.entries(chapter.evidence).filter(([, values]) => values?.length).map(([key, values]) => `${key}: ${values.join(', ')}`).join('\n') || 'No opaque evidence references recorded'}</pre></details>
        </>}
      </>}
    </aside>
    {boardOpen && index && <DepartureBoard
      items={index.workspaces || []}
      current={workspace}
      onChoose={pick}
      onClose={() => setBoardOpen(false)}
      canClose={Boolean(story)}
      refreshing={refreshing}
      onRefresh={refreshWorkspaces}
    />}
    <footer>
      <div className="replay">
        <div className="replay-controls">
          <button className={playing ? 'playing' : frozen ? 'frozen' : ''} onClick={togglePlayback}>{playing ? 'Ⅱ FREEZE' : frozen ? '▶ RESUME' : '▶ PLAY'}</button>
          {liveCapture && <button className={`live-track${trackingLive ? ' active' : ''}`} disabled={story?.state !== 'active'} onClick={toggleLiveTracking} title="Follow new call sites as calm snapshots arrive" aria-label={trackingLive ? 'Stop tracking live head' : 'Track live head'}>{trackingLive ? '● LIVE' : '○ LIVE'}</button>}
        </div>
        <div className={`replay-track${(story?.chapters.length || 0) > 14 ? ' condensed' : ''}`} style={{'--progress': `${replay * 100}%`}}>
          <span className="track-anchor start">START</span>
          <span className={`track-anchor end${story?.state === 'active' ? ' live' : ''}`}>{story?.state === 'active' ? 'LIVE' : 'END'}</span>
          <input aria-label="Journey replay" type="range" min="0" max="1" step="0.002" value={replay} onChange={(event) => { freezeAtProgress(Number(event.target.value)) }} />
          <div className="chapter-markers">
            {trackerIndexes.map((itemIndex, markerIndex) => {
              const item = story.chapters[itemIndex]
              const number = String(itemIndex + 1).padStart(2, '0')
              const kind = (KIND_LABEL[item.kind] || item.kind || 'stage').toUpperCase()
              const hiddenUntilNext = Math.max(0, (trackerIndexes[markerIndex + 1] ?? itemIndex + 1) - itemIndex - 1)
              const left = itemIndex / Math.max(1, story.chapters.length - 1) * 100
              const nextIndex = trackerIndexes[markerIndex + 1]
              const nextLeft = Number.isInteger(nextIndex) ? nextIndex / Math.max(1, story.chapters.length - 1) * 100 : left
              const state = itemIndex === replayChapter ? 'current' : itemIndex < replayChapter ? 'reached' : ''
              return <React.Fragment key={item.id}>
                <button
                  className={state}
                  style={{left: `${left}%`}}
                  onClick={() => jumpToChapter(itemIndex)}
                  aria-label={`Open stage ${number}: ${kind}, ${item.title}`}
                  data-kind={item.kind || 'phase'}
                  data-tooltip={`OPEN STAGE ${number} · ${kind} · ${item.title}${hiddenUntilNext ? ` · ${hiddenUntilNext} intermediate stage${hiddenUntilNext === 1 ? '' : 's'}` : ''}`}
                >
                  <span className="marker-core" />
                  {hiddenUntilNext > 0 && <small className="marker-cluster">+{hiddenUntilNext}</small>}
                  {itemIndex === replayChapter && <span className="marker-current-label">
                    <b>{number} · {kind}</b><em>{item.title}</em>
                  </span>}
                </button>
                {Number.isInteger(nextIndex) && <i
                  className="marker-segment"
                  style={{left: `${left}%`, width: `${Math.max(0, nextLeft - left)}%`}}
                />}
              </React.Fragment>
            })}
          </div>
          {liveCapture && story?.state === 'active' && <button
            className={`live-trace-point${trackingLive ? ' active' : ''}`}
            onClick={toggleLiveTracking}
            aria-label={`Track live at stage ${story.chapters.length}`}
            data-tooltip={`LIVE HEAD · ${String(story.chapters.length).padStart(2, '0')} · CLICK TO WATCH`}
          />}
        </div>
        <em className="replay-position">
          {story
            ? <><b>{String(replayChapter + 1).padStart(2, '0')}</b><span>/ {String(story.chapters.length).padStart(2, '0')} · {(KIND_LABEL[currentReplayChapter?.kind] || currentReplayChapter?.kind || 'stage').toUpperCase()}</span></>
            : '00 / 00'}
        </em>
      </div>
      <span className="footer-message" aria-live="polite">{trackingLive ? `TRACKING LIVE HEAD · NEXT SNAPSHOT ${String(snapshotCountdown).padStart(2, '0')}s` : playing ? `PLAYING SNAPSHOT · ${message}` : frozen ? `FROZEN VANTAGE · ${message}` : lastSnapshotAt && liveCapture ? `READY TO PLAY FROM HERE · SNAPSHOT ${new Date(lastSnapshotAt).toLocaleTimeString()} · ${message}` : `READY TO PLAY · ${message}`}</span>
    </footer>
  </main>
}
