import React from 'react'
import Cartography from './atlas.jsx'
import {formatNumber} from './format.js'
import {CapabilityRail, JourneyGuide, Telemetry, TutorialExperience, WorldModel} from './panels.jsx'
import {KIND_LABEL, MAP_MEANING} from './semantics.js'
import {useJourneyRuntime} from './use-journey-runtime.js'
import JourneyWorld from './world.jsx'

export default function App() {
  const {
    index, workspace, story, scene, interactions, tutorial, selected, setSelected, exchange,
    replay, playing, observing, snapshotCountdown, lastSnapshotAt, fitSignal, setFitSignal,
    mode, setMode, message, loadError, journeysOpen, setJourneysOpen,
    telemetryOpen, setTelemetryOpen, worldModelOpen, setWorldModelOpen, refreshing,
    choose, refreshWorkspaces, togglePlayback, jumpToChapter, selectVantage, freezeAtProgress,
  } = useJourneyRuntime()
  const chapter = story?.chapters.find((item) => item.id === selected?.siteId)
  const interaction = selected?.sequence
    ? interactions?.sites?.[selected.siteId]?.find((item) => item.sequence === selected.sequence)
    : null
  const selectedWorkspace = index?.workspaces.find((item) => item.id === workspace)
  const liveCapture = selectedWorkspace?.journey_mode === 'live'
  const liveActivity = Boolean(liveCapture && selectedWorkspace?.active_recently)
  const recalled = story?.origin?.kind === 'recalled_play'
  const isTutorial = story?.origin?.kind === 'tutorial'
  const status = isTutorial ? 'START HERE' : recalled ? 'RECALLED PLAY' : liveActivity ? 'LIVE · UPDATING' : liveCapture ? 'LIVE · QUIET' : 'RECORDED'
  const replayChapter = story ? Math.min(story.chapters.length - 1, Math.floor(replay * Math.max(1, story.chapters.length - 1) + .001)) : 0
  const currentReplayChapter = story?.chapters[replayChapter]
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

  return <main className={`dark mode-${mode}${frozen ? ' is-frozen' : ''}${isTutorial ? ' tutorial-guided' : ''}${tutorialEntryModelActive ? ' world-model-active' : ''}`}>
    <section className="atlas-stage">
      {story && scene && interactions
        ? mode === 'follow'
          ? <JourneyWorld key={`follow:${story.journey_key}`} story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} selected={selected} onSelect={selectVantage} />
          : <Cartography key={`${mode}:${story.journey_key}`} story={story} scene={scene} interactions={interactions} replay={replay} playing={playing} audit={mode === 'audit'} selected={selected} onSelect={setSelected} fitSignal={fitSignal} />
        : loadError
          ? <div className="loading failed"><strong>JOURNEY CONNECTION LOST</strong><span>{loadError}</span><code>play-journey view --active</code></div>
          : <div className="loading"><i />CONSTRUCTING JOURNEY ATLAS</div>}
    </section>
    <header>
      <button className="brand" onClick={() => setJourneysOpen((value) => !value)}><strong>PLAY CARTOGRAPHY</strong><small>{mode === 'follow' ? 'JOURNEY FOLLOW' : mode === 'audit' ? 'EVIDENCE AUDIT' : 'JOURNEY ATLAS'}</small></button>
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
        <button className={mode === 'audit' ? 'active' : ''} onClick={() => changeMode('audit')}>AUDIT</button>
        {mode !== 'follow' && <button onClick={() => setFitSignal((value) => value + 1)}>FIT</button>}
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
        <span className="kind">{KIND_LABEL[chapter.kind] || chapter.kind}</span>
        <h1>{chapter.title}</h1><p>{chapter.detail}</p>
        <div className="meaning"><strong>WHY THIS STEP EXISTS</strong><span>{MAP_MEANING[chapter.kind] || 'Advances the requested outcome while preserving evidence.'}</span></div>
        {interaction ? <>
          <dl>
            <dt>OPERATION</dt><dd>{interaction.operation}</dd><dt>STATE</dt><dd>{interaction.status}</dd>
            <dt>ACCESS</dt><dd>{(interaction.effect_profile?.posture || interaction.effect || 'unknown').toUpperCase()}</dd>
            <dt>SCOPE</dt><dd>{interaction.effect_profile?.scopes?.join(' · ') || 'not declared'}</dd>
            <dt>BASIS</dt><dd>{interaction.effect_profile?.source?.replaceAll('_', ' ') || 'legacy projection'}</dd>
            <dt>LATENCY</dt><dd>{formatNumber(interaction.duration_ms)} ms</dd><dt>TOKENS</dt><dd>{formatNumber(interaction.tokens)}</dd>
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
    {mode === 'follow' && story && interactions && !isTutorial && <JourneyGuide story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} onOpen={selectVantage} onNavigate={jumpToChapter} />}
    {mode === 'follow' && story && tutorial && <TutorialExperience key={story.journey_key} tutorial={tutorial} story={story} interactions={interactions} replay={replay} playing={playing} entryReferenceActive={tutorialEntryModelActive} onBegin={() => { setWorldModelOpen(false); jumpToChapter(0); togglePlayback() }} onChooseWorkspace={() => setJourneysOpen(true)} onOpenWorldModel={() => setWorldModelOpen(true)} />}
    {mode === 'follow' && story && interactions && !isTutorial && !showEvidencePanel && <CapabilityRail story={story} interactions={interactions} replay={replay} onJump={jumpToChapter} />}
    <WorldModel open={worldModelOpen} onToggle={() => setWorldModelOpen((value) => !value)} highlightKind={isTutorial ? currentReplayChapter?.kind : ''} tutorial={isTutorial} />
    <Telemetry story={story} open={telemetryOpen} onToggle={() => setTelemetryOpen((value) => !value)} />
    <footer>
      <button onClick={() => setJourneysOpen((value) => !value)}>☷ JOURNEYS</button>
      <span>{story ? `${story.audit.canonical_nodes} STAGES · ${interactions?.total || 0} INTERACTIONS · GEN ${story.graph_generation}` : 'WAITING FOR GRAPH'}</span>
      <div className="replay">
        <button className={playing ? 'playing' : frozen ? 'frozen' : ''} onClick={togglePlayback}>{playing ? 'Ⅱ FREEZE' : frozen ? '▶ RESUME' : '▶ PLAY'}</button>
        <div className="replay-track" style={{'--progress': `${replay * 100}%`}}>
          <input aria-label="Journey replay" type="range" min="0" max="1" step="0.002" value={replay} onChange={(event) => { freezeAtProgress(Number(event.target.value)) }} />
          <div className="chapter-markers">
            {story?.chapters.map((item, itemIndex) => {
              const number = String(itemIndex + 1).padStart(2, '0')
              const kind = (KIND_LABEL[item.kind] || item.kind || 'stage').toUpperCase()
              return <button
                key={item.id}
                className={itemIndex === replayChapter ? 'current' : itemIndex < replayChapter ? 'reached' : ''}
                style={{left: `${itemIndex / Math.max(1, story.chapters.length - 1) * 100}%`}}
                onClick={() => jumpToChapter(itemIndex)}
                aria-label={`Freeze at stage ${number}: ${kind}, ${item.title}`}
                data-tooltip={`${number} · ${kind} · ${item.title}`}
              />
            })}
          </div>
        </div>
        <em className="replay-position">
          {story
            ? <><b>{String(replayChapter + 1).padStart(2, '0')}</b><span>/ {String(story.chapters.length).padStart(2, '0')} · {(KIND_LABEL[currentReplayChapter?.kind] || currentReplayChapter?.kind || 'stage').toUpperCase()}</span></>
            : '00 / 00'}
        </em>
      </div>
      <span className="footer-message">{playing ? `PLAYING · ${message}` : frozen ? `FROZEN VANTAGE · ${message}` : lastSnapshotAt && liveCapture ? `READY TO PLAY · SNAPSHOT ${new Date(lastSnapshotAt).toLocaleTimeString()} · ${message}` : `READY TO PLAY · ${message}`}</span>
    </footer>
  </main>
}
