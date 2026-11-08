import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

from bunker.domain import Document, GameEvent, GameState, now


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(game_id TEXT, seq INTEGER, body TEXT NOT NULL,
                PRIMARY KEY(game_id,seq));
            CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, game_id TEXT, action_key TEXT,
                body TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS calls_action ON calls(game_id,action_key);
            CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(
                game_id UNINDEXED, doc_id UNINDEXED, available_round UNINDEXED, title, text,
                tokenize='unicode61');
        """)

    def get(self, game_id: str) -> GameState:
        row = self.db.execute(
            "SELECT state FROM games WHERE id=?", (game_id,)
        ).fetchone()
        if row is None:
            raise KeyError(game_id)
        return GameState.model_validate_json(row[0])

    def all(self) -> list[GameState]:
        return [
            GameState.model_validate_json(r[0])
            for r in self.db.execute("SELECT state FROM games ORDER BY rowid DESC")
        ]

    def save(self, state: GameState) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO games VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                (state.id, state.model_dump_json()),
            )

    def emit(
        self,
        state: GameState,
        kind: str,
        data: dict,
        actor_id: str | None = None,
        public: bool = False,
    ) -> GameEvent:
        with self.db:
            seq = self.db.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE game_id=?", (state.id,)
            ).fetchone()[0]
            event = GameEvent(
                seq=seq, kind=kind, round=state.round, data=data, actor_id=actor_id
            )
            if public:
                state.history.append(event)
            self.db.execute(
                "INSERT INTO events VALUES (?,?,?)",
                (state.id, seq, event.model_dump_json()),
            )
            self.db.execute(
                "INSERT INTO games VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                (state.id, state.model_dump_json()),
            )
            if public and kind in {
                "reveal",
                "speech",
                "closing",
                "defense",
                "narration",
                "epilogue",
            }:
                current = self.current_stream(state.id)
                if (
                    current
                    and current["actor_id"] == actor_id
                    and current["status"] == "validating"
                ):
                    accepted = GameEvent(
                        seq=seq + 1,
                        kind="speech_stream",
                        round=state.round,
                        actor_id=actor_id,
                        data={
                            **{k: v for k, v in current.items() if k != "seq"},
                            "status": "accepted",
                            "text": data["text"],
                            "public_seq": seq,
                        },
                    )
                    self.db.execute(
                        "INSERT INTO events VALUES (?,?,?)",
                        (state.id, accepted.seq, accepted.model_dump_json()),
                    )
        return event

    def current_stream(self, game_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT seq,body FROM events WHERE game_id=? AND json_extract(body,'$.kind')='speech_stream' ORDER BY seq DESC LIMIT 1",
            (game_id,),
        ).fetchone()
        return {**json.loads(row[1])["data"], "seq": row[0]} if row else None

    def presentation(self, game_id: str) -> dict:
        with self.db:
            state = self.get(game_id)
            seq = self.db.execute(
                "SELECT COALESCE(MAX(seq),0) FROM events WHERE game_id=?", (game_id,)
            ).fetchone()[0]
            return {
                "game": state,
                "stream": self.current_stream(game_id),
                "event_seq": seq,
            }

    def interrupt_stream(self, state: GameState) -> None:
        current = self.current_stream(state.id)
        if current and current["status"] in {"generating", "validating"}:
            self.emit(
                state,
                "speech_stream",
                {
                    **{k: v for k, v in current.items() if k != "seq"},
                    "status": "interrupted",
                    "text": "",
                },
                current["actor_id"],
            )

    def events(self, game_id: str, after: int = 0) -> list[dict]:
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT body FROM events WHERE game_id=? AND seq>? ORDER BY seq",
                (game_id, after),
            )
        ]

    def begin_call(
        self,
        game_id: str,
        action_key: str,
        actor: str,
        model: str,
        kind: str,
        inputs: dict,
    ) -> dict:
        previous = list(
            self.db.execute(
                "SELECT id FROM calls WHERE game_id=? AND action_key=?",
                (game_id, action_key),
            )
        )
        call = {
            "id": uuid4().hex,
            "actor_id": actor,
            "model": model,
            "kind": kind,
            "action_key": action_key,
            "status": "running",
            "attempt": len(previous) + 1,
            "created_at": now(),
            "input": inputs,
            "output": None,
            "raw_response": None,
            "duration_ms": None,
            "usage": {},
            "error": None,
        }
        with self.db:
            self.db.execute(
                "INSERT INTO calls VALUES (?,?,?,?)",
                (call["id"], game_id, action_key, encode(call)),
            )
        return call

    def finish_call(self, call: dict) -> None:
        with self.db:
            self.db.execute(
                "UPDATE calls SET body=? WHERE id=?", (encode(call), call["id"])
            )

    def calls(self, game_id: str, detail: bool = False) -> list[dict]:
        calls = [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT body FROM calls WHERE game_id=? ORDER BY rowid", (game_id,)
            )
        ]
        if detail:
            return calls
        return [
            {k: v for k, v in c.items() if k not in {"input", "raw_response"}}
            for c in calls
        ]

    def cached(self, game_id: str, action_key: str) -> dict | None:
        rows = self.db.execute(
            "SELECT body FROM calls WHERE game_id=? AND action_key=? ORDER BY rowid DESC",
            (game_id, action_key),
        )
        for row in rows:
            call = json.loads(row[0])
            if call["status"] == "completed":
                return call["output"]
        return None

    def player_calls(self, game_id: str, actor_id: str):
        rows = self.db.execute(
            "SELECT body FROM calls WHERE game_id=? "
            "AND json_extract(body, '$.actor_id')=? "
            "AND json_extract(body, '$.input.context.self.id')=? ORDER BY rowid DESC",
            (game_id, actor_id, actor_id),
        )
        for row in rows:
            yield json.loads(row[0])

    def last_failure(self, game_id: str, action_key: str) -> dict | None:
        row = self.db.execute(
            "SELECT body FROM calls WHERE game_id=? AND action_key=? ORDER BY rowid DESC LIMIT 1",
            (game_id, action_key),
        ).fetchone()
        call = json.loads(row[0]) if row else None
        return call if call and call.get("error") else None

    def index_documents(self, game_id: str, documents: list[Document]) -> None:
        with self.db:
            self.db.execute("DELETE FROM documents WHERE game_id=?", (game_id,))
            self.db.executemany(
                "INSERT INTO documents VALUES (?,?,?,?,?)",
                [
                    (game_id, d.id, d.available_round, d.title, d.text)
                    for d in documents
                ],
            )

    def search(self, game_id: str, round_number: int, query: str) -> list[dict]:
        words = re.findall(r"\w+", query, flags=re.UNICODE)[:12]
        if not words:
            return []
        expression = " OR ".join('"' + word + '"*' for word in words)
        rows = self.db.execute(
            """SELECT doc_id,title,text FROM documents WHERE documents MATCH ?
            AND game_id=? AND CAST(available_round AS INTEGER)<=? ORDER BY rank LIMIT 3""",
            (expression, game_id, round_number),
        )
        return [{"id": r[0], "title": r[1], "text": r[2][:600]} for r in rows]

    def recover(self) -> None:
        for state in self.all():
            self.interrupt_stream(state)
            if state.status in {"preparing", "running", "pausing"}:
                if state.reading:
                    state.reading.deadline = None
                state.status = "paused"
                state.operation = None
                state.error = "Сервер перезапущен. Сохранённые действия восстановлены; можно продолжить."
                self.emit(state, "recovered", {"reason": state.error})
        with self.db:
            rows = list(self.db.execute("SELECT body FROM calls"))
            for row in rows:
                call = json.loads(row[0])
                if call["status"] == "running":
                    call["status"] = "uncertain"
                    call["error"] = (
                        "Ответ потерян при остановке процесса; выполнение у провайдера неизвестно."
                    )
                    self.db.execute(
                        "UPDATE calls SET body=? WHERE id=?", (encode(call), call["id"])
                    )
