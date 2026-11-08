import { useEffect, useState } from 'react'
import { api, safeMessage } from '../api'
import type { ModelCall } from '../types'

interface CallMoment {
  id: string
  kind: string
  status: string
  round: number | null
  phase: string | null
  created_at: string
}
interface Inspection {
  note: string
  note_call: CallMoment | null
  latest_call: CallMoment | null
}
const phases: Record<string, string> = {
  reveal: 'Раскрытие', intents: 'Заявка на слово', speech: 'Дискуссия',
  closing: 'Последнее слово', vote: 'Голосование', defense: 'Защита',
  final_vote: 'Решающее голосование', runoff: 'Переголосование',
}
function moment(call: CallMoment) {
  return `Раунд ${call.round ?? '—'} · ${phases[call.phase ?? ''] ?? call.kind} · ${new Date(call.created_at).toLocaleString('ru-RU')}`
}
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function PlayerMemory({ gameId, actorId, archive, revision }: {
  gameId: string; actorId: string; archive: boolean; revision: string
}) {
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [open, setOpen] = useState(false)
  const [call, setCall] = useState<ModelCall | null>(null)
  const [contextError, setContextError] = useState<string | null>(null)
  const [retryContext, setRetryContext] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    api<Inspection>(`/api/games/${gameId}/players/${actorId}/inspector`)
      .then(value => { if (active) setInspection(value) })
      .catch(reason => { if (active) setError(safeMessage(reason.message)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [gameId, actorId, revision, reload])
  const latest = inspection?.latest_call
  useEffect(() => {
    if (!open || !latest) return
    let active = true
    setCall(null)
    setContextError(null)
    api<ModelCall>(`/api/games/${gameId}/calls/${latest.id}`)
      .then(value => { if (active) setCall(value) })
      .catch(reason => { if (active) setContextError(safeMessage(reason.message)) })
    return () => { active = false }
  }, [gameId, latest?.id, open, retryContext])
  const input = record(call?.input)
  const context = record(input.context)
  const own = record(context.self)
  const publicHistory = Array.isArray(context.history) ? context.history : []
  return <section className="detail-section player-memory" aria-label="Память участника">
    <div className="detail-section-heading"><h3>Память участника</h3><button className="button" disabled={loading} onClick={() => setReload(value => value + 1)}>Обновить память</button></div>
    {archive && <p className="archive-note"><strong>Архив всей партии.</strong> Последняя заметка и последний вызов не относятся к выбранному моменту записи.</p>}
    {loading && <p role="status" className="muted">{inspection ? 'Обновляем сохранённую память…' : 'Загружаем сохранённую память…'}</p>}
    {error && <div role="alert"><p>Не удалось загрузить память.</p><details><summary>Техническая причина</summary><p>{error}</p></details></div>}
    {inspection && <>
      <h4>Сохранённый план</h4>
      <p className="memory-note">{inspection.note || 'Игрок ещё не сохранил личный план.'}</p>
      {inspection.note_call && <p className="muted memory-moment">{moment(inspection.note_call)}</p>}
      <p className="muted">Краткая заметка из принятого действия. Это заявленное намерение агента, а не скрытая цепочка рассуждений.</p>
      {latest ? <details className="detail-section" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
        <summary>Что получил агент</summary>
        <p className="muted memory-moment">Последний вызов · {moment(latest)}</p>
        <p>{latest.status === 'completed' ? '✓ Ответ принят' : latest.status === 'failed' ? '⚠ Ответ отклонён. Память игрока не обновлена.' : latest.status === 'running' ? '◌ Ответ ещё готовится' : '⚠ Выполнение запроса не подтверждено'}</p>
        {contextError ? <div role="alert"><p>Не удалось открыть контекст.</p><details><summary>Техническая причина</summary><p>{contextError}</p></details><button className="button" onClick={() => setRetryContext(value => value + 1)}>Повторить загрузку контекста</button></div>
          : !call || call.id !== latest.id ? <p role="status">Загружаем вход модели…</p> : <>
            <p className="muted">В переданной истории: {publicHistory.length} событий. Собственная карточка доступна полностью; сведения о других — только публичные.</p>
            <h4>Заметка на входе этого вызова</h4><p>{String(own.note || 'Пустая заметка')}</p>
            <details className="detail-section"><summary>Фактический входной контекст</summary><pre>{JSON.stringify(context, null, 2)}</pre></details>
            <details className="detail-section"><summary>Инструкции и ограничения ответа</summary><pre>{String(input.wire_instructions ?? input.instructions ?? 'Нет сохранённых инструкций')}</pre><pre>{JSON.stringify({ schema: input.schema, parameters: input.parameters }, null, 2)}</pre></details>
            {input.correction != null && <details className="detail-section"><summary>Обратная связь для исправления</summary><pre>{String(input.correction)}</pre></details>}
          </>}
      </details> : <p className="muted">Игровых вызовов этого участника пока нет.</p>}
    </>}
  </section>
}
