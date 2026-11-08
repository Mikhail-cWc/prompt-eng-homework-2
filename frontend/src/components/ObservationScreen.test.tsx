// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GameEvent, GameState, SpeechStream } from '../types'
import { ObservationScreen } from './ObservationScreen'

const entry = (seq: number, kind: string, data: GameEvent['data'], round = 1, actor_id: string | null = null): GameEvent => ({ seq, kind, data, round, actor_id, created_at: '2026-10-24T12:00:00Z' })
const fixture: GameState = {
  id: 'screen-fixture', title: 'Тестовая запись', status: 'completed', round: 3, phase: 'done', created_at: '',
  players: Array.from({ length: 6 }, (_, index) => ({ id: `p${index + 1}`, name: ['Вера', 'Марк', 'Нина', 'Тимур', 'Ася', 'Глеб'][index], model: 'fixture-model', personality: 'Тестовый персонаж', traits: { profession: 'Врач', hobby: 'Шахматы' }, revealed: ['profession', 'hobby'], alive: index < 3, note: 'Итоговая заметка' })),
  scenario: null, queue: [], debate_count: 8, debate_elapsed: 600, error: null, operation: null, winners: ['p1', 'p2', 'p3'], config: {},
  history: [entry(3, 'narration', { text: 'Начало тестовой истории', event: 'Событие' }), entry(7, 'reveal', { text: 'Первая речь Веры', reveal: ['profession'], traits: { profession: 'Врач' } }, 1, 'p1'), entry(13, 'elimination', { eliminated_id: 'p6', text: 'Глеб ушёл' }), entry(17, 'narration', { text: 'Второе действие', event: 'Событие' }, 2), entry(21, 'epilogue', { text: 'Тестовый финал', winner_ids: ['p1', 'p2', 'p3'] }, 3)],
}

class MockEventSource {
  static instances: MockEventSource[] = []
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  listeners = new Map<string, (event: MessageEvent<string>) => void>()
  constructor(public url: string) { MockEventSource.instances.push(this) }
  addEventListener(kind: string, callback: (event: MessageEvent<string>) => void) { this.listeners.set(kind, callback) }
  close() {}
}

let root: ReturnType<typeof createRoot>
let container: HTMLDivElement
let snapshot: GameState
let emptyGames: boolean
let failNetwork: boolean
let configured: boolean
let readOnly: boolean
let streamSnapshot: SpeechStream | null
type MockFetch = (url: string, options?: RequestInit) => Promise<{ ok: boolean; status?: number; json: () => Promise<unknown> }>
let fetchMock: ReturnType<typeof vi.fn<MockFetch>>
const buttons = () => [...document.querySelectorAll<HTMLButtonElement>('button')]
function button(label: string) {
  const result = buttons().find(candidate => candidate.getAttribute('aria-label') === label || candidate.textContent?.includes(label))
  if (!result) throw new Error(`Missing button: ${label}`)
  return result
}
async function click(label: string) { await act(async () => { button(label).click() }) }
async function render() { await act(async () => { root.render(<ObservationScreen />) }) }
function expectReadOnly() { expect(fetchMock.mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true) }

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.useFakeTimers()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
  vi.stubGlobal('EventSource', MockEventSource)
  localStorage.clear()
  MockEventSource.instances = []
  snapshot = structuredClone(fixture)
  emptyGames = false
  failNetwork = false
  configured = true
  readOnly = false
  streamSnapshot = null
  fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method && options.method !== 'GET') throw new Error('Mutating requests forbidden by this recording test')
    if (failNetwork) throw new TypeError('Failed to fetch')
    let value: unknown
    if (url === '/api/health') value = { configured, read_only: readOnly }
    else if (url === '/api/games') value = emptyGames ? [] : [snapshot]
    else if (url === `/api/games/${snapshot.id}`) value = snapshot
    else if (url === `/api/games/${snapshot.id}/presentation`) value = { game: snapshot, stream: streamSnapshot, event_seq: Math.max(0, ...snapshot.history.map(e => e.seq), streamSnapshot?.seq || 0) }
    else if (url === `/api/games/${snapshot.id}/players/p1/inspector`) value = { note: 'Сохранённый план Веры', note_call: null, latest_call: { id: 'fixture-call', kind: 'reveal', status: 'completed', round: 1, phase: 'reveal', created_at: '2026-10-24T10:00:00Z' } }
    else if (url === `/api/games/${snapshot.id}/calls`) value = [{ id: 'fixture-call', actor_id: 'p1', model: 'fixture-model', kind: 'reveal', status: 'accepted', attempt: 1, created_at: '' }]
    else if (url === `/api/games/${snapshot.id}/calls/fixture-call`) value = { id: 'fixture-call', actor_id: 'p1', model: 'fixture-model', kind: 'reveal', status: 'accepted', attempt: 1, created_at: '', input: { context: { self: { note: 'Заметка этого вызова' } } }, output: { text: 'Ответ' }, raw_response: { fixture: true } }
    else throw new Error(`Unmocked request: ${url}`)
    return { ok: true, json: async () => structuredClone(value) }
  })
  vi.stubGlobal('fetch', fetchMock)
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('recording screen integration with mocked transport', () => {
  it('refreshes quietly if the reading timer expired while a skip was in flight', async () => {
    snapshot = { ...snapshot, status: 'running', phase: 'reveal', winners: [], history: fixture.history.slice(0, 2), reading: { event_seq: 7, remaining: 10, deadline: Date.now() / 1000 + 10 } }
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/commands')) {
        snapshot = { ...snapshot, reading: null }
        return { ok: false, status: 409, json: async () => ({ detail: 'Переход уже выполнен' }) }
      }
      return originalFetch(url, options)
    })
    await render()
    await click('Дальше')
    expect(document.querySelector('.reading-controls')).toBeNull()
    expect(document.querySelector('[role="alert"]')).toBeNull()
  })
  it('keeps the accepted speech while reading and sends an event-bound skip command', async () => {
    snapshot = { ...snapshot, status: 'running', phase: 'reveal', winners: [], history: fixture.history.slice(0, 2), reading: { event_seq: 7, remaining: 10, deadline: Date.now() / 1000 + 10 } }
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/commands')) {
        expect(JSON.parse(String(options?.body))).toEqual({ action: 'next', event_seq: 7 })
        snapshot = { ...snapshot, reading: null }
        return { ok: true, json: async () => structuredClone(snapshot) }
      }
      return originalFetch(url, options)
    })
    await render()
    expect(document.querySelector('.reading-controls')?.textContent).toContain('Время на чтение')
    expect(document.querySelector('.bubble-text')?.textContent).toBe('Первая речь Веры')
    expect(document.querySelector('.scene-player.speaking')).toBeNull()
    await click('Дальше')
    expect(document.querySelector('.reading-controls')).toBeNull()
    expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
  })
  it('streams drafts without snapshot requests or publishing reveals into the journal', async () => {
    snapshot = { ...snapshot, status: 'running', phase: 'speech', history: [fixture.history[0]], winners: [], players: snapshot.players.map(p => ({ ...p, alive: true, revealed: [] })) }
    await render()
    const source = MockEventSource.instances[0]
    expect(source.url).toContain('after=3')
    const initialRequests = fetchMock.mock.calls.length
    const preview = { call_id: 'stream-call', actor_id: 'p1', attempt: 1, kind: 'speech', status: 'generating', text: '' }
    async function emit(seq: number, data: Record<string, unknown>) {
      await act(async () => { source.listeners.get('update')?.(new MessageEvent('update', { data: JSON.stringify(entry(seq, 'speech_stream', data)) })) })
    }
    await emit(4, preview)
    await emit(5, { ...preview, text: 'Потоковая реплика' })
    expect(document.querySelector('.streaming-bubble')?.textContent).toContain('Потоковая реплика')
    expect(document.querySelector('.scene-traits')).toBeNull()
    expect(fetchMock.mock.calls.length).toBe(initialRequests)
    await click('Разговор')
    expect(document.querySelector('.event-feed')?.textContent).not.toContain('Потоковая реплика')
    expectReadOnly()
  })

  it('restores a live prefix and keeps a newer SSE update through an older polling snapshot', async () => {
    snapshot = { ...snapshot, status: 'running', phase: 'speech', history: [fixture.history[0]], winners: [] }
    streamSnapshot = { call_id: 'restored-call', actor_id: 'p1', attempt: 1, kind: 'speech', status: 'generating', text: 'Восстановленное начало', seq: 10 }
    await render()
    expect(MockEventSource.instances[0].url).toContain('after=10')
    await act(async () => { MockEventSource.instances[0].listeners.get('update')?.(new MessageEvent('update', { data: JSON.stringify(entry(11, 'speech_stream', { ...streamSnapshot, text: 'Восстановленное начало и продолжение' })) })) })
    await act(async () => { vi.advanceTimersByTime(5000) })
    expect(document.querySelector('.streaming-bubble')?.textContent).toContain('и продолжение')
    expectReadOnly()
  })

  it('keeps the conversation log hidden until requested even in a short viewport', async () => {
    await render()
    expect(document.querySelector('.event-feed')).toBeNull()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(document.querySelector('.speech-bubble')).not.toBeNull()
    expectReadOnly()
  })

  it('opens the journal without losing its cursor and exits with Escape', async () => {
    await render()
    await click('Следующее событие')
    await click('Воспроизвести запись')
    await click('Разговор')
    expect(document.querySelector('.conversation-backdrop:not([hidden])')).not.toBeNull()
    expect(document.querySelector('.event-feed')?.querySelectorAll('[data-seq]')).toHaveLength(2)
    expect(button('Воспроизвести запись')).toBeTruthy()
    await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(document.querySelector('.conversation-backdrop[hidden]')).not.toBeNull()
    expect(document.querySelector('.speech-bubble')?.getAttribute('data-seq')).toBe('7')
    expectReadOnly()
  })

  it('opens a completed recording at the first event paused without commands or eager call loading', async () => {
    await render()
    expect(document.querySelectorAll('[data-seq]')).toHaveLength(1)
    expect(document.body.textContent).toContain('Начало тестовой истории')
    expect(document.body.textContent).not.toContain('Тестовый финал')
    expect(document.body.textContent).toContain('6 в игре')
    expect(button('Воспроизвести запись').disabled).toBe(false)
    expect(buttons().some(candidate => candidate.textContent?.includes('Приостановить игру'))).toBe(false)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/calls'))).toBe(false)
    expectReadOnly()
  })

  it('steps, seeks to rounds and returns from the finale with the correct historical table', async () => {
    await render()
    await click('Следующее событие')
    expect(document.body.textContent).toContain('Первая речь Веры')
    expect(document.querySelector('.seat.speaking')?.textContent).toContain('Вера')
    const jump = document.querySelector<HTMLSelectElement>('.round-select select')!
    await act(async () => { jump.value = '3'; jump.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(document.body.textContent).toContain('Раунд 2 из 3')
    expect(document.querySelectorAll('.seat.eliminated')).toHaveLength(1)
    expect(document.body.textContent).not.toContain('Тестовый финал')
    await act(async () => { jump.value = '4'; jump.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(document.querySelectorAll('.seat.winner')).toHaveLength(3)
    expect(document.querySelector('.seat.speaking')).toBeNull()
    await act(async () => { jump.value = '0'; jump.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(document.querySelectorAll('.seat.eliminated, .seat.winner')).toHaveLength(0)
    expect(document.body.textContent).not.toContain('Тестовый финал')
    expectReadOnly()
  })

  it('loads the call archive only when opened and the raw context only after selecting a call', async () => {
    await render()
    await click('За кулисами')
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Архив всей партии')
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/calls'))).toBe(true)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/calls/fixture-call'))).toBe(false)
    await act(async () => { document.querySelector<HTMLButtonElement>('.call-row')!.click() })
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/calls/fixture-call'))).toBe(true)
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Фактический входной контекст')
    await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expectReadOnly()
  })

  it('shows saved memory on the card and lazily opens the actual input as a clearly labelled archive', async () => {
    await render()
    await act(async () => { document.querySelector<HTMLButtonElement>('.seat')!.click() })
    const dialog = document.querySelector('[role="dialog"]')!
    expect(dialog.textContent).toContain('Сохранённый план Веры')
    expect(dialog.textContent).toContain('Архив всей партии')
    expect(dialog.textContent).toContain('не относятся к выбранному моменту записи')
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/calls/fixture-call'))).toBe(false)
    const details = Array.from(dialog.querySelectorAll('details')).find(node => node.querySelector('summary')?.textContent === 'Что получил агент')!
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')) })
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/calls/fixture-call'))).toBe(true)
    expect(dialog.textContent).toContain('Заметка этого вызова')
    expect(dialog.textContent).toContain('Фактический входной контекст')
    const contextDetails = Array.from(dialog.querySelectorAll('details')).find(node => node.querySelector('summary')?.textContent === 'Фактический входной контекст')!
    await act(async () => { contextDetails.open = true; contextDetails.dispatchEvent(new Event('toggle')) })
    await click('Обновить память')
    expect(dialog.contains(contextDetails)).toBe(true)
    expect(contextDetails.open).toBe(true)
    expect(details.open).toBe(true)
    expectReadOnly()
  })

  it('preserves the selected card and cursor through snapshot refreshes and SSE reconnect duplicates', async () => {
    await render()
    await click('Следующее событие')
    await act(async () => { document.querySelector<HTMLButtonElement>('.seat')!.click() })
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Вера')
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('1 из 6 характеристик раскрыто')
    snapshot.history.push(structuredClone(snapshot.history[0]))
    await act(async () => { vi.advanceTimersByTime(5000) })
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Вера')
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('1 из 6 характеристик раскрыто')
    expect(document.querySelector('.speech-bubble')?.getAttribute('data-seq')).toBe('7')
    await act(async () => { MockEventSource.instances[0].listeners.get('update')?.(new MessageEvent('update', { data: JSON.stringify(entry(22, 'status', {})) })); vi.advanceTimersByTime(180) })
    expect(document.querySelector('.speech-bubble')?.getAttribute('data-seq')).toBe('7')
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/calls'))).toHaveLength(0)
    expectReadOnly()
  })
})

describe('visible operational states with mocked transport', () => {
  it('offers playback but no game creation in the public demo', async () => {
    configured = false
    readOnly = true
    await render()
    await click('Меню партии')
    expect(button('Воспроизвести запись').disabled).toBe(false)
    expect(document.body.textContent).not.toContain('Новая партия')
    expect(document.body.textContent).not.toContain('Подключите Yandex AI Studio')
    expectReadOnly()
  })

  it('shows the empty state and disables paid preparation when credentials are unavailable', async () => {
    emptyGames = true
    configured = false
    await render()
    expect(document.body.textContent).toContain('Шесть голосов. Три места.')
    expect(button('Подготовить партию').disabled).toBe(true)
    expectReadOnly()
  })

  it.each([
    ['preparing', 'setup', null, null, 'Готовим сценарий'],
    ['ready', 'opening', null, null, 'Начать игру'],
    ['running', 'speech', 'speech: p1', null, 'Вера готовит ответ'],
    ['paused', 'speech', null, null, 'Продолжить игру'],
    ['paused', 'speech', null, 'fixture technical failure', 'Техническая пауза. Можно продолжить'],
  ])('renders %s without firing a server command', async (status, phase, operation, error, expected) => {
    snapshot = { ...snapshot, status: status!, phase: phase!, operation, error, history: [] }
    await render()
    expect(document.body.textContent).toContain(expected)
    expect(document.querySelector('.replay-controls')).toBeNull()
    expectReadOnly()
  })

  it('shows loading before the first response and offers retry after a failed initial connection', async () => {
    let reject: (reason: Error) => void = () => {}
    fetchMock.mockImplementation(() => new Promise((_, fail) => { reject = fail }))
    await render()
    expect(document.body.textContent).toContain('Загружаем сохранённую партию')
    await act(async () => { reject(new TypeError('Failed to fetch')) })
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('Связь прервана')
    expect(button('Повторить')).toBeTruthy()
    expectReadOnly()
  })

  it('keeps the last record visible when the event connection is lost', async () => {
    await render()
    await act(async () => { MockEventSource.instances[0].onerror?.() })
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('Последние события сохранены')
    expect(document.querySelectorAll('[data-seq]')).toHaveLength(1)
    expectReadOnly()
  })
})
