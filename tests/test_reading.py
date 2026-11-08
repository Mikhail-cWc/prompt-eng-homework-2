import asyncio

import pytest

from bunker.domain import GameConfig, GameState, ReadingPause
from bunker.engine import Engine


def observe_reading(engine):
    started = asyncio.Event()
    original = engine.store.emit

    def emit(state, kind, data, *args, **kwargs):
        result = original(state, kind, data, *args, **kwargs)
        if kind == "reading_started":
            started.set()
        return result

    engine.store.emit = emit
    return started


async def test_next_model_waits_for_reading_and_pause_preserves_remaining(
    engine, ready_game, provider
):
    state = ready_game
    state.config.reading_pause = True
    started = observe_reading(engine)
    engine.command(state.id, "start")
    await asyncio.wait_for(started.wait(), 2)
    assert state.reading.event_seq == state.history[-1].seq
    assert provider.counts[("reveal", "p1")] == 0
    engine.command(state.id, "pause")
    await asyncio.wait_for(engine.tasks[state.id], 2)
    assert state.status == "paused"
    assert state.reading.deadline is None
    assert 0 < state.reading.remaining <= 20
    persisted = engine.store.get(state.id)
    assert persisted.reading == state.reading


async def test_skip_is_bound_to_current_event_and_does_not_skip_new_reply(
    engine, ready_game, provider
):
    state = ready_game
    state.config.reading_pause = True
    started = observe_reading(engine)
    engine.command(state.id, "start")
    await asyncio.wait_for(started.wait(), 2)
    seq = state.reading.event_seq
    with pytest.raises(ValueError):
        engine.command(state.id, "next", event_seq=seq - 1)
    assert state.reading.event_seq == seq

    async def pause_on_reveal(phase, actor):
        if phase == "reveal":
            engine.command(state.id, "pause")

    provider.on_call = pause_on_reveal
    engine.command(state.id, "next", event_seq=seq)
    with pytest.raises(ValueError):
        engine.command(state.id, "next", event_seq=seq)
    await asyncio.wait_for(engine.tasks[state.id], 2)
    assert provider.counts[("reveal", "p1")] == 1
    assert state.status == "paused"
    assert state.reading.event_seq != seq


async def test_countdown_automatically_continues_without_new_browser_command(
    engine, ready_game, provider
):
    state = ready_game
    state.config.reading_pause = True
    engine.reading_duration = lambda text: 0.02

    async def pause_on_reveal(phase, actor):
        if phase == "reveal":
            engine.command(state.id, "pause")

    provider.on_call = pause_on_reveal
    engine.command(state.id, "start")
    await asyncio.wait_for(engine.tasks[state.id], 2)
    assert state.status == "paused"
    assert provider.counts[("opening", "host")] == 1
    assert provider.counts[("reveal", "p1")] == 1
    assert len(state.history) == 2


async def test_restart_retains_reading_window_without_repeating_accepted_call(
    engine, ready_game, provider
):
    state = ready_game
    state.config.reading_pause = True
    started = observe_reading(engine)
    engine.command(state.id, "start")
    await asyncio.wait_for(started.wait(), 2)
    engine.command(state.id, "pause")
    await asyncio.wait_for(engine.tasks[state.id], 2)
    state.status = "running"
    engine.store.save(state)
    engine.store.recover()
    restored = engine.store.get(state.id)
    assert restored.status == "paused"
    assert restored.reading.deadline is None
    restarted = Engine(engine.store, provider)
    restarted.states[restored.id] = restored
    restarted.command(restored.id, "resume")
    assert restored.reading.deadline is not None
    restarted.command(restored.id, "pause")
    await asyncio.wait_for(restarted.tasks[restored.id], 2)
    assert provider.counts[("opening", "host")] == 1
    assert provider.counts[("reveal", "p1")] == 0


def test_default_reading_window_is_bounded():
    assert GameConfig().reading_pause is True
    assert Engine.reading_duration("Коротко") == 4
    assert 4 < Engine.reading_duration("я" * 350) < 20
    assert Engine.reading_duration("я" * 5000) == 40


def test_abrupt_restart_keeps_a_readable_window(store):
    state = GameState(
        status="running", reading=ReadingPause(event_seq=1, remaining=10, deadline=1)
    )
    store.save(state)
    store.recover()
    restored = store.get(state.id)
    assert restored.status == "paused"
    assert restored.reading.remaining == 10
    assert restored.reading.deadline is None


async def test_stop_cancels_reading_without_starting_another_call(
    engine, ready_game, provider
):
    state = ready_game
    state.config.reading_pause = True
    started = observe_reading(engine)
    engine.command(state.id, "start")
    await asyncio.wait_for(started.wait(), 2)
    engine.command(state.id, "stop")
    await asyncio.gather(engine.tasks[state.id], return_exceptions=True)
    assert state.status == "stopped"
    assert state.reading is None
    assert provider.counts[("reveal", "p1")] == 0
