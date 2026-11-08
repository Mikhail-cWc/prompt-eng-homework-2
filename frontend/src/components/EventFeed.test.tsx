// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GameEvent } from '../types'
import { EventFeed } from './EventFeed'

const entry = (seq: number): GameEvent => ({ seq, kind: 'narration', round: 1, actor_id: null, data: { text: `Тестовое сообщение ${seq}` }, created_at: '2026-10-24T12:00:00Z' })
let root: ReturnType<typeof createRoot>
let container: HTMLDivElement
let history: GameEvent[]
function render(replay = false, navigation = 0, active = true) {
  act(() => root.render(<EventFeed gameId="feed-fixture" history={history} players={[]} replay={replay} navigation={navigation} active={active} onPlayer={() => {}} empty={<p>Пустая лента</p>} />))
}
function scroll() { return container.querySelector<HTMLDivElement>('.event-scroll')! }
function userScroll(top: number) { act(() => { scroll().scrollTop = top; scroll().dispatchEvent(new Event('scroll', { bubbles: true })) }) }

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(2000)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(500)
  history = [entry(3), entry(7)]
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('conversation scroll ownership', () => {
  it('opens a long new live reply at its beginning rather than hiding the beginning below the viewport', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      return { top: this.matches('[data-seq="7"]') ? 800 : 100 } as DOMRect
    })
    render()
    expect(scroll().scrollTop).toBe(688)
  })

  it('preserves reading above the end, counts new events and returns only the feed to live', () => {
    const windowScroll = vi.spyOn(window, 'scrollTo')
    render()
    userScroll(300)
    expect(container.textContent).toContain('К эфиру')
    history = [...history, entry(11), entry(15)]
    render()
    expect(scroll().scrollTop).toBe(300)
    expect(container.textContent).toContain('Новые события · 2')
    act(() => container.querySelector<HTMLButtonElement>('.new-events')!.click())
    expect(scroll().scrollTop).toBe(2000)
    expect(container.querySelector('.new-events')).toBeNull()
    expect(windowScroll).not.toHaveBeenCalled()
  })

  it('follows incoming events near the end and retains position for unchanged snapshots', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      return { top: this.matches('[data-seq="11"]') ? 80 : 0 } as DOMRect
    })
    render()
    userScroll(1470)
    history = [...history, entry(11)]
    render()
    expect(scroll().scrollTop).toBe(1538)
    userScroll(240)
    history = history.map(event => ({ ...event }))
    render()
    expect(scroll().scrollTop).toBe(240)
    expect(container.querySelector('.new-events')?.textContent).toContain('К эфиру')
  })

  it('returns recording navigation to its event without scrolling the document', () => {
    const windowScroll = vi.spyOn(window, 'scrollTo')
    render(true)
    userScroll(200)
    render(true, 1)
    expect(scroll().scrollTop).not.toBe(200)
    expect(windowScroll).not.toHaveBeenCalled()
    expect(container.textContent).not.toContain('К эфиру')
  })

  it('preserves exact near-end reading position when the journal is reopened without seeking', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      return { top: this.matches('[data-seq="7"]') ? 80 : 0 } as DOMRect
    })
    render()
    userScroll(1470.5)
    render(false, 0, false)
    render()
    expect(scroll().scrollTop).toBe(1470.5)
    expect(container.querySelector('.new-events')).toBeNull()
  })

  it('preserves reading and counts events received while the journal was closed', () => {
    render()
    userScroll(1470.5)
    render(false, 0, false)
    history = [...history, entry(11), entry(15)]
    render(false, 0, false)
    render()
    expect(scroll().scrollTop).toBe(1470.5)
    expect(container.querySelector('.new-events')?.textContent).toContain('Новые события · 2')
    history = [...history, entry(19)]
    render()
    expect(scroll().scrollTop).toBe(1470.5)
    expect(container.querySelector('.new-events')?.textContent).toContain('Новые события · 3')
  })

  it('honors an explicit seek made while the journal was closed', () => {
    render(true)
    userScroll(300)
    render(true, 0, false)
    render(true, 1, false)
    render(true, 1)
    expect(scroll().scrollTop).not.toBe(300)
  })

  it('renders an explicit empty feed without inventing events', () => {
    history = []
    render()
    expect(container.textContent).toContain('Пустая лента')
    expect(container.querySelector('[data-seq]')).toBeNull()
  })
})
