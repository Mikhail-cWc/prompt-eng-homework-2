import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, safeMessage } from '../api'
import type { GameState, ModelCall } from '../types'
import { Avatar } from './Avatar'
import { PlayerMemory } from './PlayerMemory'

interface DetailPanelProps {
  game: GameState
  playerId: string | null
  kind: 'player' | 'backstage'
  archive: boolean
  onClose: () => void
}

const traits: Record<string, string> = {
  profession: 'Профессия', health: 'Здоровье', skill: 'Навык',
  biography: 'Биография', hobby: 'Хобби', baggage: 'Багаж',
}
const callKinds: Record<string, string> = {
  intent: 'Заявка на слово', intents: 'Заявка на слово', speech: 'Реплика', reveal: 'Выступление и раскрытие',
  closing: 'Последнее слово', defense: 'Защитная речь', vote: 'Голос', final_vote: 'Решающий голос', runoff: 'Переголосование',
  narration: 'Ведущий', epilogue: 'Эпилог', world: 'Подготовка мира',
  character: 'Создание персонажа', probe: 'Проверка модели', scenario: 'Сценарий',
}
const intentKinds: Record<string, string> = {
  pass: 'Пропускает', answer: 'Ответ', object: 'Возражение', topic: 'Новая тема',
}
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
function pretty(value: unknown) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? 'Нет данных'
}

export function DetailPanel({ game, playerId, kind, archive, onClose }: DetailPanelProps) {
  const titleId = useId()
  const dialogRef = useRef<HTMLElement>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const [calls, setCalls] = useState<ModelCall[]>([])
  const [actorFilter, setActorFilter] = useState('all')
  const [selectedCall, setSelectedCall] = useState<ModelCall | null>(null)
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [archivedGame, setArchivedGame] = useState<GameState | null>(null)
  const [reload, setReload] = useState(0)
  const playerIndex = game.players.findIndex(player => player.id === playerId)
  const player = game.players[playerIndex]

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    if (!dialog) return
    const previousInert: [HTMLElement, boolean][] = []
    for (const node of Array.from(document.body.children)) {
      if (node instanceof HTMLElement && !node.contains(dialog)) {
        previousInert.push([node, node.inert])
        node.inert = true
      }
    }
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, summary, [tabindex="0"]'))
      .filter(element => !element.hasAttribute('disabled') && element.getClientRects().length > 0)
    focusable()[0]?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onCloseRef.current(); return }
      if (event.key !== 'Tab') return
      const elements = focusable()
      const first = elements[0]
      const last = elements[elements.length - 1]
      if (!first) { event.preventDefault(); dialog.focus(); return }
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('keydown', keydown)
      for (const [element, inert] of previousInert) element.inert = inert
      if (opener?.isConnected) opener.focus()
    }
  }, [])

  useEffect(() => {
    if (kind !== 'backstage') return
    let active = true
    setLoading(true)
    setError(null)
    const requests = [api<ModelCall[]>(`/api/games/${game.id}/calls`).then(value => { if (active) setCalls(value) })]
    if (archive) requests.push(api<GameState>(`/api/games/${game.id}`).then(value => { if (active) setArchivedGame(value) }))
    Promise.all(requests).catch(reason => { if (active) setError(safeMessage(reason.message)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [game.id, kind, archive, reload])

  const selectionVersion = useRef(0)
  useEffect(() => {
    selectionVersion.current += 1
    setSelectedCall(null)
    setDetailError(null)
    setDetailLoading(false)
  }, [actorFilter, game.id])
  useEffect(() => () => { selectionVersion.current += 1 }, [])
  async function inspect(call: ModelCall) {
    const version = ++selectionVersion.current
    setSelectedCall(call)
    setDetailError(null)
    setDetailLoading(true)
    try {
      const detail = await api<ModelCall>(`/api/games/${game.id}/calls/${call.id}`)
      if (selectionVersion.current === version) setSelectedCall(detail)
    } catch (reason) {
      if (selectionVersion.current === version) setDetailError(safeMessage(reason instanceof Error ? reason.message : reason))
    } finally {
      if (selectionVersion.current === version) setDetailLoading(false)
    }
  }
  const visibleCalls = calls.filter(call => actorFilter === 'all' || (actorFilter === 'host' ? !game.players.some(player => player.id === call.actor_id) : call.actor_id === actorFilter))
  const callContext = record(record(selectedCall?.input).context)
  const task = record(callContext.task)
  const output = record(selectedCall?.output)
  const own = record(callContext.self)
  const search = task.search_results
  const searchQuery = task.search_query ?? record(task.intent).search_query

  return createPortal(<div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <aside ref={dialogRef} className="drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <header className="drawer-header">
        <h2 id={titleId}>{kind === 'player' ? player?.name ?? 'Участник' : 'За кулисами'}</h2>
        <button className="icon-button" aria-label="Закрыть панель" onClick={onClose}>×</button>
      </header>
      <div className="drawer-body">
        {kind === 'player' && player && <>
          <div className="player-detail-heading">
            <Avatar index={playerIndex} size={76} />
            <div><strong>{game.winners.includes(player.id) ? '✓ Место в бункере' : player.alive ? '● В игре' : '− Снаружи, на откуп судьбе'}</strong><p className="muted">{player.revealed.length} из 6 характеристик раскрыто</p></div>
          </div>
          <p className="muted">Вы видите полную карточку как зритель. Другим игрокам доступны только раскрытые сведения.</p>
          <dl className="player-detail-traits">{Object.entries(player.traits).map(([key, value]) => {
            const isPublic = player.revealed.includes(key)
            return <div key={key} className={`trait-detail ${isPublic ? 'public' : 'secret'}`}>
              <dt>{traits[key] ?? key}<span>{isPublic ? '◉ Раскрыто игрокам' : '◇ Только зрителю'}</span></dt>
              <dd>{value}</dd>
            </div>
          })}</dl>
          <details className="detail-section"><summary>О персонаже и модели</summary><p>{player.personality}</p><p className="muted">{player.model}</p></details>
          <PlayerMemory key={`${game.id}:${player.id}`} gameId={game.id} actorId={player.id} archive={archive} revision={archive ? 'archive' : `${game.history.at(-1)?.seq ?? 0}:${game.phase}:${game.operation ?? ''}`} />
        </>}
        {kind === 'backstage' && <>
          {archive ? <div className="archive-note"><strong>Архив всей партии</strong><p>Здесь доступны все вызовы и итоговые заметки, включая события после выбранного момента записи. Они не описывают намерения игроков в прошлом.</p></div>
            : <section className="detail-section"><h3>Очередь слова</h3>{game.queue.length ? <ul className="queue-list">{game.queue.map(item => <li key={item.player_id}>
              <strong>{game.players.find(candidate => candidate.id === item.player_id)?.name ?? item.player_id}</strong><span> · {intentKinds[item.kind] ?? item.kind}{item.selected ? ' · слово предоставлено' : ''}</span>
              <p>{item.goal}</p>{item.reason && <p className="muted">{item.reason}</p>}
            </li>)}</ul> : <p className="muted">Сейчас открытой очереди нет.</p>}</section>}
          {game.scenario && <details className="detail-section"><summary>Условия партии</summary><p>{game.scenario.catastrophe}</p>{game.scenario.bunker != null && <p>{pretty(game.scenario.bunker)}</p>}</details>}
          <section className="detail-section"><div className="detail-section-heading"><h3>Вызовы моделей</h3><button className="button" onClick={() => setReload(value => value + 1)} disabled={loading}>Обновить</button></div>
            <label className="call-filter">Участник<select value={actorFilter} onChange={event => setActorFilter(event.target.value)}><option value="all">Все участники и ведущий</option><option value="host">Ведущий и подготовка</option>{game.players.map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select></label>
            {loading && <p role="status">Загружаем журнал…</p>}
            {error && <div role="alert"><p>Не удалось загрузить архив.</p><details><summary>Техническая причина</summary><p>{error}</p></details><button className="button" onClick={() => setReload(value => value + 1)}>Повторить</button></div>}
            {!loading && !error && visibleCalls.length === 0 && <p className="muted">Сохранённых вызовов пока нет.</p>}
            <div className="call-list">{[...visibleCalls].reverse().map(call => <button key={call.id} className={`call-row ${selectedCall?.id === call.id ? 'selected' : ''}`} aria-pressed={selectedCall?.id === call.id} onClick={() => { void inspect(call) }}>
              <span><strong>{game.players.find(candidate => candidate.id === call.actor_id)?.name ?? 'Ведущий / подготовка'}</strong><span>{callKinds[call.kind] ?? call.kind}</span></span>
              <span className="muted">{['accepted', 'completed'].includes(call.status) ? '✓ Принят' : call.status === 'failed' ? '⚠ Ошибка' : call.status}{call.attempt > 1 ? ` · попытка ${call.attempt}` : ''}</span>
            </button>)}</div>
          </section>
          {selectedCall && <section className="detail-section" aria-label="Выбранный вызов">
            <h3>{callKinds[selectedCall.kind] ?? selectedCall.kind}</h3>
            {detailLoading && <p role="status">Загружаем вход и ответ…</p>}
            {detailError && <div role="alert"><p>Не удалось открыть вызов.</p><details><summary>Техническая причина</summary><p>{detailError}</p></details><button className="button" onClick={() => { void inspect(selectedCall) }}>Повторить</button></div>}
            {!detailLoading && !detailError && <>
              <p className="muted">{selectedCall.model} · {new Date(selectedCall.created_at).toLocaleString('ru-RU')}{selectedCall.duration_ms != null ? ` · ${(selectedCall.duration_ms / 1000).toFixed(1)} с` : ''}</p>
              {(output.note || own.note) && <div className="archive-note"><strong>Заявленное намерение в этом вызове</strong><p>{String(output.note ?? own.note)}</p></div>}
              {typeof searchQuery === 'string' && <p>Поисковый запрос: {searchQuery}</p>}
              {typeof output.search_query === 'string' && <p>Запрошен поиск: {output.search_query}</p>}
              {search != null && <details className="detail-section" open><summary>Результат поиска по документам</summary><pre>{pretty(search)}</pre></details>}
              <details className="detail-section"><summary>Фактический входной контекст</summary><pre>{pretty(selectedCall.input)}</pre></details>
              <details className="detail-section"><summary>Принятое действие</summary><pre>{pretty(selectedCall.output)}</pre></details>
              <details className="detail-section"><summary>Исходный ответ модели</summary><pre>{pretty(selectedCall.raw_response)}</pre></details>
              <details className="detail-section"><summary>Статистика и сведения о запросе</summary><pre>{pretty({ id: selectedCall.id, status: selectedCall.status, attempt: selectedCall.attempt, duration_ms: selectedCall.duration_ms, usage: selectedCall.usage, error: selectedCall.error })}</pre></details>
            </>}
          </section>}
          {archive && archivedGame && <details className="detail-section"><summary>Итоговые личные заметки · архив</summary>{archivedGame.players.map(candidate => <section key={candidate.id}><h4>{candidate.name}</h4><p>{candidate.note || 'Заметка не сохранена.'}</p></section>)}</details>}
        </>}
      </div>
    </aside>
  </div>, document.body)
}
