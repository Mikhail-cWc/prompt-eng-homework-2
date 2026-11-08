// @vitest-environment jsdom
import { act, createElement, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GameState } from './types'
import { useReplay } from './useReplay'

const event = (seq: number, kind: string, data: Record<string, unknown> = {}, round = 1) => ({ seq, kind, data, round, actor_id: null, created_at: '2026-10-24T12:00:00Z' })
const fixture: GameState = {
  id: 'hook-fixture', title: 'Тестовая партия', status: 'completed', round: 3, phase: 'finished', created_at: '', scenario: null,
  players: ['p1', 'p2'].map((id) => ({ id, name: id, model: 'test', personality: '', traits: {}, revealed: [], alive: id === 'p1', note: '' })),
  queue: [], debate_count: 0, debate_elapsed: 0, error: null, operation: null, winners: ['p1'], config: {},
  history: [event(4, 'narration', { text: 'Старт' }), event(8, 'speech', { text: 'Реплика' }), event(14, 'votes'), event(17, 'elimination', { eliminated_id: 'p2' }), event(23, 'narration', {}, 2), event(30, 'speech', {}, 2), event(40, 'epilogue', { winner_ids: ['p1'] }, 3)],
}

let state: ReturnType<typeof useReplay>
let root: ReturnType<typeof createRoot>
let container: HTMLDivElement
let game: GameState
function Harness({ value }: { value: GameState }) {
  const replay = useReplay(value)
  useEffect(() => { state = replay })
  return null
}
function render(value = game) { act(() => { root.render(createElement(Harness, { value })) }) }

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.useFakeTimers()
  localStorage.clear()
  game = structuredClone(fixture)
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('recording playback', () => {
  it('starts at the first event paused, advances at selected speed, pauses and stops at the end', () => {
    render()
    expect(state.index).toBe(0)
    expect(state.playing).toBe(false)
    act(() => state.setSpeed(2))
    act(() => state.toggle())
    act(() => vi.advanceTimersByTime(1999))
    expect(state.index).toBe(0)
    act(() => vi.advanceTimersByTime(1))
    expect(state.index).toBe(1)
    act(() => state.toggle())
    act(() => vi.advanceTimersByTime(100000))
    expect(state.index).toBe(1)
    act(() => state.seek(state.history.length - 2))
    act(() => state.toggle())
    act(() => vi.advanceTimersByTime(2000))
    expect(state.index).toBe(state.history.length - 1)
    expect(state.playing).toBe(false)
  })

  it('supports previous, next, round jumps and final then backward without leaking future state', () => {
    render()
    act(() => state.seek(state.history.findIndex((entry) => entry.round === 2)))
    expect(state.view?.round).toBe(2)
    act(() => state.step(-1))
    expect(state.view?.round).toBe(1)
    act(() => state.seek(999))
    expect(state.view?.winners).toEqual(['p1'])
    act(() => state.seek(-10))
    expect(state.view?.winners).toEqual([])
    expect(state.view?.players[1].alive).toBe(true)
  })

  it('preserves the cursor on refresh/append and restores position and speed without autoplay', () => {
    render()
    act(() => state.seek(2))
    act(() => state.setSpeed(0.5))
    render({ ...game, history: [...game.history, event(45, 'narration')] })
    expect(state.cursorSeq).toBe(14)
    act(() => root.unmount())
    root = createRoot(container)
    render()
    expect(state.cursorSeq).toBe(14)
    expect(state.speed).toBe(0.5)
    expect(state.playing).toBe(false)
  })

  it('does not restart the reading timer when polling refreshes the same history', () => {
    game.history[0].data.text = 'x'.repeat(250)
    render()
    act(() => state.toggle())
    act(() => vi.advanceTimersByTime(5000))
    render(structuredClone(game))
    act(() => vi.advanceTimersByTime(5000))
    expect(state.index).toBe(1)
  })

  it('keeps each recording position separate and handles unavailable browser storage', () => {
    render()
    act(() => state.seek(2))
    act(() => state.setSpeed(0.5))
    render({ ...game, id: 'another-fixture' })
    expect(state.index).toBe(0)
    expect(state.speed).toBe(1)
    render()
    expect(state.cursorSeq).toBe(14)
    expect(state.speed).toBe(0.5)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    act(() => state.step(1))
    expect(state.cursorSeq).toBe(17)
  })

  it('waits twice as long at half speed and ignores invalid speed controls', () => {
    render()
    act(() => state.setSpeed(0.5))
    act(() => state.setSpeed(0))
    expect(state.speed).toBe(0.5)
    act(() => state.toggle())
    act(() => vi.advanceTimersByTime(7999))
    expect(state.index).toBe(0)
    act(() => vi.advanceTimersByTime(1))
    expect(state.index).toBe(1)
  })

  it('keeps live games current and makes no requests or server commands during replay', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render({ ...game, status: 'running' })
    expect(state.isReplay).toBe(false)
    expect(state.view?.players[1].alive).toBe(false)
    act(() => state.toggle())
    expect(state.playing).toBe(false)
    render()
    act(() => state.toggle())
    act(() => state.step(1))
    act(() => state.setSpeed(2))
    act(() => vi.advanceTimersByTime(10000))
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it.each(['running', 'paused'])('keeps the observed finale visible when %s becomes completed', (status) => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render({ ...game, status, history: game.history.slice(0, -1), winners: [] })
    expect(state.isReplay).toBe(false)
    render()
    expect(state.isReplay).toBe(true)
    expect(state.index).toBe(game.history.length - 1)
    expect(state.view?.winners).toEqual(['p1'])
    expect(state.playing).toBe(false)
    expect(fetchSpy).not.toHaveBeenCalled()
    act(() => state.step(-1))
    expect(state.view?.winners).toEqual([])
    render(structuredClone(game))
    expect(state.index).toBe(game.history.length - 2)
  })

  it('keeps the last observed event when the server stops a live game', () => {
    render({ ...game, status: 'running', history: game.history.slice(0, -1), winners: [] })
    render({ ...game, status: 'stopped', history: game.history.slice(0, -1), winners: [] })
    expect(state.cursorSeq).toBe(30)
    expect(state.playing).toBe(false)
    expect(state.view?.status).toBe('stopped')
    expect(state.view?.winners).toEqual([])
  })
})
