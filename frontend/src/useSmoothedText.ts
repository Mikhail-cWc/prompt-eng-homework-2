import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { motionTokens } from './motionTokens'

function canAnimate() {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' &&
    !window.matchMedia('(prefers-reduced-motion: reduce)').matches && document.visibilityState !== 'hidden'
}

function graphemes(text: string) {
  return typeof Intl.Segmenter === 'function'
    ? [...new Intl.Segmenter('ru', { granularity: 'grapheme' }).segment(text)].map(part => part.segment)
    : Array.from(text)
}

export function useSmoothedText(key: string, source: string, enabled: boolean): string {
  const [allowed, setAllowed] = useState(canAnimate)
  const [visible, setVisible] = useState({ key, text: source })
  const current = useRef(visible)

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setAllowed(canAnimate())
    media.addEventListener('change', update)
    document.addEventListener('visibilitychange', update)
    return () => { media.removeEventListener('change', update); document.removeEventListener('visibilitychange', update) }
  }, [])

  useLayoutEffect(() => {
    function commit(text: string) {
      current.current = { key, text }
      setVisible(current.current)
    }
    if (current.current.key !== key || !enabled || !allowed || !source.startsWith(current.current.text)) {
      commit(source)
      return
    }
    if (source === current.current.text) return
    const parts = graphemes(source)
    const start = graphemes(current.current.text).length
    const started = performance.now()
    let frame: number
    const tick = (time: number) => {
      const progress = Math.min(1, Math.max(0, (time - started) / motionTokens.streamBlendMs))
      const count = start + Math.floor((parts.length - start) * progress)
      const text = parts.slice(0, count).join('')
      if (text !== current.current.text) commit(text)
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [key, source, enabled, allowed])

  return visible.key === key && enabled && allowed ? visible.text : source
}
