import { describe, expect, it } from 'vitest'
import type { GameEvent, GameState } from './types'
import { eventDuration, orderedHistory, projectGame, readReplayPosition } from './replay'

const event = (seq: number, kind: string, data: GameEvent['data'] = {}, actor_id: string | null = null, round = 1): GameEvent => ({ seq, kind, data, actor_id, round, created_at: '2026-10-24T12:00:00Z' })

const fixture: GameState = {
  id: 'fixture-replay', title: 'Тестовая партия', status: 'completed', round: 3, phase: 'finished', created_at: '2026-10-24T12:00:00Z',
  players: ['p1', 'p2'].map((id) => ({ id, name: id, model: 'test', personality: '', traits: { profession: 'Врач', hobby: 'Шахматы' }, revealed: ['profession', 'hobby'], alive: id === 'p1', note: 'Финальная секретная заметка' })),
  scenario: null, queue: [{ player_id: 'p2', kind: 'object', goal: 'Будущее намерение', selected: true }], debate_count: 8, debate_elapsed: 600, pending: { p1: 'secret vote' }, error: 'old error', operation: 'old operation', winners: ['p1'], config: { debate_limit: 8 },
  history: [event(4, 'narration', { text: 'Начало', event: 'Вводная' }), event(8, 'reveal', { text: 'Я нужен', reveal: ['profession'], traits: { profession: 'Врач' } }, 'p1'), event(14, 'votes', { votes: [{ player_id: 'p1', candidate_id: 'p2', reason: 'Причина' }] }), event(17, 'elimination', { eliminated_id: 'p2', text: 'Уходит p2' }), event(23, 'narration', { text: 'Следующий раунд', event: 'Новая опасность' }, null, 2), event(30, 'reveal', { text: 'Ещё факт', reveal: ['hobby'], traits: { hobby: 'Шахматы' } }, 'p1', 2), event(40, 'epilogue', { text: 'Конец', winner_ids: ['p1'] }, null, 3)],
}

describe('historical presentation', () => {
  it('keeps preliminary nominees alive through defense and final ballot until actual exile', () => {
    const game = { ...fixture, rules_version: '2.0' as const, history: [
      event(1, 'votes', { stage: 'preliminary', defense_candidates: ['p1'], votes: [] }),
      event(2, 'defense', { text: 'Хочу жить, не оставляйте меня снаружи.', reveal: [] }, 'p1'),
      event(3, 'votes', { stage: 'final', votes: [] }),
      event(4, 'elimination', { eliminated_id: 'p2' }),
    ] }
    expect(projectGame(game, 1).players.every(p => p.alive)).toBe(true)
    expect(projectGame(game, 2).phase).toBe('defense')
    expect(projectGame(game, 2).activeSpeakerId).toBe('p1')
    expect(projectGame(game, 2).players.every(p => p.revealed.length === 0)).toBe(true)
    expect(projectGame(game, 3).phase).toBe('final_vote')
    expect(projectGame(game, 3).activeSpeakerId).toBeNull()
    expect(projectGame(game, 3).players.every(p => p.alive)).toBe(true)
    expect(projectGame(game, 4).players[1].alive).toBe(false)
    expect(projectGame(game, 1).players[1].alive).toBe(true)
  })
  it('does not leak final reveals, elimination, notes, queue or votes into the first event', () => {
    const view = projectGame(fixture, 4)
    expect(view.players.every((player) => player.alive && player.revealed.length === 0 && player.note === '')).toBe(true)
    expect(view.winners).toEqual([])
    expect(view.pending).toEqual({})
    expect(view.queue).toEqual([])
    expect(view.history.map(({ seq }) => seq)).toEqual([4])
    expect(view.round).toBe(1)
    expect(view.operation).toBeNull()
    expect(view.error).toBeNull()
  })

  it('applies reveals and elimination only at their event, and supports backward seeks', () => {
    expect(projectGame(fixture, 8).players[0].revealed).toEqual(['profession'])
    expect(projectGame(fixture, 14).players[1].alive).toBe(true)
    expect(projectGame(fixture, 17).players[1].alive).toBe(false)
    expect(projectGame(fixture, 30).players[0].revealed).toEqual(['profession', 'hobby'])
    expect(projectGame(fixture, 8).players[1].alive).toBe(true)
    expect(projectGame(fixture, 8).activeSpeakerId).toBe('p1')
    expect(fixture.players[0].revealed).toEqual(['profession', 'hobby'])
  })

  it('changes rounds and exposes winners only after the epilogue', () => {
    expect(projectGame(fixture, 23).round).toBe(2)
    expect(projectGame(fixture, 30).winners).toEqual([])
    expect(projectGame(fixture, 40).winners).toEqual(['p1'])
    expect(projectGame(fixture, 40).activeSpeakerId).toBeNull()
    expect(projectGame(fixture, 40).status).toBe('completed')
  })

  it('sorts and deduplicates reconnect events by seq without mutating the input', () => {
    const history = [event(8, 'speech'), event(4, 'narration'), event(8, 'speech', { text: 'canonical latest' })]
    expect(orderedHistory(history).map(({ seq }) => seq)).toEqual([4, 8])
    expect(orderedHistory(history)[1].data.text).toBe('canonical latest')
    expect(history[0].seq).toBe(8)
  })
})

describe('playback inputs', () => {
  it('rejects corrupt storage and invalid speeds, clamps stale positions to actual events', () => {
    const history = fixture.history
    expect(readReplayPosition('{broken', history)).toEqual({ cursorSeq: 4, speed: 1 })
    expect(readReplayPosition('{"cursorSeq":999,"speed":9}', history)).toEqual({ cursorSeq: 40, speed: 1 })
    expect(readReplayPosition('{"cursorSeq":-3,"speed":0.5}', history)).toEqual({ cursorSeq: 4, speed: 0.5 })
    expect(readReplayPosition('{"cursorSeq":16,"speed":2}', history)).toEqual({ cursorSeq: 14, speed: 2 })
    expect(readReplayPosition('null', history)).toEqual({ cursorSeq: 4, speed: 1 })
    expect(readReplayPosition('{}', [])).toEqual({ cursorSeq: 0, speed: 1 })
  })

  it('uses reading time without replaying historical network delays', () => {
    expect(eventDuration(event(1, 'speech', { text: 'Коротко' }))).toBe(4000)
    expect(eventDuration(event(1, 'speech', { text: 'x'.repeat(250) }))).toBe(10000)
    expect(eventDuration(event(1, 'speech', { text: 'x'.repeat(1000) }))).toBe(25000)
    expect(eventDuration(event(1, 'votes'))).toBe(6000)
    expect(eventDuration(event(1, 'elimination'))).toBe(6000)
  })
})
