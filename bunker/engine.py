import asyncio
import inspect
import json
import time
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from bunker.context import character_view, director_view, player_view, scenario_view
from bunker.domain import (
    PUBLIC_TEXT_LIMIT,
    SHORT_TEXT_LIMIT,
    Character,
    GameState,
    Intent,
    Narration,
    Player,
    PlayerView,
    Probe,
    ReadingPause,
    Scenario,
    Speech,
    Vote,
    World,
)
from bunker.rules import choose_speaker, resolve_votes, validate_reveal, validate_vote
from bunker.storage import Store


class GameFailure(Exception):
    pass


class Engine:
    request_timeout = 60
    max_attempts = 4

    def __init__(self, store: Store, provider):
        self.store = store
        self.provider = provider
        self.states: dict[str, GameState] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(3)

    def state(self, game_id: str) -> GameState:
        if game_id not in self.states:
            self.states[game_id] = self.store.get(game_id)
        return self.states[game_id]

    def create(self, config) -> GameState:
        if any(s.status not in {"completed", "stopped"} for s in self.store.all()):
            raise ValueError("Сначала завершите или остановите текущую партию")
        state = GameState(config=config, rules_version="2.0")
        self.states[state.id] = state
        self.store.emit(state, "created", {"text": "Подготовка новой партии"})
        self.launch(state)
        return state

    def launch(self, state: GameState) -> None:
        task = self.tasks.get(state.id)
        if task and not task.done():
            raise ValueError("Обработка партии уже выполняется")
        self.tasks[state.id] = asyncio.create_task(self.run(state))

    def command(
        self, game_id: str, action: str, event_seq: int | None = None
    ) -> GameState:
        state = self.state(game_id)
        if action == "pause" and state.status in {"preparing", "running"}:
            state.status = "pausing"
        elif action in {"start", "resume"} and state.status in {"ready", "paused"}:
            task = self.tasks.get(game_id)
            if task and not task.done():
                raise ValueError("Предыдущая операция ещё завершается")
            state.status = (
                "preparing" if state.phase in {"preflight", "setup"} else "running"
            )
            state.error = None
            if state.reading:
                state.reading.deadline = time.time() + state.reading.remaining
            self.launch(state)
        elif action == "next" and state.status == "running" and state.reading:
            if event_seq != state.reading.event_seq:
                raise ValueError("Этот переход устарел: на сцене уже другое событие")
            state.reading = None
            self.store.emit(
                state, "reading_finished", {"event_seq": event_seq, "skipped": True}
            )
        elif action == "stop" and state.status not in {"completed", "stopped"}:
            state.status = "stopped"
            state.operation = None
            state.reading = None
            task = self.tasks.get(game_id)
            if task:
                task.cancel()
            self.store.interrupt_stream(state)
        else:
            raise ValueError(f"Команда {action} недопустима в состоянии {state.status}")
        self.store.emit(state, "status", {"status": state.status})
        return state

    async def run(self, state: GameState) -> None:
        try:
            while state.status in {"preparing", "running", "pausing"}:
                if state.status == "pausing":
                    self.suspend_reading(state)
                    state.status = "paused"
                    state.operation = None
                    self.store.emit(state, "status", {"status": "paused"})
                    break
                if state.reading:
                    if state.reading.deadline is None:
                        state.reading.deadline = time.time() + state.reading.remaining
                    remaining = state.reading.deadline - time.time()
                    if remaining > 0:
                        await asyncio.sleep(min(remaining, 0.1))
                        continue
                    event_seq = state.reading.event_seq
                    state.reading = None
                    self.store.emit(
                        state,
                        "reading_finished",
                        {"event_seq": event_seq, "skipped": False},
                    )
                previous_seq = state.history[-1].seq if state.history else 0
                timed = state.phase in {"intents", "speech"}
                started = time.monotonic()
                try:
                    await self.step(state)
                finally:
                    if timed:
                        state.debate_elapsed += time.monotonic() - started
                        self.store.save(state)
                latest = state.history[-1] if state.history else None
                if (
                    state.config.reading_pause
                    and state.status in {"running", "pausing"}
                    and latest
                    and latest.seq > previous_seq
                    and latest.kind
                    in {
                        "reveal",
                        "speech",
                        "closing",
                        "defense",
                        "narration",
                        "votes",
                        "elimination",
                    }
                ):
                    seconds = (
                        6
                        if latest.kind in {"votes", "elimination"}
                        else self.reading_duration(latest.data.get("text", ""))
                    )
                    state.reading = ReadingPause(
                        event_seq=latest.seq,
                        remaining=seconds,
                        deadline=(
                            time.time() + seconds if state.status == "running" else None
                        ),
                    )
                    state.operation = None
                    self.store.emit(
                        state, "reading_started", state.reading.model_dump()
                    )
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            if state.status != "stopped":
                self.suspend_reading(state)
                state.status = "paused"
                state.error = (
                    "Обработка прервана; можно продолжить с сохранённого действия"
                )
                self.store.emit(state, "status", {"status": state.status})
            raise
        except Exception as exc:
            state.status = "paused"
            state.operation = None
            state.error = self.provider.safe_error(exc)
            self.store.emit(state, "error", {"reason": state.error})

    @staticmethod
    def reading_duration(text: str) -> float:
        return max(4, min(40, len(text) / 35))

    @staticmethod
    def suspend_reading(state: GameState) -> None:
        if state.reading and state.reading.deadline is not None:
            state.reading.remaining = max(0, state.reading.deadline - time.time())
            state.reading.deadline = None

    async def ask(
        self,
        state: GameState,
        actor: str,
        model: str,
        kind: str,
        view: PlayerView,
        schema: type[BaseModel],
        check: Callable | None = None,
    ):
        key = f"{state.round}:{state.phase}:{state.cursor}:{state.debate_count}:{actor}:{kind}"
        cached = self.store.cached(state.id, key)
        if cached is not None:
            result = schema.model_validate(cached)
            if check:
                check(result)
            return result
        failed = self.store.last_failure(state.id, key)
        correction = None
        if failed:
            correction = failed.get("feedback") or self.repair_feedback(
                ValueError(failed["error"]),
                failed["error"],
                failed.get("output"),
                state,
                schema,
            )
        for attempt in range(self.max_attempts):
            async with self.semaphore:
                if state.status == "stopped":
                    raise asyncio.CancelledError()
                inputs = {
                    **view.model_dump(),
                    "schema": schema.model_json_schema(),
                    "correction": correction,
                    "parameters": (
                        self.provider.parameters(model, schema, view)
                        if hasattr(self.provider, "parameters")
                        else {"test_provider": True}
                    ),
                }
                if hasattr(self.provider, "instructions"):
                    inputs["wire_instructions"] = self.provider.instructions(
                        view, schema, correction
                    )
                call = self.store.begin_call(state.id, key, actor, model, kind, inputs)
                supports_stream = (
                    "on_text" in inspect.signature(self.provider.complete).parameters
                )
                streaming = (
                    schema in {Speech, Narration}
                    and kind != "stream_probe"
                    and supports_stream
                )
                received_public_text = False
                stream_data = {
                    "call_id": call["id"],
                    "actor_id": actor,
                    "attempt": call["attempt"],
                    "kind": kind,
                    "status": "generating",
                    "text": "",
                }
                last_emit = 0.0
                flush_handle = None

                def flush_text():
                    nonlocal last_emit, flush_handle
                    flush_handle = None
                    if streaming:
                        self.store.emit(
                            state, "speech_stream", dict(stream_data), actor
                        )
                        last_emit = time.monotonic()

                def cancel_flush():
                    nonlocal flush_handle
                    if flush_handle:
                        flush_handle.cancel()
                        flush_handle = None

                async def on_text(prefix):
                    nonlocal flush_handle, received_public_text
                    received_public_text = received_public_text or bool(prefix)
                    stream_data["text"] = prefix
                    current = time.monotonic()
                    if streaming and current - last_emit >= 0.1:
                        cancel_flush()
                        flush_text()
                    elif streaming and flush_handle is None:
                        flush_handle = asyncio.get_running_loop().call_later(
                            max(0, 0.1 - (current - last_emit)), flush_text
                        )

                if streaming:
                    self.store.emit(state, "speech_stream", dict(stream_data), actor)
                state.operation = f"{kind}: {actor}"
                self.store.emit(
                    state,
                    "call_started",
                    {"call_id": call["id"], "actor_id": actor, "kind": kind},
                )
                started = time.perf_counter()
                try:
                    async with asyncio.timeout(self.request_timeout):
                        result = await self.provider.complete(
                            model,
                            view,
                            schema,
                            correction,
                            **(
                                {"on_text": on_text}
                                if streaming or kind == "stream_probe"
                                else {}
                            ),
                        )
                    call.update(result.model_dump())
                    cancel_flush()
                    if streaming:
                        stream_data["status"] = "validating"
                        self.store.emit(
                            state, "speech_stream", dict(stream_data), actor
                        )
                    if "invalid_response" in result.output:
                        raise ValueError(
                            "Ответ не является JSON-объектом по схеме. "
                            + result.output.get("parse_error", "")
                        )
                    if schema is Speech and state.phase in {"closing", "defense"}:
                        text = result.output.get("text")
                        if isinstance(text, str) and len(text) > SHORT_TEXT_LIMIT:
                            raise ValueError(
                                f"text: получено {len(text)} символов, допустимо не более {SHORT_TEXT_LIMIT}"
                            )
                    parsed = schema.model_validate(result.output)
                    if kind == "stream_probe" and not received_public_text:
                        raise ValueError("Модель не вернула поток публичного JSON text")
                    if check:
                        check(parsed)
                    call["status"] = "completed"
                    self.store.finish_call(call)
                    self.store.emit(
                        state,
                        "call_completed",
                        {"call_id": call["id"], "actor_id": actor, "kind": kind},
                    )
                    return parsed
                except asyncio.CancelledError:
                    cancel_flush()
                    if streaming:
                        stream_data.update(status="interrupted", text="")
                        current = self.store.current_stream(state.id)
                        if not current or current["status"] != "interrupted":
                            self.store.emit(
                                state, "speech_stream", dict(stream_data), actor
                            )
                    call.update(
                        status="uncertain",
                        error="Запрос отменён; выполнение у провайдера неизвестно",
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                    self.store.finish_call(call)
                    raise
                except Exception as exc:
                    cancel_flush()
                    if streaming:
                        stream_data.update(status="discarded", text="")
                        self.store.emit(
                            state, "speech_stream", dict(stream_data), actor
                        )
                    call["execution_uncertain"] = isinstance(
                        exc, (TimeoutError, ConnectionError)
                    ) or type(exc).__name__ in {"APITimeoutError", "APIConnectionError"}
                    error = self.provider.safe_error(exc)
                    correction = self.repair_feedback(
                        exc, error, call.get("output"), state, schema
                    )
                    call.update(
                        status="failed",
                        error=error,
                        feedback=correction,
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                    self.store.finish_call(call)
                    self.store.emit(
                        state,
                        "call_failed",
                        {
                            "call_id": call["id"],
                            "actor_id": actor,
                            "reason": error,
                            "attempt": call["attempt"],
                            "batch_attempt": attempt + 1,
                            "max_attempts": self.max_attempts,
                        },
                    )
            if attempt + 1 < self.max_attempts:
                await asyncio.sleep(min(2**attempt, 4))
        raise GameFailure(
            f"{actor}/{kind}: {self.max_attempts} попытки исчерпаны. {error}"
        )

    @staticmethod
    def repair_feedback(exc, error, output, state, schema) -> str:
        errors = [{"field": "$", "type": "action_error", "message": error}]
        if isinstance(exc, ValidationError):
            errors = []
            for item in exc.errors(include_url=False, include_input=True):
                detail = {
                    "field": ".".join(map(str, item["loc"])),
                    "type": item["type"],
                    "message": item["msg"],
                    **item.get("ctx", {}),
                }
                if isinstance(item.get("input"), (str, list)):
                    detail["actual_length"] = len(item["input"])
                errors.append(detail)
        previous = output
        if output and "invalid_response" in output:
            previous = output["invalid_response"]
            errors = [
                {
                    "field": "$",
                    "type": "invalid_json",
                    "message": "Верни один корректный JSON-объект. Экранируй кавычки внутри строк; не добавляй обычный текст или Markdown.",
                    "parse_error": output.get("parse_error"),
                }
            ]
        elif schema is Speech and output and isinstance(output.get("text"), str):
            limit = (
                SHORT_TEXT_LIMIT
                if state.phase in {"closing", "defense"}
                else PUBLIC_TEXT_LIMIT
            )
            if len(output["text"]) > limit:
                errors = [item for item in errors if item["field"] not in {"$", "text"}]
                errors.insert(
                    0,
                    {
                        "field": "text",
                        "type": "string_too_long",
                        "actual_length": len(output["text"]),
                        "max_length": limit,
                        "message": f"Сократи text до {limit} символов с пробелами; цель — {int(limit * 0.7)} символов. Сохрани основной аргумент.",
                    },
                )
        if len(json.dumps(previous, ensure_ascii=False)) > 6000:
            previous = json.dumps(previous, ensure_ascii=False)[:6000]
        return json.dumps(
            {"errors": errors, "previous_response": previous},
            ensure_ascii=False,
            default=str,
        )

    def alive_order(self, state: GameState) -> list[str]:
        seats = [p.id for p in state.players]
        offset = (state.round - 1 + state.debate_count) % 6
        seats = seats[offset:] + seats[:offset]
        alive = {p.id for p in state.players if p.alive}
        return [actor for actor in seats if actor in alive]

    def last_speech(self, state: GameState):
        return next(
            (
                e
                for e in reversed(state.history)
                if e.round == state.round and e.kind in {"reveal", "speech", "closing"}
            ),
            None,
        )

    def player(self, state: GameState, actor: str) -> Player:
        return next(p for p in state.players if p.id == actor)

    async def batch(
        self, state: GameState, actors: list[str], schema, task: dict, check
    ):
        # Все представления строятся до запуска запросов; чужие промежуточные ответы скрыты.
        views = {actor: player_view(state, actor, task) for actor in actors}

        async def one(actor):
            if actor in state.pending:
                return
            value = await self.ask(
                state,
                actor,
                self.player(state, actor).model,
                state.phase,
                views[actor],
                schema,
                lambda value: check(actor, value),
            )
            state.pending[actor] = value.model_dump()
            self.store.emit(
                state,
                "batch_progress",
                {
                    "received": len(state.pending),
                    "expected": len(actors),
                    "kind": state.phase,
                },
            )

        results = await asyncio.gather(
            *(one(actor) for actor in actors), return_exceptions=True
        )
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            raise errors[0]
        return {actor: schema.model_validate(state.pending[actor]) for actor in actors}

    def check_speech(
        self,
        state: GameState,
        actor: str,
        speech: Speech,
        reveal=False,
        closing=False,
        defense=False,
    ):
        alive = {p.id for p in state.players if p.alive}
        if any(
            target not in alive or target == actor for target in speech.addressed_to
        ):
            raise ValueError(
                f"addressed_to: только ID других оставшихся игроков {sorted(alive - {actor})}, не имена"
            )
        if reveal:
            validate_reveal(self.player(state, actor), speech.reveal, state.round)
        elif speech.reveal:
            raise ValueError("Раскрытие доступно только в обязательном выступлении")
        if (closing or defense) and len(speech.text) > SHORT_TEXT_LIMIT:
            raise ValueError(
                f"{'Защитная речь' if defense else 'Последнее слово'} — не более {SHORT_TEXT_LIMIT} символов"
            )
        available = {
            d.id for d in state.scenario.documents if d.available_round <= state.round
        }
        if not set(speech.citations) <= available:
            raise ValueError(
                f"citations: только ID доступных документов {sorted(available)}, не названия; либо []"
            )

    async def narrate(self, state: GameState, task: dict) -> Narration:
        def check(value):
            if sorted(value.winner_ids) != sorted(
                task.get("winner_ids", [])
            ) or value.eliminated_id != task.get("eliminated_id"):
                raise ValueError("Ведущий изменил установленный кодом результат")

        return await self.ask(
            state,
            "host",
            state.config.director_model,
            "narration",
            director_view(state, task),
            Narration,
            check,
        )

    async def step(self, state: GameState) -> None:
        phase = state.phase
        if phase == "preflight":
            for model in dict.fromkeys(
                [*state.config.models, state.config.director_model]
            ):
                await self.ask(
                    state,
                    "preflight:" + model,
                    model,
                    "probe",
                    PlayerView(
                        instructions='Ответь JSON {"status":"ok"}.',
                        context={"task": {"action": "Проверка JSON-формата"}},
                    ),
                    Probe,
                )
                if "on_text" in inspect.signature(self.provider.complete).parameters:
                    await self.ask(
                        state,
                        "preflight-stream:" + model,
                        model,
                        "stream_probe",
                        PlayerView(
                            instructions='Техническая проверка. Верни JSON Speech: text="Связь есть.", note="", stage_direction="", addressed_to=[], reveal=[], citations=[].',
                            context={
                                "task": {
                                    "action": "Короткая проверка потокового JSON Speech"
                                }
                            },
                        ),
                        Speech,
                    )
            state.phase = "setup"
            self.store.emit(state, "phase", {"phase": state.phase})
        elif phase == "setup":
            view = scenario_view(state.config.seed)
            view.instructions += "\nСейчас создай только мир (World), без персонажей. Ровно 3 коротких документа по 2 предложения; события по 1 предложению. catastrophe и bunker — по 1–2 предложения."
            world = await self.ask(
                state, "director", state.config.director_model, "world", view, World
            )
            state.pending["world"] = world.model_dump()
            self.store.save(state)

            async def cast(slot):
                view = character_view(
                    world.model_dump(),
                    slot,
                    seed=state.config.seed if state.rules_version == "2.0" else None,
                )

                def check_name(character):
                    if character.name != view.context["task"]["name"]:
                        raise ValueError(
                            f"Используй назначенное имя: {view.context['task']['name']}"
                        )
                    cards = view.context["task"].get("cards")
                    if cards and character.traits.model_dump() != cards:
                        raise ValueError("Сохрани розданные cards в traits дословно")

                character = await self.ask(
                    state,
                    f"cast:p{slot + 1}",
                    state.config.director_model,
                    "character",
                    view,
                    Character,
                    check_name,
                )
                state.pending.setdefault("cast", {})[str(slot)] = character.model_dump()
                self.store.emit(
                    state,
                    "cast_progress",
                    {"received": len(state.pending["cast"]), "expected": 6},
                )
                return character

            cast_results = await asyncio.gather(
                *(cast(i) for i in range(6)), return_exceptions=True
            )
            errors = [
                value for value in cast_results if isinstance(value, BaseException)
            ]
            if errors:
                raise errors[0]
            scenario = Scenario(**world.model_dump(), players=cast_results)
            state.scenario = scenario
            state.title = scenario.title
            state.players = [
                Player(id=f"p{i + 1}", model=model, **character.model_dump())
                for i, (character, model) in enumerate(
                    zip(scenario.players, state.config.models)
                )
            ]
            self.store.index_documents(state.id, scenario.documents)
            state.phase = "opening"
            state.pending = {}
            state.status = "paused" if state.status == "pausing" else "ready"
            state.operation = None
            self.store.emit(
                state,
                "ready",
                {"text": "Сценарий и карточки сохранены. Можно начать игру."},
            )
        elif phase == "opening":
            act = next(a for a in state.scenario.acts if a.round == state.round)
            narration = await self.narrate(
                state,
                {
                    "action": "Открой действие, сообщи запланированное событие",
                    "act": act.model_dump(),
                },
            )
            state.phase = "reveal"
            state.cursor = 0
            self.store.emit(
                state,
                "narration",
                {"text": narration.text, "event": act.event, "title": act.title},
                "host",
                public=True,
            )
        elif phase in {"reveal", "closing", "defense"}:
            order = self.alive_order(state)
            if phase == "defense":
                order = [actor for actor in order if actor in state.vote_candidates]
            if state.cursor >= len(order):
                state.cursor = 0
                state.pending = {}
                state.phase = (
                    "intents"
                    if phase == "reveal"
                    else "final_vote" if phase == "defense" else "vote"
                )
                if phase == "defense":
                    state.vote_candidates = []
                self.store.emit(state, "phase", {"phase": state.phase})
                return
            actor = order[state.cursor]
            player = self.player(state, actor)
            task = {
                "action": (
                    "Раскрой ровно две характеристики и защити своё место"
                    if phase == "reveal"
                    else (
                        f"Защитная речь: предварительно выбрали тебя. Убеди проголосовавших против тебя изменить выбор. Хочешь жить и остаться в бункере. До {SHORT_TEXT_LIMIT} символов, reveal=[]"
                        if phase == "defense"
                        else f"Последнее слово: защити своё место. До {SHORT_TEXT_LIMIT} символов, reveal=[]"
                    )
                ),
                "available_traits": [
                    k for k in player.traits if k not in player.revealed
                ],
                "profession_required": phase == "reveal" and state.round == 1,
                "text_limit": (
                    PUBLIC_TEXT_LIMIT if phase == "reveal" else SHORT_TEXT_LIMIT
                ),
            }
            speech = await self.ask(
                state,
                actor,
                player.model,
                phase,
                player_view(state, actor, task),
                Speech,
                lambda value: self.check_speech(
                    state,
                    actor,
                    value,
                    reveal=phase == "reveal",
                    closing=phase == "closing",
                    defense=phase == "defense",
                ),
            )
            if phase == "reveal":
                player.revealed.extend(speech.reveal)
            player.note = speech.note
            state.cursor += 1
            data = speech.model_dump(exclude={"note"})
            data["traits"] = {k: player.traits[k] for k in speech.reveal}
            self.store.emit(state, phase, data, actor, public=True)
        elif phase == "intents":
            if state.debate_count >= 8 or state.debate_elapsed >= 600:
                self.close_debate(state, "Исчерпан лимит дискуссии")
                return
            last = self.last_speech(state)
            actors = [
                p
                for p in self.alive_order(state)
                if state.debate_counts.get(p, 0) < 2 and p != last.actor_id
            ]
            if not actors:
                self.close_debate(state, "Нет допустимых выступающих")
                return

            def check(actor, intent):
                if intent.kind in {"answer", "object"} and intent.reply_to != last.seq:
                    raise ValueError(
                        f"Для ответа/возражения reply_to должен быть {last.seq}"
                    )
                if intent.kind != "pass" and not intent.goal:
                    raise ValueError("Укажи краткую цель выступления")

            intents = await self.batch(
                state,
                actors,
                Intent,
                {
                    "action": "Хочешь ли выступить сейчас? Выбери pass/answer/object/topic. goal — одно предложение до80 символов о цели, НЕ сама речь. note до100 символов. Если нужен документ, search_query=1–3 слова. Остаться — твоя цель.",
                    "last_speech_seq": last.seq,
                },
                check,
            )
            for actor, intent in intents.items():
                if intent.note:
                    self.player(state, actor).note = intent.note
            selected = choose_speaker(
                intents,
                state.debate_counts,
                last.actor_id,
                last.data.get("addressed_to", []),
                last.seq,
                self.alive_order(state),
            )
            state.queue = [
                {"player_id": actor, **intent.model_dump()}
                for actor, intent in intents.items()
            ]
            state.pending = {}
            if not selected:
                self.close_debate(state, "Все допустимые игроки пропустили слово")
                return
            state.selected, reason = selected
            state.selection = intents[state.selected]
            state.tool_result = []
            state.phase = "speech"
            for item in state.queue:
                item["selected"] = item["player_id"] == state.selected
                item["reason"] = (
                    reason
                    if item["selected"]
                    else "Заявка истекает; решение обновится на следующем такте"
                )
            self.store.emit(
                state,
                "speaker_selected",
                {"actor_id": state.selected, "reason": reason},
            )
        elif phase == "speech":
            if state.debate_elapsed >= 600:
                self.close_debate(state, "Исчерпан лимит времени дискуссии")
                return
            actor = state.selected
            player = self.player(state, actor)
            if state.selection.search_query and not state.pending.get("tool_executed"):
                state.tool_result = self.store.search(
                    state.id, state.round, state.selection.search_query
                )
                state.pending["tool_executed"] = True
                self.store.emit(
                    state,
                    "tool_result",
                    {
                        "name": "search_documents",
                        "query": state.selection.search_query,
                        "results": state.tool_result,
                    },
                    actor,
                )
            speech = await self.ask(
                state,
                actor,
                player.model,
                "speech",
                player_view(
                    state,
                    actor,
                    {
                        "action": "Тебе дано слово. Убеди участников оставить тебя. reveal=[]",
                        "intent": state.selection.model_dump(),
                        "search_results": state.tool_result,
                    },
                ),
                Speech,
                lambda value: self.check_speech(state, actor, value),
            )
            player.note = speech.note
            state.debate_count += 1
            state.debate_counts[actor] = state.debate_counts.get(actor, 0) + 1
            state.pending = {}
            state.phase = "intents"
            self.store.emit(
                state, "speech", speech.model_dump(exclude={"note"}), actor, public=True
            )
        elif phase in {"vote", "runoff", "final_vote"}:
            actors = self.alive_order(state)
            votes = await self.batch(
                state,
                actors,
                Vote,
                {
                    "action": (
                        "Предварительно выбери другого кандидата на изгнание. Лидеры получат защитное слово; пока никто не изгнан. Нельзя за себя."
                        if state.rules_version == "2.0" and phase == "vote"
                        else (
                            "После защит проголосуй решающе за изгнание другого игрока. Можно выбрать любого оставшегося, изменить прежний голос и спасти себя. Нельзя за себя."
                            if phase == "final_vote"
                            else "Закрыто проголосуй за исключение другого игрока, чтобы самому остаться. Нельзя за себя."
                        )
                    ),
                    "candidates": state.vote_candidates or actors,
                    "runoff": phase == "runoff",
                    "stage": (
                        "final"
                        if phase == "final_vote"
                        else "preliminary" if state.rules_version == "2.0" else "legacy"
                    ),
                },
                lambda actor, value: validate_vote(
                    actor, value, state.players, state.vote_candidates
                ),
            )
            result, tied, reason = resolve_votes(
                {a: v.candidate_id for a, v in votes.items()},
                state.config.seed,
                state.round,
                phase in {"runoff", "final_vote"},
            )
            for actor, vote in votes.items():
                self.player(state, actor).note = vote.note
            state.pending = {}
            state.phase = "eliminate" if result else "runoff"
            state.resolved_id = result
            state.vote_candidates = tied if not result else []
            preliminary = state.rules_version == "2.0" and phase == "vote"
            if preliminary:
                state.phase = "defense"
                state.resolved_id = None
                state.vote_candidates = tied
                state.cursor = 0
                state.queue = []
                state.selected = None
                reason = "Предварительный результат. Лидеры получают защитное слово; изгнание ещё не решено."
            self.store.emit(
                state,
                "votes",
                {
                    "votes": [
                        {"player_id": a, **v.model_dump(exclude={"note"})}
                        for a, v in votes.items()
                    ],
                    "runoff": phase == "runoff",
                    "reason": reason,
                    "tied": tied,
                    **(
                        {
                            "stage": "preliminary" if preliminary else "final",
                            "defense_candidates": tied if preliminary else [],
                        }
                        if state.rules_version == "2.0"
                        else {}
                    ),
                },
                public=True,
            )
        elif phase == "eliminate":
            player = self.player(state, state.resolved_id)
            if not player.alive:
                raise ValueError("Игрок уже исключён")
            player.alive = False
            state.phase = "aftermath"
            self.store.emit(
                state,
                "elimination",
                {
                    "eliminated_id": player.id,
                    "text": f"{player.name} изгнан из бункера и остаётся снаружи на откуп судьбе. Дальнейшая судьба неизвестна.",
                },
                public=True,
            )
        elif phase == "aftermath":
            narration = await self.narrate(
                state,
                {
                    "action": "Прокомментируй изгнание: человек остаётся снаружи на откуп судьбе. Не утверждай, что он погиб.",
                    "eliminated_id": state.resolved_id,
                    "winner_ids": (
                        [p.id for p in state.players if p.alive]
                        if state.round == 3
                        else []
                    ),
                },
            )
            state.phase = "epilogue" if state.round == 3 else "advance"
            self.store.emit(
                state, "narration", {"text": narration.text}, "host", public=True
            )
        elif phase == "advance":
            state.round += 1
            state.phase = "opening"
            state.cursor = 0
            state.debate_count = 0
            state.debate_counts = {}
            state.debate_elapsed = 0
            state.queue = []
            state.selected = None
            state.selection = None
            state.tool_result = []
            state.resolved_id = None
            self.store.emit(state, "phase", {"phase": state.phase})
        elif phase == "epilogue":
            winners = [p.id for p in state.players if p.alive]
            narration = await self.narrate(
                state,
                {
                    "action": "Заверши пьесу. Трое перечисленных игроков получили места; трое изгнанных остаются снаружи на откуп судьбе. Их дальнейшая судьба неизвестна.",
                    "winner_ids": winners,
                    "outside_ids": [p.id for p in state.players if not p.alive],
                },
            )
            state.winners = winners
            state.status = "completed"
            state.phase = "done"
            state.operation = None
            self.store.emit(
                state,
                "epilogue",
                {"text": narration.text, "winner_ids": winners},
                "host",
                public=True,
            )
        else:
            raise ValueError(f"Неизвестный этап {phase}")

    def close_debate(self, state: GameState, reason: str):
        state.phase = "closing"
        state.cursor = 0
        state.pending = {}
        self.store.emit(state, "debate_closed", {"text": reason}, public=True)

    async def shutdown(self):
        tasks = [task for task in self.tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
