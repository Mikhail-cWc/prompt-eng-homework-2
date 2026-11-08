import { useEffect, useMemo, useState } from 'react'
import type { GameState } from './types'
import { eventDuration, orderedHistory, projectGame, readReplayPosition, replaySpeeds } from './replay'

interface PlaybackState {
  gameId: string
  isReplay: boolean
  cursorSeq: number
  speed: number
  playing: boolean
}

const storageKey = (gameId: string) => `bunker-replay:${gameId}`

function initialState(gameId: string, history: ReturnType<typeof orderedHistory>, isReplay: boolean): PlaybackState {
  let stored = null
  try { stored = localStorage.getItem(storageKey(gameId)) } catch { /* Storage may be disabled. */ }
  return { gameId, isReplay, ...readReplayPosition(stored, history), playing: false }
}

function reconcilePlayback(previous: PlaybackState, gameId: string, history: ReturnType<typeof orderedHistory>, isReplay: boolean): PlaybackState {
  if (previous.gameId !== gameId) return initialState(gameId, history, isReplay)
  if (previous.isReplay === isReplay) return previous
  return { ...previous, isReplay, cursorSeq: isReplay ? history.at(-1)?.seq ?? 0 : previous.cursorSeq, playing: false }
}

export function useReplay(game: GameState | null) {
  const gameId = game?.id ?? ''
  const history = useMemo(() => orderedHistory(game?.history ?? []), [game?.history])
  const isReplay = game?.status === 'completed' || game?.status === 'stopped'
  const [playback, setPlayback] = useState<PlaybackState>(() => initialState(gameId, history, isReplay))
  const current = reconcilePlayback(playback, gameId, history, isReplay)
  const index = isReplay ? history.reduce((found, entry, position) => entry.seq <= current.cursorSeq ? position : found, 0) : Math.max(0, history.length - 1)
  const cursorSeq = history[index]?.seq ?? 0
  const playing = Boolean(isReplay && current.playing && index < history.length - 1)
  const speed = current.speed
  const duration = history[index] ? eventDuration(history[index]) : 0
  const nextSeq = history[index + 1]?.seq ?? cursorSeq
  const lastIndex = history.length - 1

  useEffect(() => {
    setPlayback((previous) => reconcilePlayback(previous, gameId, history, isReplay))
  }, [gameId, history, isReplay])

  useEffect(() => {
    if (!gameId || !isReplay || playback.gameId !== gameId) return
    try { localStorage.setItem(storageKey(gameId), JSON.stringify({ cursorSeq, speed })) } catch { /* Playback still works without persistence. */ }
    if (playback.playing && !playing) setPlayback((previous) => ({ ...previous, playing: false }))
  }, [gameId, isReplay, cursorSeq, speed, playing, playback.gameId, playback.playing])

  useEffect(() => {
    if (!playing) return
    const timer = window.setTimeout(() => {
      setPlayback((previous) => ({ ...previous, cursorSeq: nextSeq, playing: index + 1 < lastIndex }))
    }, duration / speed)
    return () => window.clearTimeout(timer)
  }, [playing, index, speed, duration, nextSeq, lastIndex])

  const view = useMemo(() => game ? isReplay ? projectGame(game, cursorSeq) : game : null, [game, isReplay, cursorSeq])

  function seek(nextIndex: number) {
    if (!isReplay || !Number.isFinite(nextIndex)) return
    const target = Math.min(history.length - 1, Math.max(0, Math.trunc(nextIndex)))
    setPlayback((previous) => ({ ...previous, cursorSeq: history[target]?.seq ?? 0, playing: false }))
  }

  function toggle() {
    if (!isReplay || !history.length) return
    setPlayback((previous) => ({ ...previous, cursorSeq: index === history.length - 1 ? history[0].seq : cursorSeq, playing: !playing }))
  }

  function setSpeed(nextSpeed: number) {
    if (!replaySpeeds.some((value) => value === nextSpeed)) return
    setPlayback((previous) => ({ ...previous, speed: nextSpeed }))
  }

  function pause() { setPlayback(previous => ({ ...previous, playing: false })) }

  return { isReplay, cursorSeq, index, playing, speed, history, view, seek, step: (delta: number) => seek(index + delta), toggle, pause, setSpeed }
}
