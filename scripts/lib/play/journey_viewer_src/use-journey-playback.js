import {useCallback, useEffect} from 'react'
import {PLAYBACK_DEPARTURE_MS, playbackProgress} from './playback-clock.mjs'

export function useJourneyPlayback({
  story,
  replay,
  setReplay,
  playing,
  setPlaying,
  setObserving,
  playback,
  setSelected,
  setFitSignal,
  setMessage,
  setTrackingLive,
}) {
  useEffect(() => {
    if (!playing || !story) return undefined
    let frame = 0
    const count = story.chapters.length
    const intervals = Math.max(1, count - 1)
    const tutorial = story.origin?.kind === 'tutorial'
    // Give each site enough stillness for its meaning and evidence affordances
    // to register before the embodied walk resumes.
    const dwellMs = tutorial ? 6500 : 2800
    const travelMs = tutorial ? 3200 : 4200
    const tick = (time) => {
      const state = playback.current
      if (!state) return
      const clock = playbackProgress({
        from: state.from,
        elapsedMs: time - state.started,
        intervals,
        travelMs,
        dwellMs,
        departureMs: PLAYBACK_DEPARTURE_MS,
      })
      const units = clock.progress * intervals
      const stage = Math.min(intervals, Math.floor(units))
      const fraction = units - stage
      const easedFraction = fraction * fraction * (3 - 2 * fraction)
      const progress = Math.min(1, (stage + easedFraction) / intervals)
      setReplay(progress)
      if (clock.complete) {
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
  }, [playback, playing, setMessage, setObserving, setPlaying, setReplay, story])

  function togglePlayback() {
    setTrackingLive(false)
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
    setMessage('Departing for the next site')
  }

  function jumpToChapter(index) {
    setTrackingLive(false)
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
      setTrackingLive(false)
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
  }, [playback, setMessage, setObserving, setPlaying, setReplay, setSelected, setTrackingLive, story])

  function freezeAtProgress(value) {
    setTrackingLive(false)
    playback.current = null
    setPlaying(false)
    setObserving(true)
    setReplay(value)
    setMessage('Vantage frozen · inspect the illuminated structures')
  }

  return {togglePlayback, jumpToChapter, selectVantage, freezeAtProgress}
}
