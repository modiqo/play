import React from 'react'
import Cartography from './atlas.jsx'
import {formatNumber} from './format.js'
import {CapabilityRail, JourneyGuide, Telemetry, WorldModel} from './panels.jsx'
import {KIND_LABEL, MAP_MEANING} from './semantics.js'
import {useJourneyRuntime} from './use-journey-runtime.js'
import JourneyWorld from './world.jsx'

export default function App() {
  const {
    index, workspace, story, scene, interactions, selected, setSelected, exchange,
    replay, playing, observing, snapshotCountdown, lastSnapshotAt, fitSignal, setFitSignal,
    mode, setMode, message, loadError, journeysOpen, setJourneysOpen,
    telemetryOpen, setTelemetryOpen, worldModelOpen, setWorldModelOpen,
    choose, togglePlayback, jumpToChapter, selectVantage, freezeAtProgress,
  } = useJourneyRuntime()
  const chapter = story?.chapters.find((item) => item.id === selected?.siteId)
  const interaction = selected?.sequence
    ? interactions?.sites?.[selected.siteId]?.find((item) => item.sequence === selected.sequence)
    : null
  const selectedWorkspace = index?.workspaces.find((item) => item.id === workspace)
  const liveCapture = selectedWorkspace?.capture_state === 'active'
  const liveActivity = Boolean(liveCapture && selectedWorkspace?.active_recently)
  const status = liveActivity ? 'LIVE' : liveCapture ? 'LIVE · IDLE' : 'HISTORY'
  const replayChapter = story ? Math.min(story.chapters.length - 1, Math.floor(replay * Math.max(1, story.chapters.length - 1) + .001)) : 0
  const frozen = mode === 'follow' && observing && !playing

  const showEvidencePanel = chapter && (mode !== 'follow' || interaction)

  return <main className={`dark mode-${mode}${frozen ? ' is-frozen' : ''}`}>
    <section className="atlas-stage">
      {story && scene && interactions
        ? mode === 'follow'
          ? <JourneyWorld story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} selected={selected} onSelect={selectVantage} />
          : <Cartography story={story} scene={scene} interactions={interactions} replay={replay} playing={playing} audit={mode === 'audit'} selected={selected} onSelect={setSelected} fitSignal={fitSignal} />
        : loadError
          ? <div className="loading failed"><strong>JOURNEY CONNECTION LOST</strong><span>{loadError}</span><code>./scripts/bin/play-journey view --active</code></div>
          : <div className="loading"><i />CONSTRUCTING JOURNEY ATLAS</div>}
    </section>
    <header>
      <button className="brand" onClick={() => setJourneysOpen((value) => !value)}><strong>PLAY CARTOGRAPHY</strong><small>{mode === 'follow' ? 'JOURNEY FOLLOW' : mode === 'audit' ? 'EVIDENCE AUDIT' : 'JOURNEY ATLAS'}</small></button>
      <div className={`header-title${liveActivity ? ' live' : ''}`}><i />{status}{liveCapture && <b>NEXT SNAPSHOT {String(snapshotCountdown).padStart(2, '0')}s</b>}<span>{story?.outcome || 'Captured exploration'}</span></div>
      <div className="header-actions">
        <button className={mode === 'follow' ? 'active' : ''} onClick={() => { setMode('follow'); setSelected(null) }}>FOLLOW</button>
        <button className={mode === 'atlas' ? 'active' : ''} onClick={() => { setMode('atlas'); setSelected(null); setFitSignal((value) => value + 1) }}>ATLAS</button>
        <button className={mode === 'audit' ? 'active' : ''} onClick={() => { setMode('audit'); setSelected(null); setFitSignal((value) => value + 1) }}>AUDIT</button>
        {mode !== 'follow' && <button onClick={() => setFitSignal((value) => value + 1)}>FIT</button>}
      </div>
    </header>
    <aside className={`journey-drawer${journeysOpen ? ' open' : ''}`}>
      <div className="panel-heading"><span>JOURNEY ARCHIVE</span><button onClick={() => setJourneysOpen(false)}>×</button></div>
      <div className="workspace-list">{index?.workspaces.map((item) => {
        const unavailable = !item.graph_ready && !item.projectable
        const stateLabel = workspace === item.id
          ? item.active_recently ? 'VIEWING · LIVE' : item.capture_state === 'active' ? 'VIEWING · IDLE' : 'VIEWING'
          : item.graph_ready && item.active_recently
            ? 'LIVE'
            : item.graph_ready && item.capture_state === 'active'
              ? 'IDLE'
            : item.graph_ready
              ? 'RECORDED'
              : item.projectable
                ? 'BUILD MAP'
                : 'NO EVIDENCE'
        const coverage = item.graph_ready ? `${item.nodes} sites · ${item.edges} routes` : item.projectable ? 'projection available' : 'workspace unavailable'
        return <button key={item.id} disabled={unavailable} className={`workspace-card${workspace === item.id ? ' active' : ''}${item.active_recently ? ' live' : ''}`} onClick={() => choose(item)}>
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
            <dt>LATENCY</dt><dd>{formatNumber(interaction.duration_ms)} ms</dd><dt>TOKENS</dt><dd>{formatNumber(interaction.tokens)}</dd>
            <dt>AVOIDED</dt><dd>{formatNumber(interaction.tokens_saved)}</dd>
            {interaction.provider && <><dt>PROVIDER</dt><dd>{interaction.provider}</dd></>}
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
            <dt>STATE</dt><dd>{chapter.status}</dd><dt>TOWERS</dt><dd>{interactions?.sites?.[chapter.id]?.length || 0}</dd>
            <dt>LATENCY</dt><dd>{formatNumber(chapter.telemetry.duration_ms)} ms</dd><dt>TOKENS</dt><dd>{formatNumber(chapter.telemetry.payload_tokens)}</dd>
            <dt>AVOIDED</dt><dd>{formatNumber(chapter.telemetry.tokens_saved)}</dd>
            {chapter.provider && <><dt>PROVIDER</dt><dd>{chapter.provider}</dd></>}
          </dl>
          <details><summary>EVIDENCE REFERENCES</summary><pre>{Object.entries(chapter.evidence).filter(([, values]) => values?.length).map(([key, values]) => `${key}: ${values.join(', ')}`).join('\n') || 'No opaque evidence references recorded'}</pre></details>
        </>}
      </>}
    </aside>
    {mode === 'follow' && story && interactions && <JourneyGuide story={story} interactions={interactions} replay={replay} playing={playing} frozen={frozen} onOpen={selectVantage} onNavigate={jumpToChapter} />}
    {mode === 'follow' && story && interactions && <CapabilityRail story={story} interactions={interactions} replay={replay} onJump={jumpToChapter} />}
    <WorldModel open={worldModelOpen} onToggle={() => setWorldModelOpen((value) => !value)} />
    <Telemetry story={story} open={telemetryOpen} onToggle={() => setTelemetryOpen((value) => !value)} />
    <footer>
      <button onClick={() => setJourneysOpen((value) => !value)}>☷ JOURNEYS</button>
      <span>{story ? `${story.audit.canonical_nodes} STAGES · ${interactions?.total || 0} INTERACTIONS · GEN ${story.graph_generation}` : 'WAITING FOR GRAPH'}</span>
      <div className="replay"><button className={playing ? 'playing' : frozen ? 'frozen' : ''} onClick={togglePlayback}>{playing ? 'Ⅱ FREEZE' : frozen ? '▶ RESUME' : '▶ PLAY'}</button><div className="replay-track"><input aria-label="Journey replay" type="range" min="0" max="1" step="0.002" value={replay} onChange={(event) => { freezeAtProgress(Number(event.target.value)) }} /><div className="chapter-markers">{story?.chapters.map((item, itemIndex) => <button key={item.id} className={itemIndex === replayChapter ? 'current' : itemIndex < replayChapter ? 'reached' : ''} style={{left: `${itemIndex / Math.max(1, story.chapters.length - 1) * 100}%`}} onClick={() => jumpToChapter(itemIndex)} aria-label={`Freeze at stage ${itemIndex + 1}: ${item.title}`} />)}</div></div><em>{story ? `${replayChapter + 1}/${story.chapters.length}` : '0/0'}</em></div>
      <span className="footer-message">{frozen ? `FROZEN VANTAGE · ${message}` : lastSnapshotAt && liveCapture ? `SNAPSHOT ${new Date(lastSnapshotAt).toLocaleTimeString()} · ${message}` : message}</span>
    </footer>
  </main>
}
