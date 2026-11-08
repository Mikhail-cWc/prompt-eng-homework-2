import { useCallback, useEffect, useRef, useState } from 'react'
import { api, safeMessage } from './api'
import { orderedHistory } from './replay'
import { applyStreamEvent } from './streamState'
import type { GameEvent, GamePresentation, GameState } from './types'

export function usePresentation(gameId: string | null, onActivity: () => Promise<unknown>) {
  const [data, setData] = useState<GamePresentation | null>(null)
  const [connection, setConnection] = useState<'connecting' | 'live' | 'offline'>('connecting')
  const [error, setError] = useState<string | null>(null)
  const session = useRef({ id: gameId, generation: 0, cursor: 0, snapshotSeq: -1 })

  const refresh = useCallback(async () => {
    if (!gameId) return
    const generation = session.current.generation
    const next = await api<GamePresentation>(`/api/games/${gameId}/presentation`)
    const current = session.current
    if (current.id !== gameId || current.generation !== generation || next.event_seq < current.snapshotSeq) return
    current.snapshotSeq = next.event_seq
    current.cursor = Math.max(current.cursor, next.event_seq)
    setData(previous => ({
      ...next, game: { ...next.game, history: orderedHistory(next.game.history) },
      stream: previous?.game.id === gameId && previous.stream && previous.stream.seq > next.event_seq ? previous.stream : next.stream,
    }))
    setConnection('live')
    setError(null)
  }, [gameId])

  useEffect(() => {
    session.current = { id: gameId, generation: session.current.generation + 1, cursor: 0, snapshotSeq: -1 }
    setData(null)
    setError(null)
    if (!gameId) { setConnection('live'); return }
    let active = true
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    setConnection('connecting')
    function failed(reason: unknown) {
      if (!active) return
      setConnection('offline')
      setError(safeMessage(reason instanceof Error ? reason.message : reason))
    }
    function connect() {
      if (!active || source) return
      source = new EventSource(`/api/games/${gameId}/events?after=${session.current.cursor}`)
      source.onopen = () => { if (active) setConnection('live') }
      source.onerror = () => { if (active) setConnection('offline') }
      source.addEventListener('update', message => {
        if (!active) return
        let event: GameEvent
        try { event = JSON.parse((message as MessageEvent<string>).data) as GameEvent } catch { return }
        if (!Number.isInteger(event.seq) || event.seq <= session.current.cursor) return
        session.current.cursor = event.seq
        if (event.kind === 'speech_stream') {
          setData(previous => previous ? { ...previous, stream: applyStreamEvent(previous.stream, event), event_seq: event.seq } : previous)
          return
        }
        if (timer) return
        timer = setTimeout(() => {
          timer = undefined
          if (active) { void refresh().catch(failed); void onActivity().catch(() => {}) }
        }, 180)
      })
    }
    void refresh().then(connect).catch(failed)
    const polling = setInterval(() => { void refresh().then(connect).catch(failed) }, 5000)
    return () => {
      active = false
      session.current.generation += 1
      source?.close()
      clearInterval(polling)
      if (timer) clearTimeout(timer)
    }
  }, [gameId, onActivity, refresh])

  function replaceGame(game: GameState) {
    setData(previous => previous?.game.id === game.id ? { ...previous, game: { ...game, history: orderedHistory(game.history) } } : previous)
  }
  return { game: data?.game ?? null, stream: data?.stream ?? null, connection, error, refresh, replaceGame }
}
