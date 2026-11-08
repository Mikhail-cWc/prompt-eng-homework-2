export interface Player {
  id: string
  name: string
  model: string
  personality: string
  traits: Record<string, string>
  revealed: string[]
  alive: boolean
  note: string
}
export interface GameEvent {
  seq: number
  kind: string
  actor_id?: string | null
  round: number
  data: Record<string, unknown>
  created_at: string
}
export interface QueueItem {
  player_id: string
  kind: string
  goal: string
  reply_to?: string | number | null
  selected?: boolean
  reason?: string
}
export interface GameSummary {
  id: string
  title: string
  status: string
  round: number
  phase: string
  created_at: string
}
export interface GameState extends GameSummary {
  rules_version?: '1.0' | '2.0'
  reading?: ReadingPause | null
  players: Player[]
  scenario: { title?: string; catastrophe?: string; bunker?: unknown } | null
  history: GameEvent[]
  queue: QueueItem[]
  debate_count: number
  debate_elapsed: number
  debate_counts?: Record<string, number>
  pending?: Record<string, unknown>
  error: string | null
  operation: string | null
  winners: string[]
  config: { debate_limit?: number; reading_pause?: boolean }
}
export interface ReadingPause {
  event_seq: number
  remaining: number
  deadline: number | null
}
export interface ModelCall {
  id: string
  actor_id: string | null
  model: string
  kind: string
  status: string
  attempt: number
  duration_ms?: number | null
  usage?: unknown
  error?: string | null
  created_at: string
  input?: unknown
  output?: unknown
  raw_response?: unknown
}
export interface SpeechStream {
  call_id: string
  actor_id: string
  attempt: number
  kind: string
  status: 'generating' | 'validating' | 'accepted' | 'discarded' | 'interrupted'
  text: string
  seq: number
  public_seq?: number
}
export interface GamePresentation {
  game: GameState
  stream: SpeechStream | null
  event_seq: number
}
