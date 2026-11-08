import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { GameEvent, GameState, Player, SpeechStream } from '../types'
import { currentSpeaker, traitNames, valueText, votingTitle } from '../presentation'
import { Avatar } from './Avatar'
import { useSmoothedText } from '../useSmoothedText'

function PlayerPlace({ player, index, speaking, winner, onPlayer }: { player?: Player; index: number; speaking: boolean; winner: boolean; onPlayer: (id: string) => void }) {
  const status = winner ? '✦ В бункере' : !player ? 'Ожидает участника' : !player.alive ? '− Снаружи' : speaking ? '● Говорит' : 'В игре'
  return <button className={`scene-player seat ${speaking ? 'speaking' : ''} ${player && !player.alive ? 'eliminated' : ''} ${winner ? 'winner' : ''}`} disabled={!player}
    aria-label={player ? `${player.name}. ${status}. Открыть карточку` : `Место ${index + 1} ожидает участника`} onClick={() => player && onPlayer(player.id)}>
    <span className="scene-player-heading"><span className="scene-avatar"><Avatar index={index} size={48} /></span><span className="scene-player-name"><strong>{player?.name || `Участник ${index + 1}`}</strong><span>{status}</span></span><span className="card-hint" aria-hidden="true">↗</span></span>
    {player && player.revealed.length > 0 ? <span className="scene-traits">{player.revealed.filter(key => Object.hasOwn(player.traits, key)).map(key => <span className="scene-trait" key={key}><span>{traitNames[key] || key}</span><strong>{player.traits[key]}</strong></span>)}</span> : <span className="scene-traits-empty">Характеристики ещё не раскрыты</span>}
  </button>
}

function EventBubble({ event, game }: { event: GameEvent; game: GameState }) {
  const playerIndex = game.players.findIndex(player => player.id === event.actor_id)
  const player = game.players[playerIndex]
  const votes = Array.isArray(event.data.votes) ? event.data.votes as Record<string, unknown>[] : []
  const eliminated = game.players.find(candidate => candidate.id === event.data.eliminated_id)
  const final = event.kind === 'epilogue'
  const winnerIds = Array.isArray(event.data.winner_ids) ? event.data.winner_ids : []
  const name = (id: unknown) => game.players.find(candidate => candidate.id === id)?.name || String(id)
  const heading = player ? player.name : final ? 'Дверь бункера закрыта' : eliminated ? 'Решение принято' : votes.length ? votingTitle(event.data) : 'Ведущий'
  return <article className={`speech-bubble ${player ? `player-bubble ${playerIndex < 3 ? 'bubble-from-left' : 'bubble-from-right'}` : 'host-bubble'} ${final ? 'final-bubble' : ''} ${eliminated ? 'elimination-bubble' : ''}`} data-seq={event.seq}>
    <header className="bubble-heading">{player ? <Avatar index={playerIndex} size={44} /> : <span className="bubble-symbol" aria-hidden="true">{final ? '✦' : eliminated ? '↗' : votes.length ? '✓' : '✳'}</span>}<div><strong>{heading}</strong><span>{event.kind === 'defense' ? 'Защитная речь' : event.kind === 'closing' ? 'Последнее слово' : player ? 'За столом' : `Раунд ${event.round || 1}`}</span></div></header>
    {eliminated && <h2>{eliminated.name} остаётся снаружи</h2>}
    {final && <p className="bubble-winners">{game.players.filter(candidate => winnerIds.includes(candidate.id)).map(candidate => candidate.name).join(' · ')}</p>}
    {valueText(event.data.stage_direction) && <p className="stage-direction">{valueText(event.data.stage_direction)}</p>}
    {valueText(event.data.text) && <p className="bubble-text">{valueText(event.data.text)}</p>}
    {votes.length > 0 && <div className="bubble-votes">{votes.map((vote, i) => <details key={i}><summary>{name(vote.player_id)} <span>→ {name(vote.candidate_id)}</span></summary><p>{valueText(vote.reason)}</p></details>)}{valueText(event.data.reason) && <p className="muted">{valueText(event.data.reason)}</p>}</div>}
    {event.data.stage === 'preliminary' && <p className="muted">Никто ещё не изгнан. Лидеры получают защитное слово, затем все голосуют заново.</p>}
  </article>
}

export function GameScene({ game, stream, onPlayer, empty, navigation = 0 }: { game: GameState | null; stream: SpeechStream | null; onPlayer: (id: string) => void; empty: ReactNode; navigation?: number }) {
  const scroll = useRef<HTMLDivElement>(null)
  const bubble = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const programmatic = useRef(false)
  const [away, setAway] = useState(false)
  const final = Boolean(game?.winners.length)
  const terminal = game?.status === 'completed' || game?.status === 'stopped'
  const latest = game?.history.at(-1)
  const acceptedInHistory = stream?.status === 'accepted' && game?.history.some(event => event.seq === stream.public_seq)
  const obsoletePreview = stream && stream.status !== 'accepted' && stream.seq <= (latest?.seq || 0)
  const current = stream && !final && !terminal && !acceptedInHistory && !obsoletePreview ? stream : null
  const historicalSpeaker = game && 'activeSpeakerId' in game ? typeof game.activeSpeakerId === 'string' ? game.activeSpeakerId : null : game ? currentSpeaker(game) : null
  const previewSpeaking = current && !['discarded', 'interrupted'].includes(current.status) && game && ['running', 'pausing'].includes(game.status) && !['intents', 'vote', 'runoff', 'final_vote'].includes(game.phase)
  const speakerId = final || terminal ? null : previewSpeaking ? current.actor_id : historicalSpeaker
  const speakerIndex = game?.players.findIndex(player => player.id === current?.actor_id) ?? -1
  const speaker = game?.players[speakerIndex]
  const text = current && !['discarded', 'interrupted'].includes(current.status) ? current.text : ''
  const label = !current ? '' : current.status === 'accepted' ? 'Реплика принята' : current.status === 'discarded' ? 'Попытка не принята' : current.status === 'interrupted' ? 'Поток прерван' : current.status === 'validating' ? 'Проверяем реплику' : current.text ? 'Черновик' : 'Готовит ответ'
  const confirmedStream = !current && stream?.status === 'accepted' && latest?.seq === stream.public_seq ? stream : null
  const displayedStream = current || confirmedStream
  const messageKey = displayedStream ? `stream:${displayedStream.call_id}:${displayedStream.attempt}` : `event:${latest?.seq || 0}`
  const visibleText = useSmoothedText(messageKey, current ? text : valueText(latest?.data.text), Boolean(current && ['generating', 'validating'].includes(current.status)))
  const previous = useRef({ gameId: game?.id, messageKey, navigation, text: visibleText })

  useLayoutEffect(() => {
    const old = previous.current
    previous.current = { gameId: game?.id, messageKey, navigation, text: visibleText }
    if (old.gameId !== game?.id || old.navigation !== navigation) {
      returnToSpeech(false)
      return
    }
    if (old.messageKey !== messageKey) {
      if (following.current) returnToSpeech(false)
      return
    }
    if (old.text === visibleText) return
    if (!current || !following.current || !scroll.current || !bubble.current) return
    const el = scroll.current
    const box = bubble.current.getBoundingClientRect()
    const container = el.getBoundingClientRect()
    if (box.bottom > container.bottom) {
      programmatic.current = true
      el.scrollTop += box.bottom - container.bottom + 16
      requestAnimationFrame(() => { programmatic.current = false })
    }
  }, [game?.id, messageKey, text, visibleText, navigation])

  function returnToSpeech(focus: boolean) {
    const el = scroll.current
    if (el && bubble.current) {
      programmatic.current = true
      el.scrollTop = Math.max(0, el.scrollTop + bubble.current.getBoundingClientRect().top - el.getBoundingClientRect().top - 16)
      requestAnimationFrame(() => { programmatic.current = false })
    }
    following.current = true
    setAway(false)
    if (focus) bubble.current?.focus({ preventScroll: true })
  }

  return <div className="scene-container"><div ref={scroll} className="scene-scroll" tabIndex={0} aria-label="Игровая сцена" onWheel={() => { following.current = false }} onTouchMove={() => { following.current = false }} onScroll={() => {
    if (!scroll.current || !bubble.current) return
    const area = scroll.current.getBoundingClientRect()
    const box = bubble.current.getBoundingClientRect()
    const visible = box.bottom > area.top + 30 && box.top < area.bottom - 30
    if (!programmatic.current && !visible) following.current = false
    setAway(!visible || !following.current)
  }}>
    <section className="game-scene" aria-label="Участники за столом">
      <div className="scene-bubble-slot" ref={bubble} tabIndex={-1}>
        {current ? <article className={`speech-bubble streaming-bubble ${speaker ? `player-bubble ${speakerIndex < 3 ? 'bubble-from-left' : 'bubble-from-right'}` : 'host-bubble'} ${['discarded', 'interrupted'].includes(current.status) ? 'interrupted-bubble' : ''}`}>
          <header className="bubble-heading">{speaker ? <Avatar index={speakerIndex} size={44} /> : <span className="bubble-symbol" aria-hidden="true">✳</span>}<div><strong>{speaker?.name || 'Ведущий'}</strong><span className="stream-state" role="status">{label}{current.attempt > 1 ? ` · попытка ${current.attempt}` : ''}</span></div></header>
          {text ? <p className="bubble-text">{visibleText}</p> : <p className="bubble-waiting">{current.status === 'discarded' ? 'Этот ответ не добавлен в разговор.' : current.status === 'interrupted' ? 'Незавершённый ответ не добавлен в разговор.' : 'Слово уже у участника. Ждём первые строки…'}</p>}
          {text && current.status !== 'accepted' && <p className="draft-caption">Ответ станет частью игры после проверки.</p>}
        </article> : latest && game ? <EventBubble event={latest} game={game} /> : <div className="speech-bubble empty-bubble">{empty}</div>}
      </div>
      {Array.from({ length: 6 }, (_, index) => {
        const player = game?.players[index]
        return <div key={player?.id || index} className={`scene-place scene-place-${index + 1}`}><PlayerPlace player={player} index={index} speaking={Boolean(player && speakerId === player.id)} winner={Boolean(player && game?.winners.includes(player.id))} onPlayer={onPlayer} /></div>
      })}
    </section>
  </div>{away && (current || latest) && <button className="button return-to-speech" onClick={() => returnToSpeech(true)}>К текущей реплике ↑</button>}</div>
}
