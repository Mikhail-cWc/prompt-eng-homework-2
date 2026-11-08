import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from bunker.domain import GameState, Intent
from bunker.web import create_app


async def test_invalid_world_is_corrected_before_it_is_cached(
    engine, provider, no_retry_delay
):
    invalid = provider.scenario.model_dump(exclude={"players"})
    invalid["acts"][1]["round"] = 1
    provider.overrides[("World", "host")].append(invalid)
    state = GameState(phase="setup")
    engine.states[state.id] = state
    engine.store.save(state)

    await engine.run(state)

    assert state.status == "ready", state.error
    assert [act.round for act in state.scenario.acts] == [1, 2, 3]
    world_calls = [
        c for c in engine.store.calls(state.id, True) if c["kind"] == "world"
    ]
    assert [c["status"] for c in world_calls] == ["failed", "completed"]


async def test_wrong_character_name_is_corrected_before_cast_is_cached(
    engine, provider, no_retry_delay, monkeypatch
):
    original_output = provider.output
    mismatch_left = 1

    def wrong_name_once(context, schema_name):
        nonlocal mismatch_left
        output = original_output(context, schema_name)
        if (
            schema_name == "Character"
            and context["task"]["slot"] == 2
            and mismatch_left
        ):
            mismatch_left -= 1
            output["name"] = "TEST_ONLY_WRONG_ASSIGNED_NAME"
        return output

    monkeypatch.setattr(provider, "output", wrong_name_once)
    state = GameState(phase="setup")
    engine.states[state.id] = state
    engine.store.save(state)
    await engine.run(state)

    assert state.status == "ready", state.error
    assert len({p.name for p in state.players}) == 6
    character_calls = [
        call
        for call in engine.store.calls(state.id, True)
        if call["actor_id"] == "cast:p3"
    ]
    assert [call["status"] for call in character_calls] == ["failed", "completed"]
    assert "назначенное имя" in character_calls[1]["input"]["correction"]


async def test_failed_discussion_operation_consumes_active_time(
    engine, ready_game, monkeypatch
):
    state = ready_game
    state.phase = "intents"
    state.status = "running"
    timestamps = iter([100.0, 130.0])
    monkeypatch.setattr(
        "bunker.engine.time",
        SimpleNamespace(
            monotonic=lambda: next(timestamps), perf_counter=time.perf_counter
        ),
    )

    async def failed_step(state):
        raise TimeoutError("TEST_ONLY_ACTIVE_DISCUSSION_TIMEOUT")

    monkeypatch.setattr(engine, "step", failed_step)
    await engine.run(state)

    assert state.status == "paused"
    assert state.debate_elapsed == 30.0
    assert engine.store.get(state.id).debate_elapsed == 30.0


async def test_empty_search_is_not_repeated_after_speech_failure(
    engine, ready_game, provider, no_retry_delay, monkeypatch
):
    state = ready_game
    state.phase = "speech"
    state.status = "running"
    state.selected = "p1"
    state.selection = Intent(
        kind="topic", goal="Найти сведения", search_query="нетрезультатов"
    )
    searches = []

    def empty_search(game_id, round_number, query):
        searches.append((game_id, round_number, query))
        return []

    monkeypatch.setattr(engine.store, "search", empty_search)
    provider.overrides[("speech", "p1")].extend(
        [{"invalid_response": "TEST_ONLY_INVALID_SPEECH"}] * 4
    )
    await engine.run(state)
    assert state.status == "paused"
    assert state.pending["tool_executed"]
    assert len(searches) == 1

    async def pause_after_speech(phase, actor):
        if phase == "speech":
            engine.command(state.id, "pause")

    provider.on_call = pause_after_speech
    engine.command(state.id, "resume")
    await asyncio.wait_for(engine.tasks[state.id], timeout=5)
    assert state.phase == "intents"
    assert len(searches) == 1
    assert sum(e["kind"] == "tool_result" for e in engine.store.events(state.id)) == 1
    assert sum(e.kind == "speech" for e in state.history) == 1


async def test_sse_last_event_id_replays_only_missing_events(
    engine, ready_game, tmp_path
):
    app = create_app(tmp_path / "unused.sqlite3")
    app.state.engine = engine
    state = ready_game
    first = engine.store.emit(state, "TEST_ONLY_SSE", {"index": 1})
    second = engine.store.emit(state, "TEST_ONLY_SSE", {"index": 2})
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/games/{game_id}/events"
    )

    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    response = await endpoint(state.id, ConnectedRequest(), 0, str(first.seq))
    try:
        chunk = await anext(response.body_iterator)
        assert chunk.startswith(f"id: {second.seq}\nevent: update\n")
        assert '"index": 2' in chunk
    finally:
        await response.body_iterator.aclose()

    with pytest.raises(HTTPException) as error:
        await endpoint(state.id, ConnectedRequest(), 0, "not-an-integer")
    assert error.value.status_code == 400
