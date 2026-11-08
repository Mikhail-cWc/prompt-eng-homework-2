import { useLayoutEffect, useRef, useState } from 'react'
import type { GameEvent, Player } from '../types'
import { traitNames, valueText, votingTitle } from '../presentation'
import { Avatar } from './Avatar'

function EventEntry({ event, players, onPlayer, latest }: { event: GameEvent; players: Player[]; onPlayer: (id: string) => void; latest: boolean }) {
  const index = players.findIndex(p => p.id === event.actor_id)
  const player = players[index]
  const data = event.data
  const eliminated = players.find(p => p.id === data.eliminated_id)
  const votes = Array.isArray(data.votes) ? data.votes as Record<string, unknown>[] : []
  const revealed = data.traits && typeof data.traits === 'object' ? Object.entries(data.traits) : []
  const addressed = Array.isArray(data.addressed_to) ? data.addressed_to.map(id => players.find(p => p.id === id)?.name || id) : []
  const finale = event.kind === 'epilogue'
  const winnerIds = Array.isArray(data.winner_ids) ? data.winner_ids : []
  const tally = votes.reduce<Record<string, number>>((acc, vote) => { const id = String(vote.candidate_id); acc[id] = (acc[id] || 0) + 1; return acc }, {})
  const extras = <>{valueText(data.stage_direction) && <p className="stage-direction">{valueText(data.stage_direction)}</p>}{revealed.length > 0 && <dl className="reveal-traits">{revealed.map(([key, value]) => <div key={key}><dt>{traitNames[key] || key}</dt><dd>{String(value)}</dd></div>)}</dl>}</>
  return <article className={`event-entry ${latest ? 'latest-event' : ''} ${player ? 'dialogue' : 'host-event'} ${eliminated ? 'exit-event' : ''} ${finale ? 'final-event' : ''}`} data-seq={event.seq}>
    <div className="entry-avatar">{player ? <button className="avatar-button" onClick={() => onPlayer(player.id)} aria-label={`Карточка: ${player.name}`}><Avatar index={index} size={38} /></button> : <span className="host-symbol" aria-hidden="true">{finale ? '✦' : eliminated ? '↗' : votes.length ? '✓' : '✳'}</span>}</div>
    <div className="entry-body"><div className="entry-heading">{player ? <button className="actor-name" onClick={() => onPlayer(player.id)}>{player.name}</button> : <strong>{finale ? 'Дверь бункера закрыта' : eliminated ? 'Решение принято' : votes.length ? votingTitle(data) : 'Ведущий'}</strong>}{['closing', 'defense'].includes(event.kind) && <span className="entry-kind">{event.kind === 'defense' ? 'Защитная речь' : 'Последнее слово'}</span>}</div>
      {addressed.length > 0 && <p className="addressed">К {addressed.join(', ')}</p>}
      <div className="event-extras">{extras}</div>
      {eliminated && <h3>{eliminated.name} остаётся снаружи</h3>}
      {finale && <p className="winner-names">{players.filter(p => winnerIds.includes(p.id)).map(p => p.name).join(' · ')}</p>}
      {valueText(data.text) && <p className="spoken-text">{valueText(data.text)}</p>}
      {(revealed.length > 0 || valueText(data.stage_direction)) && <details className="compact-extras"><summary>{revealed.length ? `Раскрытые характеристики · ${revealed.length}` : 'Ремарка участника'}</summary>{extras}</details>}
      {votes.length > 0 && <><div className="vote-tally">{Object.entries(tally).sort((a, b) => b[1] - a[1]).map(([id, count]) => <span key={id}>{players.find(p => p.id === id)?.name || id}<b>{count}</b></span>)}</div><div className="vote-directions">{votes.map((vote, i) => <details key={i}><summary>{players.find(p => p.id === vote.player_id)?.name || String(vote.player_id)} <span>→ {players.find(p => p.id === vote.candidate_id)?.name || String(vote.candidate_id)}</span></summary><p>{String(vote.reason || '')}</p></details>)}</div>{valueText(data.reason) && <p className="muted">{valueText(data.reason)}</p>}</>}
      <details className="event-metadata"><summary>Подробности события</summary><p>Событие №{event.seq} · Раунд {event.round} · <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString('ru-RU')}</time></p></details>
    </div>
  </article>
}

export function EventFeed({ gameId, history, players, replay, navigation = 0, active = true, onPlayer, empty }: {
  gameId: string; history: GameEvent[]; players: Player[]; replay: boolean; navigation?: number; active?: boolean; onPlayer: (id: string) => void; empty: React.ReactNode
}) {
  const scroll = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const programmatic = useRef(false)
  const readingTop = useRef(0)
  const previous = useRef({ id: gameId, seq: 0, count: 0, navigation, active: false, opened: false })
  const [unread, setUnread] = useState(0)
  const [atEnd, setAtEnd] = useState(true)
  const lastSeq = history.at(-1)?.seq || 0
  useLayoutEffect(() => {
    const el = scroll.current
    if (!el) return
    const old = previous.current
    if (!active) {
      previous.current = { ...old, active: false }
      return
    }
    const changedGame = old.id !== gameId
    const backwards = lastSeq < old.seq
    const reopening = old.opened && !old.active && !changedGame
    const appended = lastSeq > old.seq
    if (changedGame || backwards || old.navigation !== navigation || !old.opened || (!reopening && appended && following.current)) {
      programmatic.current = true
      const entry = el.querySelector<HTMLElement>(`[data-seq="${lastSeq}"]`)
      el.scrollTop = entry ? el.scrollTop + entry.getBoundingClientRect().top - el.getBoundingClientRect().top - 12 : el.scrollHeight
      readingTop.current = el.scrollTop
      following.current = true
      setAtEnd(true)
      setUnread(0)
      requestAnimationFrame(() => { programmatic.current = false })
    } else {
      el.scrollTop = readingTop.current
      if (appended) {
        setUnread(n => n + Math.max(0, history.length - old.count))
        if (reopening) { following.current = false; setAtEnd(false) }
      }
    }
    previous.current = { id: gameId, seq: lastSeq, count: history.length, navigation, active: true, opened: true }
  }, [gameId, lastSeq, history.length, replay, navigation, active])
  function toEnd() {
    const el = scroll.current
    if (el) el.scrollTop = el.scrollHeight
    readingTop.current = el?.scrollTop || 0
    following.current = true
    setAtEnd(true)
    setUnread(0)
  }
  return <div className="feed-wrap"><div ref={scroll} className="event-scroll" tabIndex={0} aria-label="Лента разговора" onScroll={() => {
    const el = scroll.current
    if (!el || !active) return
    if (programmatic.current) return
    readingTop.current = el.scrollTop
    following.current = el.scrollHeight - el.clientHeight - el.scrollTop < 90
    setAtEnd(following.current)
    if (following.current) setUnread(0)
  }}>
    {history.length ? <div className="event-feed">{history.map((event, i) => <div key={event.seq}>{(!i || history[i - 1].round !== event.round) && <div className="round-divider"><span>Раунд {event.round || 1}</span><i /></div>}<EventEntry event={event} players={players} onPlayer={onPlayer} latest={i === history.length - 1} /></div>)}</div> : empty}
  </div>{unread > 0 && <button className="new-events button" onClick={toEnd}>Новые события · {unread} ↓</button>}{!replay && unread === 0 && !atEnd && <button className="new-events button" onClick={toEnd}>К эфиру ↓</button>}</div>
}
