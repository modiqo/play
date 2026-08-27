import {useCallback, useEffect, useRef, useState} from 'react'
import {api, trackWorkspaceLocation, workspaceFromLocation} from './api.js'
import {useJourneyPlayback} from './use-journey-playback.js'
import {chooseWorkspace} from './workspace-choice.mjs'
import {reconcileJourneyPosition} from './journey-position.mjs'
import {
  liveWorkspaceRefreshActive,
  startLiveWorkspaceRefresh,
  workspaceRefreshSeconds,
} from './live-workspace-refresh.mjs'

export function useJourneyRuntime() {
  const [index, setIndex] = useState(null)
  const [workspace, setWorkspace] = useState('')
  const [story, setStory] = useState(null)
  const [interactions, setInteractions] = useState(null)
  const [tutorial, setTutorial] = useState(null)
  const [selected, setSelected] = useState(null)
  const [exchange, setExchange] = useState(null)
  const [replay, setReplay] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [observing, setObserving] = useState(false)
  const [trackingLive, setTrackingLiveState] = useState(false)
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
  const storyRef = useRef(null)
  const selectedRef = useRef(null)
  const playingRef = useRef(false)
  const trackingLiveRef = useRef(false)
  const wasPlayingRef = useRef(false)
  const loadRequestRef = useRef(0)
  const startingWorkspaceRef = useRef('')
  const liveRefreshLeaseRef = useRef(null)
  const setTrackingLive = useCallback((value) => {
    const next = Boolean(value)
    trackingLiveRef.current = next
    setTrackingLiveState(next)
  }, [])
  const {togglePlayback, jumpToChapter, selectVantage, freezeAtProgress} = useJourneyPlayback({
    story, replay, setReplay, playing, setPlaying, setObserving, playback,
    setSelected, setFitSignal, setMessage, setTrackingLive,
  })

  useEffect(() => { selectedRef.current = selected }, [selected])
  useEffect(() => { playingRef.current = playing }, [playing])

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
      if (selected?.id && selected.id !== current) startingWorkspaceRef.current = selected.id
      return selected?.id || ''
    })
    return value
  }, [])

  const loadJourney = useCallback(async (id, quiet = false) => {
    const request = ++loadRequestRef.current
    const startsWorkspace = !quiet || startingWorkspaceRef.current === id
    if (startsWorkspace) setReplay(0)
    if (!quiet) setMessage('Loading journey map')
    const [storyResponse, interactionResponse] = await Promise.all([
      fetch(api('/api/story', {workspace: id}), {cache: 'no-store'}),
      fetch(api('/api/interactions', {workspace: id}), {cache: 'no-store'}),
    ])
    if (!storyResponse.ok || !interactionResponse.ok) throw new Error('Journey map is unavailable')
    const [nextStory, nextInteractions] = await Promise.all([storyResponse.json(), interactionResponse.json()])
    if (request !== loadRequestRef.current) return false
    if (quiet && playingRef.current) return false
    const nextTutorial = nextStory.origin?.kind === 'tutorial'
      ? await fetch(api('/api/tutorial', {workspace: id}), {cache: 'no-store'}).then((response) => response.ok ? response.json() : null)
      : null
    if (request !== loadRequestRef.current) return false
    const previousStory = storyRef.current
    setReplay((current) => reconcileJourneyPosition({
      previousStory,
      nextStory,
      replay: current,
      selected: selectedRef.current,
      quiet: quiet && !startsWorkspace,
      followHead: trackingLiveRef.current,
    }))
    if (nextStory.state !== 'active') setTrackingLive(false)
    if (nextStory.state === 'active') {
      const currentLease = liveRefreshLeaseRef.current
      if (!currentLease || currentLease.workspace !== id) {
        liveRefreshLeaseRef.current = startLiveWorkspaceRefresh(id)
      }
    } else if (liveRefreshLeaseRef.current?.workspace === id) {
      liveRefreshLeaseRef.current = null
    }
    storyRef.current = nextStory
    setStory(nextStory)
    setInteractions(nextInteractions)
    setTutorial(nextTutorial)
    setSelected((current) => nextStory.chapters.some((chapter) => chapter.id === current?.siteId) ? current : null)
    if (startingWorkspaceRef.current === id) startingWorkspaceRef.current = ''
    if (!quiet) setObserving(false)
    if (!quiet) setMessage(nextStory.state === 'active' ? 'Live journey connected' : 'Recorded journey loaded')
    setLastSnapshotAt(Date.now())
    return true
  }, [setTrackingLive])

  async function choose(item) {
    try {
      setReplay(0)
      setPlaying(false)
      setObserving(true)
      setTrackingLive(false)
      liveRefreshLeaseRef.current = null
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
      // Commit the user's destination before hydrating its (potentially large)
      // story and interaction payloads. Keeping the previous workspace current
      // during that request lets index reconciliation preserve the old journey
      // and makes a successful click appear to do nothing.
      startingWorkspaceRef.current = item.id
      setWorkspace(item.id)
      trackWorkspaceLocation(item.workspace_path || item.workspace || item.id)
      setJourneysOpen(false)
      setMessage('Loading journey map')
      // Selecting the already-open card does not change `workspace`, so its
      // effect will not run again. Refresh it explicitly in that one case.
      if (item.id === workspace) await loadJourney(item.id)
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
        startingWorkspaceRef.current = ''
        setWorkspace('')
        setStory(null)
        setScene(null)
        setInteractions(null)
        setTutorial(null)
        setSelected(null)
        setExchange(null)
        setPlaying(false)
        setObserving(false)
        setTrackingLive(false)
        setMessage(`Workspace slate refreshed · ${value.workspaces.length} current workspaces · no captured journey yet`)
        return
      }
      if (target.id !== workspace) {
        startingWorkspaceRef.current = target.id
        setReplay(0)
        setTrackingLive(false)
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
    let cancelled = false
    let retryTimer = null
    let retryDelay = 1000
    const connect = () => {
      loadIndex().catch((error) => {
        if (cancelled) return
        setMessage('Reconnecting to Journey')
        setLoadError(error.message)
        retryTimer = window.setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 15000)
          connect()
        }, retryDelay)
      })
    }
    connect()
    return () => {
      cancelled = true
      if (retryTimer !== null) window.clearTimeout(retryTimer)
    }
  }, [loadIndex])
  useEffect(() => {
    if (!workspace) return undefined
    loadJourney(workspace).catch((error) => setMessage(error.message))
    const events = new EventSource(api('/api/events', {workspace}))
    events.addEventListener('journey', (event) => {
      let generation = null
      try { generation = JSON.parse(event.data)?.material_generation ?? null } catch {}
      if (generation !== null && generation === materialGeneration.current) {
        return
      }
      materialGeneration.current = generation
    })
    events.onerror = () => setMessage('Reconnecting to live journey')
    return () => events.close()
  }, [loadIndex, loadJourney, workspace])

  useEffect(() => {
    if (wasPlayingRef.current && !playing && workspace) {
      loadJourney(workspace, true).catch(() => {})
    }
    wasPlayingRef.current = playing
  }, [loadJourney, playing, workspace])

  useEffect(() => {
    if (!workspace) return undefined
    let refreshInFlight = false
    let remaining = workspaceRefreshSeconds({
      lease: liveRefreshLeaseRef.current,
      workspace,
      storyState: storyRef.current?.state,
    })
    setSnapshotCountdown(remaining)
    const interval = window.setInterval(() => {
      const cadence = workspaceRefreshSeconds({
        lease: liveRefreshLeaseRef.current,
        workspace,
        storyState: storyRef.current?.state,
      })
      remaining = Math.min(remaining, cadence)
      remaining -= 1
      if (remaining <= 0) {
        remaining = cadence
        if (refreshInFlight) {
          setSnapshotCountdown(remaining)
          return
        }
        refreshInFlight = true
        loadIndex()
          .then(async (nextIndex) => {
            const currentWorkspace = nextIndex.workspaces.find((item) => item.id === workspace)
            const fastRefresh = liveWorkspaceRefreshActive({
              lease: liveRefreshLeaseRef.current,
              workspace,
              storyState: storyRef.current?.state,
            })
            if (fastRefresh && currentWorkspace?.journey_mode === 'live') {
              await fetch(api('/api/project', {workspace, refresh: '1'}), {
                method: 'POST',
                cache: 'no-store',
              })
              return loadJourney(workspace, true)
            }
            if (currentWorkspace?.active_recently) {
              return loadJourney(workspace, true)
            }
            return undefined
          })
          .catch(() => {})
          .finally(() => { refreshInFlight = false })
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

  const toggleLiveTracking = useCallback(() => {
    if (!workspace || storyRef.current?.state !== 'active') {
      setMessage('Live tracking is available only while this exploration is active')
      return
    }
    if (trackingLiveRef.current) {
      setTrackingLive(false)
      setObserving(true)
      setMessage('Live head released · current vantage frozen')
      return
    }
    playback.current = null
    setPlaying(false)
    setObserving(false)
    setSelected(null)
    setTrackingLive(true)
    setReplay(1)
    setMessage('Tracking the live head · snapshots advance on a calm cadence')
    loadJourney(workspace, true).catch(() => {})
  }, [loadJourney, setTrackingLive, workspace])


  return {
    index, workspace, story, interactions, tutorial, selected, setSelected, exchange,
    replay, playing, observing, trackingLive, snapshotCountdown, lastSnapshotAt, fitSignal, setFitSignal,
    mode, setMode, message, loadError, journeysOpen, setJourneysOpen,
    telemetryOpen, setTelemetryOpen, worldModelOpen, setWorldModelOpen, refreshing,
    choose, refreshWorkspaces, togglePlayback, toggleLiveTracking, jumpToChapter, selectVantage, freezeAtProgress,
  }
}
