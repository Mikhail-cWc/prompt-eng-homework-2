import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bunker.context import PROMPT_VERSION
from bunker.domain import GameConfig
from bunker.engine import Engine
from bunker.provider import YandexProvider
from bunker.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def markdown_export(state) -> str:
    names = {p.id: p.name for p in state.players}
    lines = [
        f"# {state.title}",
        "",
        f"Партия: {state.id}; статус: {state.status}",
        "",
        "Реальная запись модели; без пересоздания реплик.",
        "",
    ]
    for event in state.history:
        data = event.data
        lines.extend(
            [
                f"## Раунд {event.round} · {event.kind} · {names.get(event.actor_id, 'Ведущий')}",
                "",
            ]
        )
        if data.get("stage_direction"):
            lines.append(f"*{data['stage_direction']}*")
        if data.get("text"):
            lines.append(data["text"])
        if data.get("traits"):
            lines.append(
                "Раскрыто: " + "; ".join(f"{k}: {v}" for k, v in data["traits"].items())
            )
        if data.get("event"):
            lines.append("Событие: " + data["event"])
        for vote in data.get("votes", []):
            lines.append(
                f"- {names.get(vote['player_id'])} → {names.get(vote['candidate_id'])}: {vote['reason']}"
            )
        if data.get("reason"):
            lines.append(data["reason"])
        lines.append("")
    if state.winners:
        lines.append("Места получили: " + ", ".join(names[p] for p in state.winners))
    return "\n".join(lines)


class Command(BaseModel):
    action: Literal["start", "pause", "resume", "stop", "next"]
    event_seq: int | None = Field(default=None, ge=1)


def create_app(db_path=None, provider=None) -> FastAPI:
    read_only = os.environ.get("BUNKER_READ_ONLY") == "1"

    @asynccontextmanager
    async def lifespan(app):
        store = Store(
            db_path or os.environ.get("BUNKER_DB", ROOT / "data/bunker.sqlite3")
        )
        store.recover()
        app.state.engine = Engine(store, provider or YandexProvider())
        yield
        await app.state.engine.shutdown()
        client = getattr(app.state.engine.provider, "client", None)
        if client:
            await client.close()
        store.db.close()

    app = FastAPI(title="Бункер · LLM Theatre", lifespan=lifespan)

    @app.middleware("http")
    async def local_commands(request: Request, call_next):
        if read_only and request.method not in {"GET", "HEAD", "OPTIONS"}:
            return PlainTextResponse("Доступен только просмотр записи", status_code=403)
        # Локальное управление не должно запускаться со страницы постороннего сайта.
        if request.method in {"POST", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin not in {
                str(request.base_url).rstrip("/"),
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            }:
                return PlainTextResponse("Недопустимый Origin", status_code=403)
        return await call_next(request)

    def engine() -> Engine:
        return app.state.engine

    def state(game_id):
        try:
            return engine().state(game_id)
        except KeyError:
            raise HTTPException(404, "Партия не найдена") from None

    @app.get("/api/health")
    async def health():
        return {
            "configured": not read_only and engine().provider.configured,
            "read_only": read_only,
            "service": "bunker",
            "prompt_version": PROMPT_VERSION,
        }

    @app.get("/api/games")
    async def games():
        return [
            {
                k: s.model_dump()[k]
                for k in ("id", "status", "round", "phase", "title", "created_at")
            }
            for s in engine().store.all()
        ]

    @app.post("/api/games", status_code=201)
    async def create(config: GameConfig):
        try:
            return engine().create(config)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/games/{game_id}")
    async def get_game(game_id: str):
        return state(game_id)

    @app.get("/api/games/{game_id}/presentation")
    async def presentation(game_id: str):
        state(game_id)
        return engine().store.presentation(game_id)

    @app.post("/api/games/{game_id}/commands")
    async def command(game_id: str, body: Command):
        state(game_id)
        try:
            return engine().command(game_id, body.action, body.event_seq)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/games/{game_id}/events")
    async def events(
        game_id: str,
        request: Request,
        after: int = 0,
        last_event_id: str | None = Header(default=None),
    ):
        state(game_id)
        try:
            cursor = max(after, int(last_event_id or 0))
        except ValueError:
            raise HTTPException(400, "Некорректный Last-Event-ID") from None

        async def stream():
            nonlocal cursor
            heartbeat = 0
            while not await request.is_disconnected():
                rows = engine().store.events(game_id, cursor)
                for event in rows:
                    cursor = event["seq"]
                    yield f"id: {cursor}\nevent: update\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                heartbeat += 1
                if heartbeat % 150 == 0:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/games/{game_id}/calls")
    async def calls(game_id: str):
        state(game_id)
        return engine().store.calls(game_id)

    @app.get("/api/games/{game_id}/players/{actor_id}/inspector")
    async def player_inspector(game_id: str, actor_id: str):
        game = state(game_id)
        player = next((p for p in game.players if p.id == actor_id), None)
        if player is None:
            raise HTTPException(404, "Участник не найден")
        latest = note_call = None

        def metadata(call):
            context = call["input"]["context"]
            return {
                **{
                    k: call[k]
                    for k in ("id", "model", "kind", "status", "attempt", "created_at")
                },
                "round": context.get("round"),
                "phase": context.get("phase"),
            }

        for call in engine().store.player_calls(game_id, actor_id):
            if latest is None:
                latest = metadata(call)
            if (
                player.note
                and call["status"] == "completed"
                and (call.get("output") or {}).get("note") == player.note
            ):
                note_call = metadata(call)
                break
        return {"note": player.note, "note_call": note_call, "latest_call": latest}

    @app.get("/api/games/{game_id}/calls/{call_id}")
    async def call(game_id: str, call_id: str):
        state(game_id)
        result = next(
            (
                c
                for c in engine().store.calls(game_id, detail=True)
                if c["id"] == call_id
            ),
            None,
        )
        if not result:
            raise HTTPException(404, "Вызов не найден")
        return result

    @app.get("/api/games/{game_id}/export")
    async def export(game_id: str, format: Literal["json", "markdown"] = "json"):
        game = state(game_id)
        if format == "markdown":
            return Response(
                markdown_export(game),
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="bunker-{game_id}.md"'
                },
            )
        payload = {
            "state": game.model_dump(),
            "events": engine().store.events(game_id),
            "calls": engine().store.calls(game_id, detail=True),
        }
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="bunker-{game_id}.json"'
            },
        )

    dist = ROOT / "frontend/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:

        @app.get("/")
        async def no_frontend():
            return PlainTextResponse(
                "Соберите сайт: cd frontend && npm ci && npm run build. API: /docs"
            )

    return app


app = create_app()
