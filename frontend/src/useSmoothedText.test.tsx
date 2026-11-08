// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSmoothedText } from './useSmoothedText'
import { ReadingControls } from './components/ReadingControls'

let root: ReturnType<typeof createRoot>
let container: HTMLDivElement
let reduced = false
const mediaListeners = new Set<() => void>()
function Probe({ id, text, enabled }: { id: string; text: string; enabled: boolean }) {
  return <p>{useSmoothedText(id, text, enabled)}</p>
}
function render(text: string, id = 'call-1', enabled = true) { act(() => root.render(<Probe id={id} text={text} enabled={enabled} />)) }
function advance(ms: number) { act(() => { vi.advanceTimersByTime(ms) }) }
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(100000)
  reduced = false
  mediaListeners.clear()
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(performance.now()), 16))
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id))
  vi.stubGlobal('matchMedia', () => ({ get matches() { return reduced }, addEventListener: (_: string, cb: () => void) => mediaListeners.add(cb), removeEventListener: (_: string, cb: () => void) => mediaListeners.delete(cb) }))
  container = document.createElement('div'); document.body.append(container)
  root = createRoot(container)
})
afterEach(() => { act(() => root.unmount()); container.remove(); vi.useRealTimers(); vi.unstubAllGlobals() })

describe('received streaming text smoothing', () => {
  it('interpolates only received text, drains promptly and never changes a grapheme', () => {
    render('')
    const text = 'Привет, мир! 👩‍🔬 Ещё несколько слов.'
    render(text)
    advance(64)
    expect(container.textContent!.length).toBeGreaterThan(0)
    expect(container.textContent!.length).toBeLessThan(text.length)
    expect(text.startsWith(container.textContent!)).toBe(true)
    advance(200)
    expect(container.textContent).toBe(text)
  })
  it('keeps prefixes monotonic and resets immediately for a new attempt or rejection', () => {
    render('')
    render('Первая полученная часть')
    advance(64)
    const prefix = container.textContent!
    render('Первая полученная часть и продолжение')
    expect(container.textContent!.startsWith(prefix)).toBe(true)
    render('', 'call-2')
    advance(200)
    expect(container.textContent).toBe('')
    render('Следующая попытка', 'call-2')
    advance(32)
    render('', 'call-2', false)
    advance(300)
    expect(container.textContent).toBe('')
  })
  it('shows records, accepted text and reduced-motion text immediately', () => {
    render('', 'record', false)
    render('Полная запись', 'record', false)
    expect(container.textContent).toBe('Полная запись')
    render('', 'live')
    reduced = true
    act(() => { mediaListeners.forEach(cb => cb()) })
    render('Полученный текст', 'live')
    expect(container.textContent).toBe('Полученный текст')
  })
})

describe('reading countdown', () => {
  it('counts down, skips only its event and freezes on pause', () => {
    const next = vi.fn()
    act(() => root.render(<ReadingControls reading={{ event_seq: 17, remaining: 10, deadline: 110 }} paused={false} busy={false} onNext={next} />))
    expect(container.textContent).toContain('10 с')
    advance(2000)
    expect(container.textContent).toContain('8 с')
    act(() => container.querySelector('button')!.click())
    expect(next).toHaveBeenCalledWith(17)
    act(() => root.render(<ReadingControls reading={{ event_seq: 17, remaining: 8, deadline: null }} paused busy={false} onNext={next} />))
    advance(5000)
    expect(container.textContent).toContain('Чтение приостановлено')
    expect(container.querySelector('button')!.disabled).toBe(true)
  })
})
