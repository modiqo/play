import React from 'react'
import Cartography from './atlas.jsx'
import {formatNumber} from './format.js'
import {CapabilityRail, JourneyGuide, ModelLiveCounter, Telemetry, TutorialExperience, WorldModel} from './panels.jsx'
import {KIND_LABEL, MAP_MEANING} from './semantics.js'
import {journeyTrackerIndexes} from './journey-position.mjs'
import {EXPERIENCE_SCALES, adjacentExperienceScale, defaultExperienceScale, markerScaleForExperience, storedExperienceScale} from './experience-scale.mjs'
import {useJourneyRuntime} from './use-journey-runtime.js'
import JourneyWorld from './world.jsx'

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
  const panelScale = 1 + (experienceScale - 1) * .48
  const {
    index, workspace, story, interactions, tutorial, selected, setSelected, exchange,
    replay, playing, observing, trackingLive, snapshotCountdown, lastSnapshotAt, fitSignal, setFitSignal,
    mode, setMode, message, loadError, journeysOpen, setJourneysOpen,
    telemetryOpen, setTelemetryOpen, worldModelOpen, setWorldModelOpen, refreshing,
    choose, refreshWorkspaces, togglePlayback, toggleLiveTracking, jumpToChapter, selectVantage, freezeAtProgress,
  } = useJourneyRuntime()
  const chapter = story?.chapters.find((item) => item.id === selected?.siteId)
  const interaction = selected?.sequence
    ? interactions?.sites?.[selected.siteId]?.find((item) => item.sequence === selected.sequence)
    : null
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
  const frozen = mode === 'follow' && observing && !playing
  const tutorialEntryModelActive = Boolean(isTutorial && worldModelOpen)

  const showEvidencePanel = chapter && (mode !== 'follow' || interaction)
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
    className={`dark mode-${mode}${frozen ? ' is-frozen' : ''}${trackingLive ? ' is-live-tracking' : ''}${isTutorial ? ' tutorial-guided' : ''}${tutorialEntryModelActive ? ' world-model-active' : ''}`}
    style={{'--experience-scale': experienceScale, '--experience-panel-scale': panelScale, '--experience-marker-scale': markerScale}}
  >
    <section className="atlas-stage">
      {story && interactions
        ? mode === 'follow'
          ? <JourneyWorld key={`follow:${story.journey_key}`} story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} selected={selected} onSelect={selectVantage} markerScale={markerScale} />
          : <Cartography key={`${mode}:${story.journey_key}`} story={story} interactions={interactions} replay={replay} playing={playing} selected={selected} onSelect={setSelected} fitSignal={fitSignal} markerScale={markerScale} />
        : loadError
          ? <div className="loading failed"><strong>JOURNEY CONNECTION LOST</strong><span>{loadError}</span><code>play-journey view --active</code></div>
          : <div className="loading"><i />CONSTRUCTING JOURNEY ATLAS</div>}
    </section>
    <header>
      <button className="brand" onClick={() => setJourneysOpen((value) => !value)}><strong>PLAY CARTOGRAPHY</strong><small>{mode === 'follow' ? 'JOURNEY FOLLOW' : 'JOURNEY ATLAS'}</small></button>
      <div className={`header-title${liveActivity ? ' live' : ''}`}>
        <i />
        <div className="header-state"><b>{status}</b>{recalled ? <small>KNOWN ROUTE · DISCOVERY SKIPPED</small> : liveActivity && <small>NEXT SNAPSHOT {String(snapshotCountdown).padStart(2, '0')}s</small>}</div>
        <div className="header-identity" title={`${selectedWorkspace?.intent || story?.outcome || 'Captured exploration'}\n${selectedWorkspace?.workspace_path || selectedWorkspace?.workspace || workspace || ''}`}>
          <span>{selectedWorkspace?.intent || story?.outcome || 'Captured exploration'}</span>
          <code>{recalled && story?.origin?.exact_reference ? `${story.origin.exact_reference} · ` : ''}{selectedWorkspace?.workspace_path || selectedWorkspace?.workspace || workspace || 'Workspace loading'}</code>
        </div>
      </div>
      <div className="header-actions">
        <button className={refreshing ? 'refreshing' : ''} disabled={refreshing} onClick={refreshWorkspaces} title="Rescan the current Rote workspace root and refresh its Play projections">{refreshing ? 'REFRESHING' : '↻ REFRESH'}</button>
        <button className={mode === 'follow' ? 'active' : ''} onClick={() => changeMode('follow')}>FOLLOW</button>
        <button className={mode === 'atlas' ? 'active' : ''} onClick={() => changeMode('atlas')}>ATLAS</button>
        {mode !== 'follow' && <button onClick={() => setFitSignal((value) => value + 1)}>FIT</button>}
        <div className="experience-scale-control" aria-label="Experience scale">
          <button
            disabled={experienceScale === EXPERIENCE_SCALES[0]}
            onClick={() => setExperienceScale((value) => adjacentExperienceScale(value, -1))}
            title="Decrease text, cards, callouts, and glass bead size"
            aria-label="Decrease experience scale"
          >A−</button>
          <button
            className="experience-scale-value"
            onClick={() => setExperienceScale(1)}
            title="Reset experience scale"
            aria-label={`Experience scale ${Math.round(experienceScale * 100)} percent; reset to standard`}
          >{Math.round(experienceScale * 100)}%</button>
          <button
            disabled={experienceScale === EXPERIENCE_SCALES.at(-1)}
            onClick={() => setExperienceScale((value) => adjacentExperienceScale(value, 1))}
            title="Increase text, cards, callouts, and glass bead size"
            aria-label="Increase experience scale"
          >A+</button>
        </div>
      </div>
    </header>
    <aside className={`journey-drawer${journeysOpen ? ' open' : ''}`}>
      <div className="panel-heading"><span>JOURNEY ARCHIVE</span><button onClick={() => setJourneysOpen(false)}>×</button></div>
      <div className="workspace-list">{index?.workspaces.map((item) => {
        const unavailable = !item.graph_ready && !item.projectable
        const stateLabel = workspace === item.id
          ? item.tutorial ? 'VIEWING · TUTORIAL' : recalled ? 'VIEWING · RECALLED' : item.journey_mode === 'live' && item.active_recently ? 'VIEWING · LIVE' : item.journey_mode === 'live' ? 'VIEWING · QUIET' : item.journey_mode === 'workspace' ? 'VIEWING · WORKSPACE' : 'VIEWING · RECORDED'
          : item.tutorial
            ? 'START HERE'
            : item.graph_ready && item.journey_mode === 'live' && item.active_recently
            ? 'LIVE · UPDATING'
            : item.graph_ready && item.journey_mode === 'live'
              ? 'LIVE · QUIET'
            : item.graph_ready && item.journey_mode === 'workspace'
              ? 'WORKSPACE SNAPSHOT'
            : item.graph_ready
              ? 'RECORDED'
              : item.projectable
                ? 'BUILD MAP'
                : item.workspace_available ? 'NO PLAY JOURNEY' : 'NO EVIDENCE'
        const coverage = item.graph_ready
          ? `${item.nodes} sites · ${item.edges} routes`
          : item.projectable
            ? 'projection available'
            : item.workspace_available
              ? 'Rote workspace · no Play capture'
              : 'workspace unavailable'
        return <button key={item.id} disabled={unavailable} className={`workspace-card${workspace === item.id ? ' active' : ''}${item.journey_mode === 'live' && item.active_recently ? ' live' : ''}`} onClick={() => choose(item)}>
        <i /><span>{item.intent}</span>
        <small><b>{stateLabel}</b><em>{coverage}</em></small>
      </button>})}</div>
      <p>The atlas is a semantic projection. Every canonical node, edge, command and evidence reference remains preserved below it.</p>
    </aside>
    <aside className={`landmark-panel${showEvidencePanel ? ' visible' : ''}`}>
      {showEvidencePanel && <>
        <div className="panel-heading"><span>{interaction ? `INTERACTION @${interaction.sequence}` : `DISTRICT ${String(chapter.order + 1).padStart(2, '0')}`}</span><button onClick={() => setSelected(null)}>×</button></div>
        <span className="kind">{KIND_LABEL[presentedKind] || presentedKind}</span>
        <h1>{interaction ? interaction.capability?.label || interaction.operation : chapter.title}</h1>
        <p>{interaction ? `${interaction.operation} · situated at ${chapter.title}` : chapter.detail}</p>
        <div className="meaning"><strong>WHY THIS STEP EXISTS</strong><span>{MAP_MEANING[presentedKind] || 'Advances the requested outcome while preserving evidence.'}</span></div>
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
    {mode === 'follow' && story && interactions && !isTutorial && <div className="follow-instruments">
      <JourneyGuide story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} onOpen={selectVantage} onNavigate={jumpToChapter} />
      {!showEvidencePanel && <ModelLiveCounter story={story} interactions={interactions} replay={replay} playing={playing} live={liveActivity || trackingLive} />}
    </div>}
    {mode !== 'follow' && story && interactions && !isTutorial && (playing || selected?.siteId) && <div className="atlas-instruments">
      <ModelLiveCounter story={story} interactions={interactions} replay={replay} playing={playing} live={liveActivity || trackingLive} siteId={playing ? '' : selected?.siteId} />
    </div>}
    {mode === 'follow' && story && tutorial && <TutorialExperience key={story.journey_key} tutorial={tutorial} story={story} interactions={interactions} replay={replay} playing={playing} entryReferenceActive={tutorialEntryModelActive} onBegin={() => { setWorldModelOpen(false); jumpToChapter(0); togglePlayback() }} onChooseWorkspace={() => setJourneysOpen(true)} onOpenWorldModel={() => setWorldModelOpen(true)} />}
    {mode === 'follow' && story && interactions && !isTutorial && !showEvidencePanel && <CapabilityRail story={story} interactions={interactions} replay={replay} onJump={jumpToChapter} />}
    <WorldModel open={worldModelOpen} onToggle={() => setWorldModelOpen((value) => !value)} highlightKind={isTutorial ? currentReplayChapter?.kind : ''} tutorial={isTutorial} />
    <Telemetry story={story} open={telemetryOpen} onToggle={() => setTelemetryOpen((value) => !value)} />
    <footer>
      <button onClick={() => setJourneysOpen((value) => !value)}>☷ JOURNEYS</button>
      <span>{story ? `${story.audit.canonical_nodes} STAGES · ${interactions?.total || 0} INTERACTIONS · GEN ${story.graph_generation}` : 'WAITING FOR GRAPH'}</span>
      <div className="replay">
        <div className="replay-controls">
          <button className={playing ? 'playing' : frozen ? 'frozen' : ''} onClick={togglePlayback}>{playing ? 'Ⅱ FREEZE' : frozen ? '▶ RESUME' : '▶ PLAY'}</button>
          {liveCapture && <button className={`live-track${trackingLive ? ' active' : ''}`} disabled={story?.state !== 'active'} onClick={toggleLiveTracking} title="Follow new call sites as calm snapshots arrive">{trackingLive ? '● LIVE HEAD' : '○ TRACK LIVE'}</button>}
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
              return <button
                key={item.id}
                className={itemIndex === replayChapter ? 'current' : itemIndex < replayChapter ? 'reached' : ''}
                style={{left: `${itemIndex / Math.max(1, story.chapters.length - 1) * 100}%`}}
                onClick={() => jumpToChapter(itemIndex)}
                aria-label={`Freeze at stage ${number}: ${kind}, ${item.title}`}
                data-kind={item.kind || 'phase'}
                data-tooltip={`${number} · ${kind} · ${item.title}${hiddenUntilNext ? ` · ${hiddenUntilNext} intermediate stage${hiddenUntilNext === 1 ? '' : 's'}` : ''}`}
              />
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
      <span className="footer-message">{trackingLive ? `TRACKING LIVE HEAD · NEXT SNAPSHOT ${String(snapshotCountdown).padStart(2, '0')}s` : playing ? `PLAYING SNAPSHOT · ${message}` : frozen ? `FROZEN VANTAGE · ${message}` : lastSnapshotAt && liveCapture ? `READY TO PLAY FROM HERE · SNAPSHOT ${new Date(lastSnapshotAt).toLocaleTimeString()} · ${message}` : `READY TO PLAY · ${message}`}</span>
    </footer>
  </main>
}
