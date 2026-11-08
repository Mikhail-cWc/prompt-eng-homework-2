// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GameEvent, GameState, SpeechStream } from '../types'
import { GameScene } from './GameScene'
import { ConversationPanel } from './ConversationPanel'
import { projectGame } from '../replay'

const event = (kind: string, data: GameEvent['data'], actor_id: string | null = null): GameEvent => ({ seq: 10, kind, data, actor_id, round: 1, created_at: '' })
const fixture: GameState = {
  id: 'scene-fixture', title: 'Тестовая сцена', status: 'running', phase: 'speech', round: 1, created_at: '',
  players: Array.from({ length: 6 }, (_, i) => ({ id: `p${i + 1}`, name: `Участник ${i + 1}`, model: 'fixture', personality: 'Персонаж', traits: { profession: 'Публичная профессия', health: 'Скрытое здоровье' }, revealed: ['profession'], alive: true, note: 'Скрытая заметка' })),
  scenario: null, history: [], queue: [], debate_count: 0, debate_elapsed: 0, error: null, operation: null, winners: [], config: {},
}
const stream = (status: SpeechStream['status'], text = ''): SpeechStream => ({ call_id: 'test-call', actor_id: 'p1', attempt: 1, kind: 'speech', status, text, seq: 11 })
let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals() })
function render(game: GameState = fixture, current: SpeechStream | null = null, onPlayer = vi.fn(), navigation = 0) {
  act(() => root.render(<GameScene game={game} stream={current} onPlayer={onPlayer} navigation={navigation} empty={<p>Ожидание</p>} />))
}

describe('public scene', () => {
  it('distinguishes preliminary votes, defense and decisive votes without premature exile', () => {
    render({ ...fixture, phase: 'defense', history: [event('votes', { stage: 'preliminary', votes: [{ player_id: 'p2', candidate_id: 'p1', reason: 'Пока так' }] })] })
    expect(container.querySelector('.speech-bubble')?.textContent).toContain('Предварительное голосование')
    expect(container.textContent).toContain('Никто ещё не изгнан')
    expect(container.querySelector('.scene-player.eliminated')).toBeNull()
    render(projectGame({ ...fixture, history: [event('defense', { text: 'Я хочу жить', reveal: [] }, 'p1')] }, 10))
    expect(container.querySelector('.speech-bubble')?.textContent).toContain('Защитная речь')
    expect(container.querySelector('.scene-player.speaking')?.textContent).toContain('Участник 1')
    render({ ...fixture, phase: 'final_vote', history: [event('votes', { stage: 'final', votes: [{ player_id: 'p2', candidate_id: 'p3', reason: 'Изменил решение' }] })] })
    expect(container.querySelector('.speech-bubble')?.textContent).toContain('Решающее голосование')
    expect(container.querySelector('.scene-player.speaking')).toBeNull()
  })
  it('renders every revealed trait and never includes hidden values or notes', () => {
    render()
    expect(container.querySelectorAll('.scene-player')).toHaveLength(6)
    expect(container.querySelectorAll('.scene-trait')).toHaveLength(6)
    expect(container.textContent).not.toContain('Скрытое здоровье')
    expect(container.textContent).not.toContain('Скрытая заметка')
    expect(container.querySelector('.event-scroll')).toBeNull()
  })

  it('opens the full card through the participant control', () => {
    const onPlayer = vi.fn()
    render(fixture, null, onPlayer)
    act(() => container.querySelector<HTMLButtonElement>('.scene-player')!.click())
    expect(onPlayer).toHaveBeenCalledWith('p1')
  })

  it.each([['generating', '', 'Готовит ответ'], ['generating', 'Новый текст', 'Черновик'], ['validating', 'Проверяемый текст', 'Проверяем реплику'], ['discarded', 'Отброшенный текст', 'Попытка не принята'], ['interrupted', 'Прерванный текст', 'Поток прерван']] as const)('labels %s and hides a rejected draft', (status, text, expected) => {
    render(fixture, stream(status, text))
    expect(container.querySelector('.speech-bubble')?.textContent).toContain(expected)
    if (['discarded', 'interrupted'].includes(status)) expect(container.querySelector('.bubble-text')).toBeNull()
    else if (text) expect(container.querySelector('.bubble-text')?.textContent).toBe(text)
  })

  it('uses the accepted public event rather than a stale stream preview', () => {
    render({ ...fixture, history: [event('speech', { text: 'Принятая реплика' }, 'p2')] }, { ...stream('accepted', 'Устаревший черновик'), public_seq: 10 })
    expect(container.querySelector('.bubble-text')?.textContent).toBe('Принятая реплика')
    expect(container.textContent).not.toContain('Устаревший черновик')
    expect(container.querySelector('.scene-player.speaking')?.textContent).toContain('Участник 2')
  })

  it('keeps an accepted stream visible until its matching public event arrives', () => {
    const game = { ...fixture, history: [event('speech', { text: 'Предыдущая реплика' }, 'p2')] }
    const current = { ...stream('accepted', 'Новая принятая реплика'), public_seq: 14 }
    render(game, current)
    expect(container.querySelector('.bubble-text')?.textContent).toBe('Новая принятая реплика')
    expect(container.querySelector('.speech-bubble')?.textContent).toContain('Реплика принята')
    expect(container.querySelector('.draft-caption')).toBeNull()
    render({ ...game, history: [...game.history, { ...event('speech', { text: 'Новая принятая реплика' }, 'p1'), seq: 14 }] }, current)
    expect(container.querySelector('.bubble-text')?.textContent).toBe('Новая принятая реплика')
    expect(container.querySelector('.stream-state')).toBeNull()
  })

  it('ignores an interrupted preview older than a newly published accepted event', () => {
    render({ ...fixture, history: [event('speech', { text: 'Принятый ответ после восстановления' }, 'p2')] }, { ...stream('interrupted', 'Старый поток'), seq: 7 })
    expect(container.querySelector('.bubble-text')?.textContent).toBe('Принятый ответ после восстановления')
    expect(container.querySelector('.stream-state')).toBeNull()
    expect(container.textContent).not.toContain('Поток прерван')
  })

  it.each([['running', 'intents'], ['running', 'vote'], ['paused', 'speech'], ['completed', 'speech'], ['stopped', 'speech']])('does not mark the previous participant as speaking during %s / %s', (status, phase) => {
    render({ ...fixture, status, phase, history: [event('speech', { text: 'Уже закончил' }, 'p2')] })
    expect(container.querySelector('.scene-player.speaking')).toBeNull()
  })

  it('uses the historical projected speaker in a paused recording', () => {
    render(projectGame({ ...fixture, status: 'completed', history: [event('speech', { text: 'Реплика в записи' }, 'p3')] }, 10))
    expect(container.querySelector('.scene-player.speaking')?.textContent).toContain('Участник 3')
  })

  it('shows saved speech immediately without a stream label', () => {
    render({ ...fixture, status: 'completed', history: [event('speech', { text: 'Полный текст записи' }, 'p1')] })
    expect(container.querySelector('.bubble-text')?.textContent).toBe('Полный текст записи')
    expect(container.textContent).not.toContain('Черновик')
  })

  it('returns only the scene to the bubble on explicit recording navigation', () => {
    const game = { ...fixture, history: [event('speech', { text: 'Запись' }, 'p1')] }
    render(game)
    const scroller = container.querySelector<HTMLDivElement>('.scene-scroll')!
    const bubble = container.querySelector<HTMLDivElement>('.scene-bubble-slot')!
    vi.spyOn(scroller, 'getBoundingClientRect').mockImplementation(() => ({ top: 0, bottom: 400 }) as DOMRect)
    vi.spyOn(bubble, 'getBoundingClientRect').mockImplementation(() => ({ top: 16 - scroller.scrollTop, bottom: 300 - scroller.scrollTop }) as DOMRect)
    act(() => { scroller.scrollTop = 500; scroller.dispatchEvent(new WheelEvent('wheel', { bubbles: true })); scroller.dispatchEvent(new Event('scroll', { bubbles: true })) })
    render(game, null, vi.fn(), 1)
    expect(scroller.scrollTop).toBe(0)
    expect(container.querySelector('.return-to-speech')).toBeNull()
  })

  it('preserves manual reading position on a new accepted event and offers return', () => {
    const game = { ...fixture, history: [event('speech', { text: 'Первая реплика' }, 'p1')] }
    render(game)
    const scroller = container.querySelector<HTMLDivElement>('.scene-scroll')!
    const bubble = container.querySelector<HTMLDivElement>('.scene-bubble-slot')!
    vi.spyOn(scroller, 'getBoundingClientRect').mockImplementation(() => ({ top: 0, bottom: 400 }) as DOMRect)
    vi.spyOn(bubble, 'getBoundingClientRect').mockImplementation(() => ({ top: 16 - scroller.scrollTop, bottom: 300 - scroller.scrollTop }) as DOMRect)
    act(() => { scroller.scrollTop = 500; scroller.dispatchEvent(new WheelEvent('wheel', { bubbles: true })); scroller.dispatchEvent(new Event('scroll', { bubbles: true })) })
    render({ ...game, history: [...game.history, { ...event('speech', { text: 'Вторая реплика' }, 'p2'), seq: 20 }] })
    expect(scroller.scrollTop).toBe(500)
    expect(container.querySelector('.return-to-speech')?.textContent).toContain('К текущей реплике')
    act(() => container.querySelector<HTMLButtonElement>('.return-to-speech')!.click())
    expect(scroller.scrollTop).toBe(0)
  })

  it('starts a new bubble at its beginning, then follows streaming growth', () => {
    render(fixture, stream('generating', 'Начало'))
    const scroller = container.querySelector<HTMLDivElement>('.scene-scroll')!
    const bubble = container.querySelector<HTMLDivElement>('.scene-bubble-slot')!
    vi.spyOn(scroller, 'getBoundingClientRect').mockImplementation(() => ({ top: 0, bottom: 400 }) as DOMRect)
    vi.spyOn(bubble, 'getBoundingClientRect').mockImplementation(() => ({ top: 16 - scroller.scrollTop, bottom: 800 - scroller.scrollTop }) as DOMRect)
    render(fixture, { ...stream('generating', 'Новая длинная реплика'), call_id: 'new-call' })
    expect(scroller.scrollTop).toBe(0)
    render(fixture, { ...stream('generating', 'Новая длинная реплика продолжается'), call_id: 'new-call' })
    expect(scroller.scrollTop).toBe(416)
  })

  it('shows votes, elimination and final winners in the central bubble', () => {
    render({ ...fixture, history: [event('votes', { votes: [{ player_id: 'p1', candidate_id: 'p2', reason: 'Причина' }] })] })
    expect(container.querySelector('.speech-bubble')?.textContent).toContain('Участник 1 → Участник 2')
    render({ ...fixture, history: [event('elimination', { eliminated_id: 'p2', text: 'Решено' })], players: fixture.players.map(p => ({ ...p, alive: p.id !== 'p2' })) })
    expect(container.querySelectorAll('.scene-player.eliminated')).toHaveLength(1)
    expect(container.querySelector('.speech-bubble')?.textContent).toContain('Участник 2 остаётся снаружи')
    render({ ...fixture, status: 'completed', history: [event('epilogue', { text: 'Финал', winner_ids: ['p1', 'p2', 'p3'] })], winners: ['p1', 'p2', 'p3'] }, stream('generating', 'Устаревший поток'))
    expect(container.querySelectorAll('.scene-player.winner')).toHaveLength(3)
    expect(container.querySelector('.scene-player.speaking')).toBeNull()
    expect(container.textContent).not.toContain('Устаревший поток')
  })
})

describe('conversation drawer', () => {
  it('keeps its content mounted while hidden and closes with Escape', () => {
    const close = vi.fn()
    act(() => root.render(<ConversationPanel onClose={close}><p>Журнал</p></ConversationPanel>))
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Журнал')
    act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(close).toHaveBeenCalledOnce()
    act(() => root.render(<ConversationPanel open={false} onClose={close}><p>Журнал</p></ConversationPanel>))
    expect(document.querySelector('.conversation-backdrop')?.hasAttribute('hidden')).toBe(true)
    expect(document.querySelector('.conversation-panel')?.textContent).toContain('Журнал')
  })
})
