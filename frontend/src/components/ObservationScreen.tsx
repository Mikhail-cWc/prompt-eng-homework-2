import { useCallback, useEffect, useRef, useState } from 'react'
import { api, safeMessage } from '../api'
import type { GameState, GameSummary } from '../types'
import { usePresentation } from '../usePresentation'
import { useReplay } from '../useReplay'
import { statusNames, waitingLabel } from '../presentation'
import { ConversationPanel } from './ConversationPanel'
import { DetailPanel } from './DetailPanel'
import { EventFeed } from './EventFeed'
import { GameScene } from './GameScene'
import { ReplayControls } from './ReplayControls'
import { ReadingControls } from './ReadingControls'

function savedGameId() { try { return localStorage.getItem('bunker-game') } catch { return null } }

export function ObservationScreen() {
  const [games, setGames] = useState<GameSummary[]>([])
  const [gameId, setGameId] = useState<string | null>(savedGameId)
  const [loaded, setLoaded] = useState(false)
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [panel, setPanel] = useState<'player' | 'backstage' | 'conversation' | null>(null)
  const [journalMounted, setJournalMounted] = useState(false)
  const [selectedPlayer, setSelectedPlayer] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [navigation, setNavigation] = useState(0)
  const menu = useRef<HTMLDivElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)

  const refreshGames = useCallback(async () => {
    const list = await api<GameSummary[]>('/api/games')
    setGames(list)
    return list
  }, [])
  const presentation = usePresentation(gameId, refreshGames)
  const game = presentation.game
  const replay = useReplay(game)
  const view = replay.view
  const initialize = useCallback(async () => {
    try {
      const [list, health] = await Promise.all([refreshGames(), api<{ configured: boolean }>('/api/health')])
      setConfigured(health.configured)
      setGameId(id => list.some(g => g.id === id) ? id : list[0]?.id || null)
      setError(null)
    } catch (e) { setError(safeMessage((e as Error).message)) }
    finally { setLoaded(true) }
  }, [refreshGames])
  useEffect(() => { void initialize() }, [initialize])
  useEffect(() => {
    setPanel(null)
    setJournalMounted(false)
    setSelectedPlayer(null)
    if (gameId) { try { localStorage.setItem('bunker-game', gameId) } catch { /* Storage can be disabled. */ } }
  }, [gameId])
  useEffect(() => {
    if (!menuOpen) return
    function dismiss(e: PointerEvent) { if (!menu.current?.contains(e.target as Node)) setMenuOpen(false) }
    function key(e: KeyboardEvent) { if (e.key === 'Escape') { setMenuOpen(false); menuButton.current?.focus() } }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', key) }
  }, [menuOpen])

  async function createGame() {
    setBusy(true)
    try {
      const next = await api<GameState>('/api/games', { method: 'POST', body: '{}' })
      setGameId(next.id)
      await refreshGames()
      setMenuOpen(false)
    } catch (e) { setError(safeMessage((e as Error).message)) }
    finally { setBusy(false) }
  }
  async function command(action: string, eventSeq?: number) {
    if (!gameId) return
    setBusy(true)
    try {
      presentation.replaceGame(await api<GameState>(`/api/games/${gameId}/commands`, { method: 'POST', body: JSON.stringify({ action, ...(eventSeq !== undefined ? { event_seq: eventSeq } : {}) }) }))
      await Promise.all([presentation.refresh(), refreshGames()])
      setMenuOpen(false)
      setError(null)
    } catch (e) {
      if (action === 'next' && e instanceof Error && 'status' in e && e.status === 409) {
        await presentation.refresh().catch(() => {})
        setError(null)
      } else setError(safeMessage((e as Error).message))
    }
    finally { setBusy(false) }
  }
  function choosePlayer(id: string) { setSelectedPlayer(id); setPanel('player') }
  function openJournal() { replay.pause(); setJournalMounted(true); setPanel('conversation') }
  const terminal = Boolean(game && ['completed', 'stopped'].includes(game.status))
  const alive = view?.players.filter(p => p.alive).length || 0
  const visibleError = error || presentation.error
  const loading = !loaded || Boolean(gameId && !game && !visibleError)
  const title = game?.scenario?.title || game?.title || 'Бункер'
  const status = game ? replay.isReplay ? 'Запись партии' : statusNames[game.status] || game.status : 'Игра LLM за три места'
  const empty = <div className="empty-state"><span className="empty-symbol" aria-hidden="true">✳</span><h2>{loading ? 'Собираемся за столом' : game ? game.status === 'preparing' ? 'У каждой истории своё начало' : 'Все за столом?' : 'Шесть голосов. Три места.'}</h2><p>{loading ? 'Загружаем сохранённую партию…' : game ? waitingLabel(game) : 'Модели спорят, договариваются и выбирают, кто останется. Вы наблюдаете за их историей.'}</p>{!game && loaded && !visibleError && <button className="button primary" disabled={busy || configured === false} onClick={createGame}>{busy ? 'Подготовка…' : 'Подготовить партию'}</button>}</div>
  const transport = replay.isReplay ? <ReplayControls {...replay} seek={index => { replay.seek(index); setNavigation(n => n + 1) }} step={delta => { replay.step(delta); setNavigation(n => n + 1) }} /> : game?.reading ? <ReadingControls reading={game.reading} paused={game.status !== 'running'} busy={busy} onNext={seq => void command('next', seq)} /> : <div className="live-status" role="status"><span className={game?.status === 'running' || game?.status === 'preparing' ? 'working-dot' : 'quiet-dot'} aria-hidden="true" />{game ? waitingLabel(game) : loading ? 'Подключаемся…' : 'Готовы к новой истории'}</div>

  return <div className="observation-shell">
    <header className="game-header"><div className="game-title"><span className="brand-symbol" aria-hidden="true">✳</span><div><h1>{title}</h1><div className="game-subtitle"><span>{status}</span>{view && <><span aria-hidden="true">·</span><span>Раунд {view.round || 1} из 3</span><span aria-hidden="true">·</span><span>{alive} в игре</span></>}</div></div></div>
      <div className="header-actions">{game && !terminal && ['ready', 'paused', 'running', 'pausing'].includes(game.status) && <button className="button primary live-control" disabled={busy || game.status === 'pausing'} onClick={() => command(game.status === 'ready' ? 'start' : game.status === 'paused' ? 'resume' : 'pause')}>{game.status === 'ready' ? '▶ Начать игру' : game.status === 'paused' ? '▶ Продолжить игру' : game.status === 'pausing' ? 'Завершаем ход…' : 'Ⅱ Приостановить игру'}</button>}
        <button className="button conversation-button" aria-label="Разговор" onClick={openJournal} disabled={!game}><span aria-hidden="true">☷</span><span className="conversation-button-label">Разговор</span></button>
        <button className="button backstage-button" onClick={() => setPanel('backstage')} disabled={!game}>За кулисами <span aria-hidden="true">↗</span></button>
        <div className="game-menu" ref={menu}><button ref={menuButton} className="icon-button" aria-label="Меню партии" aria-expanded={menuOpen} aria-controls="game-menu" onClick={() => setMenuOpen(v => !v)}>•••</button>{menuOpen && <div id="game-menu" className="menu-popover"><label>История партий<select aria-label="Выбрать партию" value={gameId || ''} onChange={e => { setGameId(e.target.value); setMenuOpen(false) }}><option value="" disabled>Выберите партию</option>{games.map(g => <option key={g.id} value={g.id}>{g.title} · {statusNames[g.status] || g.status}</option>)}</select></label><button className="backstage-menu-item" onClick={() => { setPanel('backstage'); setMenuOpen(false) }} disabled={!game}>За кулисами</button><button onClick={createGame} disabled={busy || Boolean(game && !terminal) || configured === false}>＋ Новая партия</button>{gameId && <><a href={`/api/games/${gameId}/export?format=markdown`} download>Скачать стенограмму</a><a href={`/api/games/${gameId}/export?format=json`} download>Скачать полный JSON</a></>}{game && !terminal && <button className="danger-text" disabled={busy} onClick={() => command('stop')}>Остановить партию</button>}</div>}</div>
      </div>
    </header>
    {(visibleError || presentation.connection === 'offline') && <div className="notice error-notice" role="alert"><div><strong>Связь прервана. Последние события сохранены.</strong>{visibleError && <details><summary>Техническая причина</summary><p>{visibleError}</p></details>}</div><button className="button" onClick={() => gameId ? void presentation.refresh().then(() => setError(null)).catch(e => setError(safeMessage(e.message))) : void initialize()}>Повторить</button></div>}
    {configured === false && <div className="notice">Подключите Yandex AI Studio в серверном .env, чтобы запустить новую игру. Записи доступны для просмотра.</div>}
    {game?.error && !terminal && <div className="notice error-notice" role="alert"><div><strong>Техническая пауза. Можно продолжить с текущего места.</strong><details><summary>Причина</summary><p>{safeMessage(game.error)}</p></details></div></div>}
    <main className="stage-workspace"><GameScene game={view} stream={replay.isReplay ? null : presentation.stream} navigation={navigation} onPlayer={choosePlayer} empty={empty} /></main>
    {panel !== 'conversation' && <footer className="game-footer">{transport}</footer>}
    {journalMounted && view && <ConversationPanel open={panel === 'conversation'} onClose={() => setPanel(null)} footer={panel === 'conversation' ? transport : undefined}><EventFeed gameId={gameId || 'empty'} history={view.history} players={view.players} replay={replay.isReplay} navigation={navigation} active={panel === 'conversation'} onPlayer={choosePlayer} empty={empty} /></ConversationPanel>}
    {panel && panel !== 'conversation' && view && <DetailPanel key={`${gameId}-${panel}-${selectedPlayer || ''}`} game={view} playerId={selectedPlayer} kind={panel} archive={replay.isReplay} onClose={() => setPanel(null)} />}
  </div>
}
