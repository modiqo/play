import {useCallback, useEffect, useRef, useState} from 'react'
import {api} from './api.js'

export function useJourneyRuntime() {
  const [index, setIndex] = useState(null)
  const [workspace, setWorkspace] = useState('')
  const [story, setStory] = useState(null)
  const [scene, setScene] = useState(null)
  const [interactions, setInteractions] = useState(null)
  const [selected, setSelected] = useState(null)
  const [exchange, setExchange] = useState(null)
  const [replay, setReplay] = useState(1)
  const [playing, setPlaying] = useState(false)
  const [observing, setObserving] = useState(true)
  const [snapshotCountdown, setSnapshotCountdown] = useState(10)
  const [lastSnapshotAt, setLastSnapshotAt] = useState(null)
  const [fitSignal, setFitSignal] = useState(0)
  const [mode, setMode] = useState('follow')
  const [message, setMessage] = useState('Loading journeys')
  const [loadError, setLoadError] = useState('')
  const [journeysOpen, setJourneysOpen] = useState(false)
  const [telemetryOpen, setTelemetryOpen] = useState(false)
  const [worldModelOpen, setWorldModelOpen] = useState(false)
  const playback = useRef(null)

  const loadIndex = useCallback(async () => {
    const response = await fetch(api('/api/workspaces'), {cache: 'no-store'})
    if (!response.ok) throw new Error(`Workspace index unavailable (${response.status})`)
    const value = await response.json()
    setLoadError('')
    setIndex(value)
    setWorkspace((current) => current || value.selected_id || value.workspaces[0]?.id || '')
    return value
  }, [])

  const loadJourney = useCallback(async (id, quiet = false) => {
    if (!quiet) setMessage('Loading journey map')
    const [storyResponse, sceneResponse, interactionResponse] = await Promise.all([
      fetch(api('/api/story', {workspace: id}), {cache: 'no-store'}),
      fetch(api('/api/scene', {workspace: id}), {cache: 'no-store'}),
      fetch(api('/api/interactions', {workspace: id}), {cache: 'no-store'}),
    ])
    if (!storyResponse.ok || !sceneResponse.ok || !interactionResponse.ok) throw new Error('Journey map is unavailable')
    const [nextStory, nextScene, nextInteractions] = await Promise.all([storyResponse.json(), sceneResponse.json(), interactionResponse.json()])
    setStory(nextStory)
    setScene(nextScene)
    setInteractions(nextInteractions)
    setSelected((current) => nextStory.chapters.some((chapter) => chapter.id === current?.siteId) ? current : null)
    if (!quiet) setReplay(nextStory.state === 'active' ? 1 : 0)
    if (!quiet) setObserving(true)
    if (!quiet) setMessage(nextStory.state === 'active' ? 'Live journey connected' : 'Recorded journey loaded')
    setLastSnapshotAt(Date.now())
  }, [])

  async function choose(item) {
    try {
      setPlaying(false)
      setObserving(true)
      playback.current = null
      setSelected(null)
      setMode('follow')
      if (!item.graph_ready && !item.projectable) {
        setMessage('This historical capture no longer has its Rote workspace evidence, so no map can be projected')
        return
      }
      if (!item.graph_ready) {
        setMessage('Projecting first journey snapshot')
        const start = await fetch(api('/api/project', {workspace: item.id}), {method: 'POST', cache: 'no-store'})
        if (!start.ok && start.status !== 202) throw new Error(`Projection could not start (${start.status})`)
        const deadline = Date.now() + 10000
        let ready = false
        while (Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 240))
          const next = await loadIndex()
          ready = Boolean(next.workspaces.find((candidate) => candidate.id === item.id)?.graph_ready)
          if (ready) break
        }
        if (!ready) throw new Error('First map is still building; select it again in a moment')
      }
      await loadJourney(item.id)
      setWorkspace(item.id)
      setJourneysOpen(false)
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
  }

  useEffect(() => {
    loadIndex().catch((error) => {
      setMessage(error.message)
      setLoadError(error.message)
    })
  }, [loadIndex])
  useEffect(() => {
    if (!workspace) return undefined
    loadJourney(workspace).catch((error) => setMessage(error.message))
    const events = new EventSource(api('/api/events', {workspace}))
    events.addEventListener('journey', () => {
      loadJourney(workspace, true).catch(() => {})
      loadIndex().catch(() => {})
      setSnapshotCountdown(10)
    })
    events.onerror = () => setMessage('Reconnecting to live journey')
    return () => events.close()
  }, [loadIndex, loadJourney, workspace])

  useEffect(() => {
    if (!workspace) return undefined
    let remaining = 10
    setSnapshotCountdown(remaining)
    const interval = window.setInterval(() => {
      remaining -= 1
      if (remaining <= 0) {
        remaining = 10
        loadIndex()
          .then((nextIndex) => {
            const currentWorkspace = nextIndex.workspaces.find((item) => item.id === workspace)
            if (currentWorkspace?.capture_state === 'active') {
              return loadJourney(workspace, true)
            }
            return undefined
          })
          .catch(() => {})
      }
      setSnapshotCountdown(remaining)
    }, 1000)
    return () => window.clearInterval(interval)
  }, [loadIndex, loadJourney, workspace])

  useEffect(() => {
    if (!selected?.sequence || !workspace) {
      setExchange(null)
      return undefined
    }
    const abort = new AbortController()
    setExchange({loading: true})
    fetch(api('/api/exchange', {workspace, sequence: selected.sequence}), {cache: 'no-store', signal: abort.signal})
      .then((response) => {
        if (!response.ok) throw new Error(`Evidence unavailable (${response.status})`)
        return response.json()
      })
      .then(setExchange)
      .catch((error) => { if (error.name !== 'AbortError') setExchange({error: error.message}) })
    return () => abort.abort()
  }, [selected?.sequence, workspace])

  useEffect(() => {
    if (!selected?.sequence) return
    setTelemetryOpen(false)
    setWorldModelOpen(false)
  }, [selected?.sequence])

  useEffect(() => {
    if (!playing || !story) return undefined
    let frame = 0
    const count = story.chapters.length
    const intervals = Math.max(1, count - 1)
    const dwellMs = 2800
    const travelMs = 4200
    const cycleMs = dwellMs + travelMs
    const startingUnits = (playback.current?.from || 0) * intervals
    const startingStage = Math.min(intervals, Math.floor(startingUnits))
    const startingFraction = startingUnits - startingStage
    const timelineOffset = startingStage * cycleMs + (startingFraction > .001 ? dwellMs + startingFraction * travelMs : 0)
    const finishAt = intervals * cycleMs + dwellMs
    const tick = (time) => {
      const state = playback.current
      if (!state) return
      const timeline = timelineOffset + time - state.started
      const stage = Math.min(intervals, Math.floor(timeline / cycleMs))
      const withinStage = timeline - stage * cycleMs
      const rawTravel = stage >= intervals ? 0 : Math.max(0, Math.min(1, (withinStage - dwellMs) / travelMs))
      const travel = rawTravel * rawTravel * (3 - 2 * rawTravel)
      const progress = Math.min(1, (stage + travel) / intervals)
      setReplay(progress)
      if (timeline >= finishAt) {
        playback.current = null
        setPlaying(false)
        setObserving(true)
        setMessage('Journey traversal complete')
        return
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, story])

  function togglePlayback() {
    if (playing) {
      playback.current = null
      setPlaying(false)
      setObserving(true)
      setMessage('Vantage frozen · all local structures are available for inspection')
      return
    }
    const from = replay >= .999 ? 0 : replay
    setSelected(null)
    setObserving(false)
    setReplay(from)
    setFitSignal((value) => value + 1)
    playback.current = {from, started: performance.now()}
    setPlaying(true)
    setMessage('Following the agent trajectory')
  }

  function jumpToChapter(index) {
    setPlaying(false)
    setObserving(true)
    playback.current = null
    setSelected(null)
    const denominator = Math.max(1, (story?.chapters.length || 1) - 1)
    setReplay(index / denominator)
    setMessage(`Jumped to stage ${index + 1}`)
  }

  const selectVantage = useCallback((value) => {
    if (value) {
      playback.current = null
      setPlaying(false)
      setObserving(true)
      const vantageIndex = story?.chapters.findIndex((chapter) => chapter.id === value.siteId) ?? -1
      if (vantageIndex >= 0) {
        setReplay(vantageIndex / Math.max(1, story.chapters.length - 1))
      }
      setMessage(value.sequence ? `Inspecting interaction @${value.sequence}` : 'Situational awareness opened')
    }
    setSelected(value)
  }, [story])

  function freezeAtProgress(value) {
    playback.current = null
    setPlaying(false)
    setObserving(true)
    setReplay(value)
    setMessage('Vantage frozen · inspect the illuminated structures')
  }

  return {
    index, workspace, story, scene, interactions, selected, setSelected, exchange,
    replay, playing, observing, snapshotCountdown, lastSnapshotAt, fitSignal, setFitSignal,
    mode, setMode, message, loadError, journeysOpen, setJourneysOpen,
    telemetryOpen, setTelemetryOpen, worldModelOpen, setWorldModelOpen,
    choose, togglePlayback, jumpToChapter, selectVantage, freezeAtProgress,
  }
}

