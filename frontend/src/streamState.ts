import type { GameEvent, SpeechStream } from './types'

const statuses = new Set(['generating', 'validating', 'accepted', 'discarded', 'interrupted'])

export function applyStreamEvent(current: SpeechStream | null, event: GameEvent): SpeechStream | null {
  const data = event.data
  if (event.kind !== 'speech_stream' || !Number.isInteger(event.seq) || event.seq <= (current?.seq ?? -1)) return current
  if (typeof data.call_id !== 'string' || typeof data.actor_id !== 'string' || typeof data.kind !== 'string' ||
    !Number.isInteger(data.attempt) || Number(data.attempt) < 1 || typeof data.text !== 'string' || !statuses.has(String(data.status))) return current
  if (current && data.call_id !== current.call_id && !(data.status === 'generating' && data.text === '')) return current
  const status = data.status as SpeechStream['status']
  return {
    call_id: data.call_id, actor_id: data.actor_id, kind: data.kind, attempt: Number(data.attempt), status,
    text: ['discarded', 'interrupted'].includes(status) ? '' : [...data.text].slice(0, 1200).join(''),
    seq: event.seq, ...(typeof data.public_seq === 'number' ? { public_seq: data.public_seq } : {}),
  }
}
