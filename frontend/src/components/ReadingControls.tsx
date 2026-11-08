import { useEffect, useState } from 'react'
import type { ReadingPause } from '../types'
import { motionTokens } from '../motionTokens'

export function ReadingControls({ reading, paused, busy, onNext }: { reading: ReadingPause; paused: boolean; busy: boolean; onNext: (seq: number) => void }) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined
    const update = () => setNow(Date.now())
    const visibility = () => {
      clearInterval(timer)
      update()
      if (!paused && document.visibilityState !== 'hidden') timer = setInterval(update, motionTokens.clockRefreshMs)
    }
    visibility()
    document.addEventListener('visibilitychange', visibility)
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', visibility) }
  }, [paused, reading.event_seq, reading.deadline])
  const seconds = paused || reading.deadline === null ? reading.remaining : Math.max(0, reading.deadline - now / 1000)
  const progress = reading.remaining > 0 ? Math.min(1, seconds / reading.remaining) : 0
  return <div className="reading-controls">
    <div className="reading-copy"><strong>{paused ? 'Чтение приостановлено' : 'Время на чтение'}</strong><span>{paused ? 'Таймер продолжится вместе с игрой' : seconds <= 0 ? 'Переходим к следующему ходу…' : 'Следующий ход начнётся автоматически'}</span></div>
    <span className="reading-time" role="timer" aria-live="off">{Math.ceil(seconds)} с</span>
    <button className="button" disabled={paused || busy || seconds <= 0} onClick={() => onNext(reading.event_seq)}>Дальше <span aria-hidden="true">→</span></button>
    <div className="reading-progress" aria-hidden="true"><i style={{ transform: `scaleX(${progress})` }} /></div>
  </div>
}
