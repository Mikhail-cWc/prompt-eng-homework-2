import copy
from collections import Counter, defaultdict, deque

import pytest

from bunker.domain import TRAITS, GameConfig, GameState, ModelCallResult, Scenario
from bunker.engine import Engine
from bunker.storage import Store


@pytest.fixture
def scenario():
    return Scenario.model_validate(
        {
            "title": "Искусственный сценарий только для автоматических тестов",
            "catastrophe": "Тестовая катастрофа",
            "bunker": "В тестовом убежище ровно три места",
            "players": [
                {
                    "name": f"Тестовый игрок {i}",
                    "personality": f"Закрытый характер персонажа {i}",
                    "traits": {key: f"PRIVATE_{i}_{key}" for key in TRAITS},
                }
                for i in range(1, 7)
            ],
            "documents": [
                {
                    "id": f"doc{round_number}",
                    "title": f"Инструкция {round_number}",
                    "text": f"Вода фильтр: ROUND_{round_number}_DOCUMENT",
                    "available_round": round_number,
                }
                for round_number in range(1, 4)
            ],
            "acts": [
                {
                    "round": round_number,
                    "title": f"Тестовое действие {round_number}",
                    "event": f"ROUND_{round_number}_EVENT",
                }
                for round_number in range(1, 4)
            ],
        }
    )


class TestOnlyProvider:
    __test__ = False

    def __init__(self, scenario):
        self.scenario = scenario
        self.records = []
        self.counts = Counter()
        self.overrides = defaultdict(deque)
        self.pass_intents = False
        self.on_call = None

    @staticmethod
    def safe_error(exc):
        return f"{type(exc).__name__}: {exc}"

    async def complete(self, model, view, schema, correction=None):
        context = copy.deepcopy(view.context)
        actor = context.get("self", {}).get("id", "host")
        phase = context.get("phase", schema.__name__)
        self.records.append(
            {
                "model": model,
                "actor": actor,
                "schema": schema.__name__,
                "context": context,
                "correction": correction,
            }
        )
        self.counts[(phase, actor)] += 1
        if self.on_call:
            await self.on_call(phase, actor)
        if self.overrides[(phase, actor)]:
            output = self.overrides[(phase, actor)].popleft()
            if isinstance(output, Exception):
                raise output
        else:
            output = self.output(context, schema.__name__)
        return ModelCallResult(
            output=output,
            raw_response={"fixture": "TEST_ONLY_NOT_A_REAL_MODEL_RESPONSE"},
            usage={},
            duration_ms=0,
        )

    def output(self, context, schema_name):
        task = context.get("task", {})
        if schema_name == "Probe":
            return {"status": "ok"}
        if schema_name == "Scenario":
            return self.scenario.model_dump()
        if schema_name == "World":
            return self.scenario.model_dump(exclude={"players"})
        if schema_name == "Character":
            return {
                **self.scenario.players[task["slot"]].model_dump(),
                "name": task["name"],
                **({"traits": task["cards"]} if "cards" in task else {}),
            }
        if schema_name == "Narration":
            return {
                "text": "Искусственная ремарка тестового ведущего.",
                "winner_ids": task.get("winner_ids", []),
                "eliminated_id": task.get("eliminated_id"),
            }
        if schema_name == "Intent":
            return {
                "kind": "pass" if self.pass_intents else "topic",
                "goal": "Убедить оставить моё место",
                "search_query": "вода",
                "note": "TEST_ONLY_PRIVATE_INTENT",
            }
        if schema_name == "Speech":
            return {
                "text": "Я нужен группе и хочу остаться в бункере.",
                "reveal": (
                    task.get("available_traits", [])[:2]
                    if context["phase"] == "reveal"
                    else []
                ),
                "note": "TEST_ONLY_PRIVATE_SPEECH_NOTE",
            }
        if schema_name == "Vote":
            actor = context["self"]["id"]
            candidate = min(p for p in task["candidates"] if p != actor)
            return {
                "candidate_id": candidate,
                "reason": f"Тестовый голос {actor}, чтобы самому остаться",
                "note": f"PRIVATE_VOTE_NOTE_{actor}",
            }
        raise AssertionError(f"Неожиданная схема тестового вызова: {schema_name}")


@pytest.fixture
def provider(scenario):
    return TestOnlyProvider(scenario)


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "test-only.sqlite3")
    yield value
    value.db.close()


@pytest.fixture
def engine(store, provider):
    return Engine(store, provider)


@pytest.fixture
async def ready_game(engine):
    state = GameState(
        config=GameConfig(seed="TEST_ONLY_FIXED_SEED", reading_pause=False)
    )
    engine.states[state.id] = state
    engine.store.save(state)
    await engine.run(state)
    assert state.status == "ready", state.error
    return state


@pytest.fixture
def no_retry_delay(monkeypatch):
    import bunker.engine

    original_sleep = bunker.engine.asyncio.sleep

    async def immediate_retry(delay):
        await original_sleep(0)

    monkeypatch.setattr(bunker.engine.asyncio, "sleep", immediate_retry)
