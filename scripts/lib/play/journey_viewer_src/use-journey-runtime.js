import {useCallback, useEffect, useRef, useState} from 'react'
import {api, trackWorkspaceLocation, workspaceFromLocation} from './api.js'
import {useJourneyPlayback} from './use-journey-playback.js'
import {chooseWorkspace} from './workspace-choice.mjs'

export function useJourneyRuntime() {
  const [index, setIndex] = useState(null)
  const [workspace, setWorkspace] = useState('')
  const [story, setStory] = useState(null)
  const [scene, setScene] = useState(null)
  const [interactions, setInteractions] = useState(null)
  const [tutorial, setTutorial] = useState(null)
  const [selected, setSelected] = useState(null)
  const [exchange, setExchange] = useState(null)
  const [replay, setReplay] = useState(1)
  const [playing, setPlaying] = useState(false)
  const [observing, setObserving] = useState(false)
  const [snapshotCountdown, setSnapshotCountdown] = useState(10)
  const [lastSnapshotAt, setLastSnapshotAt] = useState(null)
  const [fitSignal, setFitSignal] = useState(0)
  const [mode, setMode] = useState('follow')
  const [message, setMessage] = useState('Loading journeys')
  const [loadError, setLoadError] = useState('')
  const [journeysOpen, setJourneysOpen] = useState(false)
  const [telemetryOpen, setTelemetryOpen] = useState(false)
  const [worldModelOpen, setWorldModelOpen] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const playback = useRef(null)
  const materialGeneration = useRef(null)
  const {togglePlayback, jumpToChapter, selectVantage, freezeAtProgress} = useJourneyPlayback({
    story, replay, setReplay, playing, setPlaying, setObserving, playback,
    setSelected, setFitSignal, setMessage,
  })

  const loadIndex = useCallback(async () => {
    const response = await fetch(api('/api/workspaces'), {cache: 'no-store'})
    if (!response.ok) throw new Error(`Workspace index unavailable (${response.status})`)
    const value = await response.json()
    setLoadError('')
    setIndex(value)
    setWorkspace((current) => {
      const selected = chooseWorkspace(value.workspaces, {
        current,
        requested: workspaceFromLocation,
        selectedId: value.selected_id,
      })
      if (selected?.id) trackWorkspaceLocation(selected.workspace_path || selected.workspace || selected.id)
      return selected?.id || ''
    })
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
    const nextTutorial = nextStory.origin?.kind === 'tutorial'
      ? await fetch(api('/api/tutorial', {workspace: id}), {cache: 'no-store'}).then((response) => response.ok ? response.json() : null)
      : null
    setStory(nextStory)
    setScene(nextScene)
    setInteractions(nextInteractions)
    setTutorial(nextTutorial)
    setSelected((current) => nextStory.chapters.some((chapter) => chapter.id === current?.siteId) ? current : null)
    if (!quiet) setReplay(nextStory.state === 'active' ? 1 : 0)
    if (!quiet) setObserving(false)
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
      trackWorkspaceLocation(item.workspace_path || item.workspace || item.id)
      setJourneysOpen(false)
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
  }

  async function refreshWorkspaces() {
    if (refreshing) return
    setRefreshing(true)
    setMessage('Reconciling with the current Rote workspace root')
    try {
      const response = await fetch(api('/api/refresh'), {method: 'POST', cache: 'no-store'})
      if (!response.ok) throw new Error(`Workspace refresh failed (${response.status})`)
      let value = await response.json()
      const reconciliation = value.reconciliation || {}
      setIndex(value)
      setLoadError('')
      const pending = new Set(value.workspaces.filter((item) => item.projectable && !item.graph_ready).map((item) => item.id))
      if (pending.size) {
        const deadline = Date.now() + 4000
        while (Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 240))
          value = await loadIndex()
          for (const item of value.workspaces) {
            if (item.graph_ready) pending.delete(item.id)
          }
          if (!pending.size) break
        }
      }
      const retained = value.workspaces.find((item) => item.id === workspace && (item.graph_ready || item.projectable))
      const target = retained || value.workspaces.find((item) => item.id === value.selected_id) || value.workspaces.find((item) => item.graph_ready || item.projectable)
      if (!target) {
        setWorkspace('')
        setStory(null)
        setScene(null)
        setInteractions(null)
        setTutorial(null)
        setSelected(null)
        setExchange(null)
        setPlaying(false)
        setObserving(false)
        setMessage(`Workspace slate refreshed · ${value.workspaces.length} current workspaces · no captured journey yet`)
        return
      }
      setWorkspace(target.id)
      trackWorkspaceLocation(target.workspace_path || target.workspace || target.id)
      if (target.graph_ready) {
        await loadJourney(target.id, true)
      } else {
        setStory(null)
        setScene(null)
        setInteractions(null)
        setTutorial(null)
        setExchange(null)
        await choose(target)
      }
      const result = reconciliation
      setMessage(`Workspace slate refreshed · ${result.current_workspaces ?? value.workspaces.length} current · ${result.stale_captures_hidden ?? 0} stale hidden`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setRefreshing(false)
    }
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
    events.addEventListener('journey', (event) => {
      let generation = null
      try { generation = JSON.parse(event.data)?.material_generation ?? null } catch {}
      if (generation !== null && generation === materialGeneration.current) {
        setSnapshotCountdown(10)
        return
      }
      materialGeneration.current = generation
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
            if (currentWorkspace?.active_recently) {
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


  return {
    index, workspace, story, scene, interactions, tutorial, selected, setSelected, exchange,
    replay, playing, observing, snapshotCountdown, lastSnapshotAt, fitSignal, setFitSignal,
    mode, setMode, message, loadError, journeysOpen, setJourneysOpen,
    telemetryOpen, setTelemetryOpen, worldModelOpen, setWorldModelOpen, refreshing,
    choose, refreshWorkspaces, togglePlayback, jumpToChapter, selectVantage, freezeAtProgress,
  }
}
