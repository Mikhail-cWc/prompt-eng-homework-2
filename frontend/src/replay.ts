import type { GameEvent, GameState } from './types'

export interface PresentationGameState extends GameState {
  activeSpeakerId: string | null
}

export const replaySpeeds = [0.5, 1, 2] as const

export function orderedHistory(history: GameEvent[]): GameEvent[] {
  return [...new Map(history.map((entry) => [entry.seq, entry])).values()].sort((left, right) => left.seq - right.seq)
}

export function projectGame(game: GameState, cursorSeq: number): PresentationGameState {
  const history = orderedHistory(game.history).filter((entry) => entry.seq <= cursorSeq)
  const players = game.players.map((player) => ({ ...player, traits: { ...player.traits }, revealed: [] as string[], alive: true, note: '' }))
  let phase = 'opening'
  let winners: string[] = []
  let activeSpeakerId: string | null = null
  let debateCount = 0
  let round = history[0]?.round ?? 1
  const debateCounts: Record<string, number> = {}

  for (const entry of history) {
    if (round !== entry.round) {
      debateCount = 0
      for (const key of Object.keys(debateCounts)) delete debateCounts[key]
    }
    round = entry.round
    activeSpeakerId = null
    switch (entry.kind) {
      case 'narration':
        phase = entry.data.event ? 'opening' : 'aftermath'
        break
      case 'reveal': {
        phase = 'reveal'
        activeSpeakerId = entry.actor_id ?? null
        const player = players.find(({ id }) => id === entry.actor_id)
        const traits = entry.data.traits && typeof entry.data.traits === 'object' ? Object.keys(entry.data.traits) : []
        const reveal = Array.isArray(entry.data.reveal) ? entry.data.reveal.filter((key): key is string => typeof key === 'string') : traits
        if (player) player.revealed = [...new Set([...player.revealed, ...reveal])]
        break
      }
      case 'speech':
        phase = 'debate'
        activeSpeakerId = entry.actor_id ?? null
        debateCount += 1
        if (entry.actor_id) debateCounts[entry.actor_id] = (debateCounts[entry.actor_id] ?? 0) + 1
        break
      case 'closing':
      case 'defense':
        phase = entry.kind
        activeSpeakerId = entry.actor_id ?? null
        break
      case 'debate_closed':
        phase = 'closing'
        break
      case 'votes':
        phase = entry.data.stage === 'final' ? 'final_vote' : entry.data.runoff ? 'runoff' : 'vote'
        break
      case 'elimination': {
        phase = 'aftermath'
        const player = players.find(({ id }) => id === entry.data.eliminated_id)
        if (player) player.alive = false
        break
      }
      case 'epilogue':
        phase = 'done'
        winners = Array.isArray(entry.data.winner_ids) ? entry.data.winner_ids.filter((id): id is string => typeof id === 'string') : []
        break
    }
  }

  return {
    id: game.id, title: game.title, created_at: game.created_at, rules_version: game.rules_version,
    status: phase === 'done' ? 'completed' : game.status === 'stopped' && history.length === orderedHistory(game.history).length ? 'stopped' : 'paused',
    round, phase, players, scenario: game.scenario, history, queue: [],
    debate_count: debateCount, debate_counts: debateCounts, debate_elapsed: 0,
    pending: {}, error: null, operation: null, winners, config: game.config,
    activeSpeakerId: phase === 'done' ? null : activeSpeakerId,
  }
}

export function eventDuration(entry: GameEvent): number {
  if (entry.kind === 'votes' || entry.kind === 'elimination') return 6000
  const text = typeof entry.data.text === 'string' ? entry.data.text : ''
  return Math.min(25000, Math.max(4000, text.length / 25 * 1000))
}

export interface ReplayPosition {
  cursorSeq: number
  speed: number
}

export function readReplayPosition(raw: string | null, history: GameEvent[]): ReplayPosition {
  let saved: Partial<ReplayPosition> | null = null
  try { saved = raw ? JSON.parse(raw) : null } catch { /* Invalid browser storage starts a fresh recording. */ }
  const speed = saved && replaySpeeds.some((value) => value === saved.speed) ? saved.speed! : 1
  const first = history[0]?.seq ?? 0
  const requested = saved && typeof saved.cursorSeq === 'number' && Number.isFinite(saved.cursorSeq) ? saved.cursorSeq : first
  const cursorSeq = history.filter(({ seq }) => seq <= requested).at(-1)?.seq ?? first
  return { cursorSeq, speed }
}
