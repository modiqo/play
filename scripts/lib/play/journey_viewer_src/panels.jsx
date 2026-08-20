import React, {useEffect, useRef, useState} from 'react'
import {formatNumber} from './format.js'
import {KIND_LABEL, MAP_MEANING, MODALITY_VOCABULARY, WORLD_MODEL_KINDS, WORLD_ROLE, WORLD_STORY, worldSpec} from './semantics.js'

export function Telemetry({story, open, onToggle}) {
  const latency = Number(story?.telemetry.duration_ms || 0)
  const tokens = Number(story?.telemetry.payload_tokens || 0)
  const avoided = Number(story?.telemetry.tokens_saved || 0)
  const denominator = Math.max(1, tokens + avoided)
  return <section className={`telemetry${open ? ' open' : ''}`}>
    <button className="telemetry-toggle" onClick={onToggle} aria-expanded={open}><span>TELEMETRY</span><strong>{formatNumber(latency)} ms · {formatNumber(tokens)} tok</strong><i>{open ? '×' : '+'}</i></button>
    <div className="telemetry-body">
      <div className="metric"><span>LATENCY</span><strong>{formatNumber(latency)}<small> ms</small></strong><i style={{'--fill': `${Math.min(100, Math.log10(latency + 1) * 24)}%`}} /></div>
      <div className="metric"><span>CONSUMED</span><strong>{formatNumber(tokens)}</strong><i style={{'--fill': `${tokens / denominator * 100}%`}} /></div>
      <div className="metric saved"><span>AVOIDED</span><strong>{formatNumber(avoided)}</strong><i style={{'--fill': `${avoided / denominator * 100}%`}} /></div>
    </div>
  </section>
}

const WHY = {
  intent: 'Establish the requested outcome before choosing tools or taking effects.',
  decision: 'Choose the next route while preserving the user’s constraints and authority.',
  capability: 'Prepare the capability needed to advance the outcome.',
  authority: 'Confirm that the next effect is allowed before it occurs.',
  phase: 'Group related commands into one understandable stage of the outcome.',
  effect: 'Perform outcome-bearing work through the selected capability.',
  evidence: 'Check the observed result before treating the work as complete.',
  blocker: 'Expose what prevented progress instead of hiding it behind retries.',
  recovery: 'Re-enter the useful path with verified corrective evidence.',
  milestone: 'Record a meaningful boundary in the completed journey.',
  artifact: 'Turn the verified work into something the user can use.',
  play_candidate: 'Compress the successful trajectory into a reusable procedure.',
  play: 'Make the verified procedure available for future runs.',
}

export function JourneyGuide({story, interactions, replay, playing, frozen, onOpen, onNavigate}) {
  const [compact, setCompact] = useState(false)
  if (!story?.chapters?.length) return null
  const playbackIndex = Math.max(0, Math.min(story.chapters.length - 1, Math.ceil(replay * story.chapters.length) - 1))
  const liveIndex = Math.max(0, story.chapters.findIndex((chapter) => chapter.id === story.current_chapter))
  const restingIndex = story.state === 'active' ? liveIndex : story.chapters.length - 1
  const index = playing || replay < .999 ? playbackIndex : restingIndex
  const current = story.chapters[index]
  const next = story.chapters[index + 1]
  const records = interactions?.sites?.[current.id] || []
  const capabilities = [...new Set(records.map((record) => capabilityLabel(record)))]
  const effects = [...new Set(records.map((record) => record.effect_profile?.posture || record.effect).filter(Boolean))]
  const latency = records.reduce((sum, record) => sum + Number(record.duration_ms || 0), 0)
  const consumed = records.reduce((sum, record) => sum + Number(record.tokens || 0), 0)
  const succeeded = records.filter((record) => record.status === 'succeeded').length
  const navigate = (event, target) => { event.stopPropagation(); onNavigate(target) }
  return <aside className={`journey-guide${frozen ? ' frozen' : ''}${compact ? ' compact' : ''}`} onClick={() => !compact && onOpen({siteId: current.id, sequence: null})}>
    <div className="guide-kicker"><i />{playing ? 'TRAVERSING' : frozen ? 'FROZEN VANTAGE' : story.state === 'active' ? 'NOW' : 'RECORDED JOURNEY'}<span>{String(index + 1).padStart(2, '0')} / {String(story.chapters.length).padStart(2, '0')}</span><button className="guide-compact-toggle" onClick={(event) => { event.stopPropagation(); setCompact((value) => !value) }} aria-label={compact ? 'Expand vantage controls' : 'Minimize vantage controls'} title={compact ? 'Expand' : 'Minimize'}>{compact ? '+' : '−'}</button></div>
    <h1>{current.title}</h1>
    {!compact && <>
    {story.route?.mode === 'known' && <div className="known-route"><strong>RECALLED PLAY</strong><span>{story.origin?.exact_reference || 'Verified reusable procedure'} · workflow and capability discovery were not repeated.</span></div>}
    <p><strong>{KIND_LABEL[current.kind] || current.kind} → {WORLD_ROLE[current.kind] || 'journey stage'}.</strong> {WORLD_STORY[current.kind] || WHY[current.kind] || 'Advance the requested outcome while preserving evidence.'}</p>
    {frozen && <div className="vantage-nudge"><strong>EXPLORE</strong><span>Drag or use arrow keys to look through 360°. Scroll to move forward or backward. Every illuminated callout opens that structure’s evidence.</span></div>}
    <dl>
      <dt>HAPPENED</dt><dd>{current.detail || current.title}</dd>
      <dt>STRUCTURES</dt><dd>{records.length ? `${records.length} illuminated · select any callout for evidence` : 'No tool interactions recorded at this vantage'}</dd>
      <dt>CAPABILITIES</dt><dd>{capabilities.length ? capabilities.join(' · ') : 'No tool capability used here'}</dd>
      <dt>EFFECT</dt><dd>{effects.length ? effects.join(' · ') : current.kind === 'effect' ? 'Outcome-bearing work' : 'No external effect recorded'}</dd>
      <dt>INSIGHT</dt><dd>{succeeded}/{records.length} interactions succeeded · {formatNumber(consumed)} tokens · {formatNumber(latency)} ms</dd>
      <dt>NEXT</dt><dd>{next?.title || 'Deliver the verified outcome'}</dd>
    </dl></>}
    {frozen && <nav className="vantage-navigation" aria-label="Frozen vantage navigation">
      <button disabled={index === 0} onClick={(event) => navigate(event, index - 1)}>{compact ? '← BACK' : '← PRIOR VANTAGE'}</button>
      {!compact && <span>ROUTE DIRECTION</span>}
      <button className="forward" disabled={index >= story.chapters.length - 1} onClick={(event) => navigate(event, index + 1)}>{compact ? 'NEXT →' : 'FORWARD →'}</button>
    </nav>}
    <div className="guide-progress"><i style={{width: `${Math.max(2, (index + 1) / story.chapters.length * 100)}%`}} /></div>
  </aside>
}

export function WorldModel({open, onToggle, highlightKind = '', tutorial = false}) {
  useEffect(() => {
    if (!open) return undefined
    const close = (event) => { if (event.key === 'Escape') onToggle() }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onToggle, open])
  return <>
    <button className="world-model-toggle" onClick={onToggle} aria-expanded={open}>◇ WORLD MODEL</button>
    <button className={`world-model-scrim${open ? ' open' : ''}`} onClick={onToggle} aria-label="Close the World Model and return" tabIndex={open ? 0 : -1} />
    <aside className={`world-model${open ? ' open' : ''}`}>
      <div className="panel-heading"><span>HOW TO READ THIS WORLD</span><button onClick={onToggle}>×</button></div>
      <p>The same spatial vocabulary repeats across every journey. Shape tells you what role a place has before you inspect its evidence.</p>
      <dl>{WORLD_MODEL_KINDS.map((kind, index) => <React.Fragment key={kind}>
        <dt style={{'--world-index': index}} className={kind === highlightKind ? 'world-model-current' : ''}><i className={`world-glyph ${worldSpec(kind).glyph}`} />{KIND_LABEL[kind]}</dt>
        <dd style={{'--world-index': index}} className={kind === highlightKind ? 'world-model-current' : ''}><strong>{WORLD_ROLE[kind]}</strong><span>{WORLD_STORY[kind]}</span><em>EXAMPLE · {worldSpec(kind).example}</em></dd>
      </React.Fragment>)}</dl>
      <div className="world-modalities">{Object.entries(MODALITY_VOCABULARY).map(([modality, value]) => <div key={modality}><i className={`modality-mark ${modality}`} /><span><strong>{value.label}</strong><small>{value.note}</small></span></div>)}</div>
      <div className="world-model-note"><i className="route-mark" />The amber route is the agent’s path. Structures around a stop are recorded interactions; select one to inspect its redacted exchange.</div>
      {tutorial && <button className="world-model-continue" onClick={onToggle}>RETURN →</button>}
    </aside>
  </>
}

export function TutorialNarration({tutorial, story, interactions, replay, journeyPlaying, onOpenWorldModel}) {
  const audio = useRef(null)
  const [voicePlaying, setVoicePlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [dismissedChapter, setDismissedChapter] = useState(null)
  const chapterCount = story?.chapters?.length || 0
  const index = Math.max(0, Math.min(Math.max(0, chapterCount - 1), Math.floor(replay * Math.max(1, chapterCount - 1) + .001)))
  const chapter = story?.chapters?.[index]
  const cue = tutorial?.cues?.find((item) => item.chapter === index) || tutorial?.cues?.[0]
  const spec = worldSpec(chapter?.kind)
  const records = interactions?.sites?.[chapter?.id] || []
  const source = tutorial?.audio?.voice
  useEffect(() => {
    if (!audio.current || !source || !cue) return
    if (Math.abs(audio.current.currentTime - Number(cue.start_seconds || 0)) > 3) audio.current.currentTime = Number(cue.start_seconds || 0)
  }, [cue?.chapter, source])
  if (!tutorial || !cue) return null
  const journeyUnits = replay * Math.max(1, chapterCount - 1)
  const travelling = journeyPlaying && Math.abs(journeyUnits - Math.round(journeyUnits)) > .006
  const dismissed = dismissedChapter === index
  const toggle = () => {
    if (!audio.current) return
    if (audio.current.paused) audio.current.play().then(() => setVoicePlaying(true)).catch(() => setVoicePlaying(false))
    else { audio.current.pause(); setVoicePlaying(false) }
  }
  if (dismissed) return <button className={`tutorial-explain-toggle${travelling ? ' is-travelling' : ''}`} onClick={() => setDismissedChapter(null)}>◇ EXPLAIN THIS VANTAGE</button>
  return <aside className={`tutorial-narration${travelling ? ' is-travelling' : ''}`} aria-live="polite">
    <div className="tutorial-narration-heading"><strong>{escapeTutorialLabel(cue.landmark)} · {escapeTutorialLabel(cue.primitive)}</strong><span>{String(index + 1).padStart(2, '0')} / {String(chapterCount).padStart(2, '0')}</span><button onClick={() => setDismissedChapter(index)} aria-label="Hide this explanation">×</button></div>
    <p className="tutorial-site-story">{cue.text}</p>
    <div className="tutorial-vantage-meaning">
      <p><strong>WORLD MODEL</strong><b>{spec.role} → {spec.label}</b><span>{spec.meaning}</span></p>
      <p><strong>LOCAL TOWERS</strong><b>{records.length} operation{records.length === 1 ? '' : 's'} at this vantage</b><span>They sit here because their evidence belongs to this step. Left→right is time; width is latency; height is tokens; depth is overlap.</span></p>
    </div>
    <nav><button onClick={onOpenWorldModel}>◇ OPEN WORLD MODEL</button>{source && <><button onClick={toggle}>{voicePlaying ? 'Ⅱ PAUSE VOICE' : '▶ PLAY VOICE'}</button><button onClick={() => { if (audio.current) audio.current.muted = !muted; setMuted(!muted) }}>{muted ? 'UNMUTE' : 'MUTE'}</button></>}</nav>
    <small>{journeyPlaying ? 'FOLLOWING · THE CARD CLEARS DURING TRAVEL' : 'FROZEN · SELECT AN AMBER TOWER OR @ NUMBER FOR REDACTED EVIDENCE'}</small>
    {source && <audio ref={audio} src={source} onEnded={() => setVoicePlaying(false)} />}
  </aside>
}

function escapeTutorialLabel(value) {
  return String(value || 'START HERE').toUpperCase()
}

function BionicText({children}) {
  return String(children).split(/(\s+)/).map((part, index) => {
    if (/^\s+$/.test(part)) return part
    const letters = part.match(/^([^A-Za-z0-9]*)([A-Za-z0-9]+)(.*)$/)
    if (!letters) return part
    const [, before, word, after] = letters
    const pivot = Math.max(1, Math.ceil(word.length * .48))
    return <React.Fragment key={`${part}:${index}`}>{before}<b>{word.slice(0, pivot)}</b>{word.slice(pivot)}{after}</React.Fragment>
  })
}

export function TutorialExperience({tutorial, story, interactions, replay, playing, entryReferenceActive, onBegin, onChooseWorkspace, onOpenWorldModel}) {
  const [entered, setEntered] = useState(false)
  if (!tutorial) return null
  if (!entered && entryReferenceActive) return null
  if (!entered) return <aside className="tutorial-intro">
    <span>START HERE · BEFORE YOU PRESS PLAY</span>
    <h1><BionicText>We do not anthropomorphize the agent. We embody it.</BionicText></h1>
    <p><BionicText>Most interfaces describe an agent from the outside, as if it were a person. This world does the opposite: it places you at the agent’s vantage point, inside the situation where it is operating.</BionicText></p>
    <p><BionicText>The world model begins with exact primitives, then paraphrases them as a spatial narrative you can experience.</BionicText></p>
    <p><BionicText>It turns an agent trace into a spatio-temporal experience: an homage to Doom, Wolfenstein 3D, and Halo, games that taught us a world through movement, landmarks, and time. We borrow that legibility, not their visual style.</BionicText></p>
    <p><BionicText>One example carries through the whole lesson: create a page in Notion, then use CALL, SHELL, and DRIVE to prepare it, create it, and verify it.</BionicText></p>
    <div className="tutorial-intro-actions"><button onClick={onOpenWorldModel}>◇ READ THE WORLD MODEL</button><button onClick={() => { setEntered(true); onBegin() }}>ENTER THE VANTAGE · PLAY JOURNEY →</button></div>
  </aside>
  if (replay >= .999 && !playing) return <aside className="tutorial-complete">
    <span>WORLD MODEL ORIENTED</span>
    <h1><BionicText>Now enter a real situation.</BionicText></h1>
    <p><BionicText>Choose a live or recorded Rote workspace. The same primitives, landmarks, capability lifecycle, and time grammar will repeat there.</BionicText></p>
    <button onClick={onChooseWorkspace}>CHOOSE A WORKSPACE →</button>
  </aside>
  return <TutorialNarration tutorial={tutorial} story={story} interactions={interactions} replay={replay} journeyPlaying={playing} onOpenWorldModel={onOpenWorldModel} />
}

const CAPABILITY_FAMILIES = {
  adapter: {label: MODALITY_VOCABULARY.call.label, note: MODALITY_VOCABULARY.call.note},
  proc: {label: MODALITY_VOCABULARY.shell.label, note: MODALITY_VOCABULARY.shell.note},
  browser: {label: MODALITY_VOCABULARY.drive.label, note: MODALITY_VOCABULARY.drive.note},
}

function fallbackCapability(record) {
  const operation = String(record.operation || 'local')
  const name = operation.split(/[\s.]/)[0] || 'local'
  const commandType = String(record.command_type || '')
  if (commandType.startsWith('Process') || commandType === 'StreamFollow') {
    return {family: 'proc', id: name, label: `${name} CLI`, interface: 'shell', mode: commandType === 'ProcessPtyRun' ? 'pty' : 'argv'}
  }
  // Old snapshots did not preserve the endpoint and MCP envelope required to
  // prove adapter/browser ownership. Keep them visible in evidence, but never
  // invent an equipped system from a provider label or operation wording.
  return {family: 'legacy', id: `legacy:${commandType}:${name}`, label: 'Legacy interaction', interface: 'unknown'}
}

function capabilityOf(record) {
  return record?.capability && typeof record.capability === 'object' ? record.capability : fallbackCapability(record)
}

function capabilityKey(record) {
  if (record?.capability_ref) return record.capability_ref
  const capability = capabilityOf(record)
  const unit = capability.family === 'browser' ? capability.primitive : capability.id
  return `${capability.family}:${unit || capability.label}`
}

function capabilityLabel(record) {
  const capability = capabilityOf(record)
  return capability.family === 'rote' ? capability.label : `${capability.label} · ${capability.interface}`
}

function effectPosture(entry) {
  const values = entry.postures
  if (values.has('unknown')) return 'UNKNOWN EFFECT'
  if (values.has('mixed') || values.has('read') && values.has('write')) return 'READ + WRITE'
  if (values.has('write')) return 'WRITE'
  if (values.has('read')) return 'READ'
  return 'UNKNOWN EFFECT'
}

function capabilityDetail(entry) {
  const {capability, modes, scopes, instance} = entry
  const access = `${effectPosture(entry)}${entry.destructive ? ' · DESTRUCTIVE' : ''}`
  const scope = [...scopes].map((value) => value.replaceAll('_', ' ')).join(' + ')
  const lifecycle = instance ? `INIT ${instance.initialization?.state || 'unknown'} · AUTH ${instance.authorization?.state || 'unknown'} · ${instance.state}` : ''
  if (capability.family === 'adapter') {
    const manifest = capability.manifest || {}
    return [lifecycle, access, scope, [...modes].join(' + '), manifest.spec_type, capability.transport].filter(Boolean).join(' · ')
  }
  if (capability.family === 'proc') return [lifecycle, access, scope, [...modes].join(' · ') || capability.mode || 'argv'].filter(Boolean).join(' · ')
  if (capability.family === 'browser') return [lifecycle, access, scope, capability.primitive || 'browse'].filter(Boolean).join(' · ')
  return [lifecycle, access, scope, capability.primitive || 'workspace'].filter(Boolean).join(' · ')
}

export function CapabilityRail({story, interactions, replay, onJump}) {
  const [expanded, setExpanded] = useState({adapter: true, proc: true, browser: true})
  const chapterIndex = Math.max(0, Math.min(story.chapters.length - 1, Math.floor(replay * Math.max(1, story.chapters.length - 1) + .001)))
  const currentChapter = story.chapters[chapterIndex]
  const activeRecords = (interactions?.sites?.[currentChapter?.id] || []).filter((record) => capabilityOf(record).family in CAPABILITY_FAMILIES)
  const activeKeys = new Set(activeRecords.map(capabilityKey))
  const instances = new Map((story.capabilities || []).map((instance) => [instance.id, instance]))
  const byKey = new Map()
  story.chapters.forEach((chapter, sourceIndex) => {
    for (const record of interactions?.sites?.[chapter.id] || []) {
      const capability = capabilityOf(record)
      if (!(capability.family in CAPABILITY_FAMILIES)) continue
      const key = capabilityKey(record)
      const existing = byKey.get(key)
      const entry = existing || {key, capability, instance: instances.get(record.capability_ref), firstIndex: sourceIndex, lastIndex: sourceIndex, count: 0, modes: new Set(), tools: new Set(), postures: new Set(), scopes: new Set(), destructive: false}
      entry.firstIndex = Math.min(entry.firstIndex, sourceIndex)
      entry.lastIndex = Math.max(entry.lastIndex, sourceIndex)
      entry.count += 1
      if (capability.phase) entry.modes.add(capability.phase)
      if (capability.mode) entry.modes.add(capability.mode)
      if (capability.tool) entry.tools.add(capability.tool)
      for (const operation of capability.operations || []) entry.tools.add(operation)
      const profile = record.effect_profile || {}
      entry.postures.add(profile.posture || record.effect || 'unknown')
      for (const scope of profile.scopes || []) entry.scopes.add(scope)
      entry.destructive ||= profile.destructive === true
      byKey.set(key, entry)
    }
  })
  const entries = [...byKey.values()].filter((entry) => entry.firstIndex <= chapterIndex).sort((left, right) => {
    const leftActive = activeKeys.has(left.key) ? 0 : 1
    const rightActive = activeKeys.has(right.key) ? 0 : 1
    return leftActive - rightActive || left.firstIndex - right.firstIndex || left.capability.label.localeCompare(right.capability.label)
  })
  const groups = Object.keys(CAPABILITY_FAMILIES).map((family) => ({family, entries: entries.filter((entry) => entry.capability.family === family)})).filter((group) => group.entries.length)
  const activeFamilies = groups.filter((group) => group.entries.some((entry) => activeKeys.has(entry.key))).map((group) => group.family).join(':')
  useEffect(() => {
    if (!activeFamilies) return
    setExpanded((current) => {
      const next = {...current}
      activeFamilies.split(':').forEach((family) => { next[family] = true })
      return next
    })
  }, [activeFamilies])
  return <aside className="capability-rail">
    <h2><i />USING CAPABILITIES <span>{activeKeys.size} ACTIVE</span></h2><p>The agent’s equipped systems in this situated environment</p>
    <div>{groups.length ? groups.map((group) => <section className={`capability-family ${group.family}`} key={group.family}>
      <button className="capability-family-toggle" onClick={() => setExpanded((current) => ({...current, [group.family]: !current[group.family]}))} aria-expanded={expanded[group.family]}>
        <span><strong>{CAPABILITY_FAMILIES[group.family].label}</strong><small>{CAPABILITY_FAMILIES[group.family].note}</small></span><b>{group.entries.length}</b><i>{expanded[group.family] ? '−' : '+'}</i>
      </button>
      {expanded[group.family] && <div className="capability-family-items">{group.entries.slice(0, 6).map((entry) => {
        const active = activeKeys.has(entry.key)
        const used = entry.firstIndex <= chapterIndex
        return <button key={entry.key} className={`capability-item ${active ? 'active' : used ? 'used' : ''}`} onClick={() => onJump(entry.firstIndex)} title={`${entry.capability.label}: ${[...entry.tools].join(', ')}`}>
          <i /><span><strong>{entry.capability.label}</strong><small>{capabilityDetail(entry)}</small></span><b>{active ? 'IN USE' : used ? 'USED' : 'AHEAD'}</b><em>{entry.count}</em>
        </button>
      })}</div>}
    </section>) : <div className="capability-empty"><strong>NO SYSTEM EQUIPPED</strong><span>The agent has fixed the intent but has not used an API, shell, or browser capability at this vantage.</span></div>}</div>
  </aside>
}
