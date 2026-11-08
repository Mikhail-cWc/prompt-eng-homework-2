import type { GameState } from './types'

export const traitNames: Record<string, string> = {
  profession: 'Профессия', health: 'Здоровье', skill: 'Навык',
  biography: 'Биография', hobby: 'Хобби', baggage: 'Багаж',
}
export const statusNames: Record<string, string> = {
  preparing: 'Подготовка', ready: 'Готова к старту', running: 'Игра идёт',
  pausing: 'Завершаем текущий ход', paused: 'Игра на паузе',
  completed: 'Партия завершена', stopped: 'Партия остановлена',
}
export const phaseNames: Record<string, string> = {
  opening: 'Начало раунда', reveal: 'Знакомство', intents: 'Заявки на слово',
  speech: 'Обсуждение', debate: 'Обсуждение', closing: 'Последнее слово',
  vote: 'Голосование', defense: 'Защитная речь', final_vote: 'Решающее голосование', runoff: 'Повторное голосование', eliminate: 'Решение группы',
  aftermath: 'После голосования', advance: 'Следующий раунд', epilogue: 'Финал', done: 'Финал',
  preflight: 'Проверка моделей', setup: 'Подготовка сценария',
}
export function valueText(value: unknown) { return typeof value === 'string' ? value : '' }
export function currentSpeaker(game: GameState): string | null {
  if (game.reading || game.status !== 'running' || ['intents', 'vote', 'runoff', 'final_vote'].includes(game.phase)) return null
  const [kind, operationActor] = (game.operation || '').split(':').map(v => v.trim())
  if (['reveal', 'speech', 'closing', 'defense'].includes(kind) && game.players.some(p => p.id === operationActor)) return operationActor || null
  const last = game.history.at(-1)
  return last && ['reveal', 'speech', 'closing', 'defense'].includes(last.kind) ? last.actor_id || null : null
}
export function waitingLabel(game: GameState): string {
  if (game.status === 'paused') return game.error ? 'Техническая пауза. Партия сохранена.' : 'Игра на паузе'
  if (game.status === 'ready') return 'Все участники готовы. Можно начинать.'
  if (game.status === 'pausing') return 'Завершаем текущую операцию перед паузой'
  if (['intents', 'vote', 'runoff', 'final_vote'].includes(game.phase)) {
    const last = [...game.history].reverse().find(e => ['speech', 'reveal'].includes(e.kind))
    const eligible = game.players.filter(p => p.alive && (game.phase !== 'intents' ||
      (p.id !== last?.actor_id && (game.debate_counts?.[p.id] || 0) < 2)))
    const count = eligible.filter(p => Object.hasOwn(game.pending || {}, p.id)).length
    return `Получено ${count} из ${eligible.length} ${game.phase === 'intents' ? 'заявок' : 'голосов'}`
  }
  const [kind, actor] = (game.operation || '').split(':').map(v => v.trim())
  const name = game.players.find(p => p.id === actor)?.name
  if (name) return `${name} ${kind === 'vote' ? 'выбирает кандидата' : 'готовит ответ'}`
  if (kind === 'world' || kind === 'scenario') return 'Сценарист готовит мир и условия убежища'
  if (kind === 'character') return 'Знакомимся с будущими участниками'
  if (kind === 'probe') return 'Проверяем доступность моделей'
  if (game.status === 'preparing') return 'Готовим сценарий и карточки участников'
  return `${phaseNames[game.phase] || 'Следующий ход'} · ожидаем решение`
}

export function votingTitle(data: Record<string, unknown>): string {
  return data.stage === 'preliminary' ? 'Предварительное голосование'
    : data.stage === 'final' ? 'Решающее голосование'
    : data.runoff ? 'Повторное голосование' : 'Голосование'
}
