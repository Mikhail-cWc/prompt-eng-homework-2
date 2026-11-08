import { describe, expect, it } from 'vitest'
import { applyStreamEvent } from './streamState'
import type { GameEvent, SpeechStream } from './types'

const preview: SpeechStream = { call_id: 'one', actor_id: 'p1', kind: 'speech', attempt: 1, status: 'generating', text: 'Начало', seq: 12 }
const event = (seq: number, data: Record<string, unknown>): GameEvent => ({ seq, kind: 'speech_stream', actor_id: 'p1', round: 1, data, created_at: '' })
describe('observer stream reducer', () => {
  it('keeps 1200 Unicode characters in a public draft without the old 600-character cut', () => {
    const text = 'я'.repeat(1199) + '🙂'
    expect(applyStreamEvent(preview, event(13, { ...preview, text }))?.text).toBe(text)
    expect(applyStreamEvent(preview, event(14, { ...preview, text: text + 'я' }))?.text).toBe(text)
  })
  it('replaces cumulative prefixes, ignoring repeated and stale sequences', () => {
    const next = applyStreamEvent(preview, event(14, { ...preview, text: 'Начало речи', seq: undefined }))
    expect(next?.text).toBe('Начало речи')
    expect(next?.seq).toBe(14)
    expect(applyStreamEvent(next, event(13, { ...preview, text: 'Старая часть' }))).toBe(next)
  })
  it('does not let a previous attempt overwrite the current attempt', () => {
    const next = { ...preview, call_id: 'two', attempt: 2, seq: 20 }
    expect(applyStreamEvent(next, event(21, { ...preview, text: 'Поздняя часть' }))).toBe(next)
  })
  it('discards public text from failed attempts and ignores unknown statuses', () => {
    expect(applyStreamEvent(preview, event(13, { ...preview, status: 'discarded' }))?.text).toBe('')
    expect(applyStreamEvent(preview, event(13, { ...preview, status: 'unknown' }))).toBe(preview)
  })
})
