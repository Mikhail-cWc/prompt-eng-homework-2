import type { GameEvent } from '../types'

interface Props {
  history: GameEvent[]; index: number; playing: boolean; speed: number;
  seek: (index: number) => void; step: (delta: number) => void;
  toggle: () => void; setSpeed: (speed: number) => void
}
export function ReplayControls({ history, index, playing, speed, seek, step, toggle, setSpeed }: Props) {
  const rounds = history.filter((event, i) => !i || event.round !== history[i - 1].round)
  const last = Math.max(0, history.length - 1)
  return <section className="replay-controls" aria-label="Проигрыватель записи">
    <div className="replay-actions">
      <button className="button primary replay-play" onClick={toggle} disabled={!history.length} aria-label={playing ? 'Пауза записи' : 'Воспроизвести запись'}>{playing ? 'Ⅱ' : '▶'}<span>{playing ? 'Пауза записи' : 'Смотреть запись'}</span></button>
      <button className="icon-button" onClick={() => step(-1)} disabled={index <= 0} aria-label="Предыдущее событие">←</button>
      <button className="icon-button" onClick={() => step(1)} disabled={index >= last} aria-label="Следующее событие">→</button>
      <label className="speed-select"><span className="sr-only">Скорость записи</span><select value={speed} onChange={e => setSpeed(Number(e.target.value))}><option value={0.5}>0,5×</option><option value={1}>1×</option><option value={2}>2×</option></select></label>
      <label className="round-select"><span className="sr-only">Переход по записи</span><select value="" onChange={e => { if (e.target.value) seek(Number(e.target.value)) }}><option value="" disabled>Перейти…</option><option value="0">К началу</option>{rounds.map(e => <option key={e.seq} value={history.findIndex(v => v.seq === e.seq)}>Раунд {e.round || 1}</option>)}<option value={last}>К финалу</option></select></label>
      <span className="replay-position">{history.length ? index + 1 : 0} / {history.length}</span>
    </div>
    <div className="timeline"><span className="sr-only" id="timeline-legend">Круглые отметки — голосования, вертикальные — исключения.</span><input aria-label="Позиция записи" aria-describedby="timeline-legend" aria-valuetext={`Событие ${index + 1} из ${history.length}, раунд ${history[index]?.round || 1}`} type="range" min={0} max={last} value={Math.max(0, index)} onChange={e => seek(Number(e.target.value))} disabled={!history.length} />
      <div className="timeline-marks" aria-hidden="true">{history.map((e, i) => ['votes', 'elimination'].includes(e.kind) && <i key={e.seq} className={e.kind} style={{ left: `${last ? i / last * 100 : 0}%` }} />)}</div>
    </div>
  </section>
}
