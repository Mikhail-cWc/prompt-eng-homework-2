import asyncio
import json
from collections import Counter

import pytest

from bunker.context import player_view
from bunker.domain import GameConfig, GameState, Intent, Speech, Vote
from bunker.engine import Engine
from bunker.provider import YandexProvider
from bunker.rules import resolve_votes
from bunker.storage import Store


async def test_preflight_uses_production_prompt_builder_without_network(
    engine, provider
):
    adapter = YandexProvider()
    provider.parameters = adapter.parameters
    provider.instructions = adapter.instructions
    try:
        state = engine.create(GameConfig(seed="TEST_ONLY_PRODUCTION_PROMPT"))
        await asyncio.wait_for(engine.tasks[state.id], timeout=5)
        assert state.status == "ready", state.error
        assert sum(r["schema"] == "Probe" for r in provider.records) == 3
        calls = engine.store.calls(state.id, detail=True)
        assert all(c["input"]["wire_instructions"] for c in calls)
    finally:
        await adapter.client.close()


def enter_phase(engine, state, phase):
    state.status = "running"
    state.phase = phase
    engine.store.save(state)


def last_test_speech(engine, state, actor="p6"):
    return engine.store.emit(
        state,
        "reveal",
        {"text": "Тестовая реплика", "addressed_to": ["p1"]},
        actor,
        public=True,
    )


async def test_setup_preserves_world_and_successful_cast_after_partial_failure(
    engine, provider, no_retry_delay, monkeypatch
):
    original_output = provider.output
    failures_left = 4

    def fail_one_character(context, schema_name):
        nonlocal failures_left
        if (
            schema_name == "Character"
            and context["task"]["slot"] == 2
            and failures_left
        ):
            failures_left -= 1
            raise TimeoutError("TEST_ONLY_CHARACTER_TIMEOUT")
        return original_output(context, schema_name)

    monkeypatch.setattr(provider, "output", fail_one_character)
    state = GameState(phase="setup")
    engine.states[state.id] = state
    engine.store.save(state)
    await engine.run(state)

    assert state.status == "paused"
    assert state.phase == "setup"
    assert state.pending["world"]["title"] == provider.scenario.title
    assert set(state.pending["cast"]) == {"0", "1", "3", "4", "5"}
    assert engine.store.get(state.id).pending == state.pending
    assert sum(r["schema"] == "World" for r in provider.records) == 1

    engine.command(state.id, "resume")
    await asyncio.wait_for(engine.tasks[state.id], timeout=5)

    assert state.status == "ready", state.error
    assert state.phase == "opening"
    assert len(state.players) == 6
    assert state.pending == {}
    assert sum(r["schema"] == "World" for r in provider.records) == 1
    character_counts = Counter(
        r["context"]["task"]["slot"]
        for r in provider.records
        if r["schema"] == "Character"
    )
    assert character_counts == {0: 1, 1: 1, 2: 5, 3: 1, 4: 1, 5: 1}
    assert sum(e["kind"] == "ready" for e in engine.store.events(state.id)) == 1


async def test_complete_game_has_three_exclusions_and_bounded_discussion(
    engine, ready_game
):
    state = engine.command(ready_game.id, "start")
    await asyncio.wait_for(engine.tasks[state.id], timeout=15)

    assert state.status == "completed", state.error
    assert state.round == 3
    assert len(state.winners) == 3
    assert set(state.winners) == {p.id for p in state.players if p.alive}
    eliminations = [e for e in state.history if e.kind == "elimination"]
    assert [e.round for e in eliminations] == [1, 2, 3]
    assert len({e.data["eliminated_id"] for e in eliminations}) == 3
    for round_number in range(1, 4):
        speeches = [
            e for e in state.history if e.round == round_number and e.kind == "speech"
        ]
        assert len(speeches) == 8
        assert max(Counter(e.actor_id for e in speeches).values()) <= 2
        assert all(a.actor_id != b.actor_id for a, b in zip(speeches, speeches[1:]))
        assert (
            sum(e.kind == "votes" and e.round == round_number for e in state.history)
            == 1
        )
    assert all(len(p.revealed) == 6 for p in state.players if p.alive)
    assert engine.store.get(state.id) == state
    assert any(e["kind"] == "tool_result" for e in engine.store.events(state.id))


async def test_hidden_data_never_enters_another_players_view(engine, ready_game):
    state = ready_game
    state.players[1].revealed = ["profession"]
    state.players[1].note = "SECRET_OTHER_PLAYER_NOTE"
    state.pending = {"p2": {"candidate_id": "p1", "reason": "SECRET_CURRENT_VOTE"}}
    state.queue = [{"player_id": "p2", "goal": "SECRET_CURRENT_INTENT"}]
    state.selected = "p2"
    state.selection = Intent(kind="topic", goal="SECRET_SELECTION")

    view = player_view(state, "p1", {"action": "Тест"})
    serialized = view.model_dump_json()
    assert view.context["self"]["traits"] == state.players[0].traits
    assert state.players[1].traits["profession"] in serialized
    for player in state.players[1:]:
        for key, value in player.traits.items():
            if key not in player.revealed:
                assert value not in serialized
        assert player.personality not in serialized
    for secret in (
        "SECRET_OTHER_PLAYER_NOTE",
        "SECRET_CURRENT_VOTE",
        "SECRET_CURRENT_INTENT",
        "SECRET_SELECTION",
        "ROUND_2_EVENT",
        "ROUND_3_EVENT",
        "ROUND_2_DOCUMENT",
        "ROUND_3_DOCUMENT",
    ):
        assert secret not in serialized
    assert view.context["available_documents"] == [
        {"id": "doc1", "title": "Инструкция 1"}
    ]


async def test_votes_use_same_public_snapshot_and_publish_only_after_batch(
    engine, ready_game, provider
):
    state = ready_game
    enter_phase(engine, state, "vote")
    last_test_speech(engine, state)
    await engine.step(state)

    calls = [r for r in provider.records if r["schema"] == "Vote"]
    assert len(calls) == 6
    public_contexts = [
        {k: v for k, v in r["context"].items() if k != "self"} for r in calls
    ]
    assert all(context == public_contexts[0] for context in public_contexts)
    for record in calls:
        serialized = json.dumps(record["context"])
        assert "PRIVATE_VOTE_NOTE" not in serialized
        assert "Тестовый голос" not in serialized
        assert all(e["kind"] != "votes" for e in record["context"]["history"])
    assert state.phase == "eliminate"
    vote_event = next(e for e in state.history if e.kind == "votes")
    assert len(vote_event.data["votes"]) == 6
    assert "note" not in json.dumps(vote_event.data)


async def test_all_pass_closes_discussion_without_fabricated_speech(
    engine, ready_game, provider
):
    state = ready_game
    provider.pass_intents = True
    enter_phase(engine, state, "intents")
    last_test_speech(engine, state)
    await engine.step(state)

    assert state.phase == "closing"
    assert state.debate_count == 0
    assert not any(e.kind == "speech" for e in state.history)
    assert state.history[-1].kind == "debate_closed"
    assert "пропустили" in state.history[-1].data["text"]


@pytest.mark.parametrize("limit", ["count", "time"])
async def test_discussion_limit_closes_before_new_model_calls(
    engine, ready_game, provider, limit
):
    state = ready_game
    enter_phase(engine, state, "intents")
    last_test_speech(engine, state)
    if limit == "count":
        state.debate_count = 8
    else:
        state.debate_elapsed = 600
    count = len(provider.records)
    await engine.step(state)
    assert state.phase == "closing"
    assert len(provider.records) == count


async def test_partial_batch_survives_failure_and_resume_without_duplicate_votes(
    engine, ready_game, provider, no_retry_delay
):
    state = ready_game
    enter_phase(engine, state, "vote")
    provider.overrides[("vote", "p3")].extend([TimeoutError("TEST_ONLY_TIMEOUT")] * 4)
    await engine.run(state)

    assert state.status == "paused"
    assert state.phase == "vote"
    assert set(state.pending) == {"p1", "p2", "p4", "p5", "p6"}
    assert not any(e.kind == "votes" for e in state.history)
    saved_pending = engine.store.get(state.id).pending
    assert saved_pending == state.pending
    initial_calls = dict(provider.counts)

    async def pause_after_missing_vote(phase, actor):
        if phase == "vote" and actor == "p3":
            engine.command(state.id, "pause")

    provider.on_call = pause_after_missing_vote
    engine.command(state.id, "resume")
    await asyncio.wait_for(engine.tasks[state.id], timeout=5)

    assert state.status == "paused"
    assert state.phase == "eliminate"
    assert sum(e.kind == "votes" for e in state.history) == 1
    assert provider.counts[("vote", "p3")] == initial_calls[("vote", "p3")] + 1
    for actor in saved_pending:
        assert provider.counts[("vote", actor)] == initial_calls[("vote", actor)]
    assert state.pending == {}


async def test_pause_finishes_current_action_and_resume_does_not_repeat_it(
    engine, ready_game, provider
):
    state = ready_game

    async def pause_during_opening(phase, actor):
        if phase == "opening":
            engine.command(state.id, "pause")

    provider.on_call = pause_during_opening
    engine.command(state.id, "start")
    await asyncio.wait_for(engine.tasks[state.id], timeout=5)
    assert state.status == "paused"
    assert state.phase == "reveal"
    assert len(state.history) == 1
    assert state.history[0].kind == "narration"

    async def pause_during_reveal(phase, actor):
        if phase == "reveal":
            engine.command(state.id, "pause")

    provider.on_call = pause_during_reveal
    engine.command(state.id, "resume")
    await asyncio.wait_for(engine.tasks[state.id], timeout=5)
    assert state.status == "paused"
    assert state.cursor == 1
    assert sum(e.kind == "narration" for e in state.history) == 1
    assert sum(e.kind == "reveal" for e in state.history) == 1
    assert provider.counts[("opening", "host")] == 1


async def test_successful_call_cache_replays_without_call_or_duplicate_event(
    engine, ready_game, provider
):
    state = ready_game
    enter_phase(engine, state, "reveal")
    view = player_view(
        state,
        "p1",
        {
            "available_traits": list(state.players[0].traits),
            "profession_required": True,
        },
    )
    speech = await engine.ask(
        state,
        "p1",
        state.players[0].model,
        "reveal",
        view,
        Speech,
        lambda value: engine.check_speech(state, "p1", value, reveal=True),
    )
    before = len(engine.store.events(state.id))
    restarted = Engine(engine.store, provider)
    restored = restarted.state(state.id)
    repeated = await restarted.ask(
        restored,
        "p1",
        restored.players[0].model,
        "reveal",
        player_view(restored, "p1", view.context["task"]),
        Speech,
    )
    assert repeated == speech
    assert provider.counts[("reveal", "p1")] == 1
    assert len(engine.store.events(state.id)) == before


@pytest.mark.parametrize("failure_kind", ["timeout", "invalid_json", "self_vote"])
async def test_four_failed_attempts_pause_game_and_preserve_failure_evidence(
    engine, ready_game, provider, no_retry_delay, failure_kind
):
    state = ready_game
    enter_phase(engine, state, "vote")
    failures = {
        "timeout": TimeoutError("TEST_ONLY_TIMEOUT"),
        "invalid_json": {"invalid_response": "TEST_ONLY_NOT_JSON"},
        "self_vote": {"candidate_id": "p1", "reason": "Нельзя", "note": "план"},
    }
    provider.overrides[("vote", "p1")].extend([failures[failure_kind]] * 4)
    await engine.run(state)

    assert state.status == "paused"
    assert state.phase == "vote"
    assert "4 попытки исчерпаны" in state.error
    failed = [
        c
        for c in engine.store.calls(state.id, detail=True)
        if c["actor_id"] == "p1" and c["kind"] == "vote"
    ]
    assert len(failed) == 4
    assert all(c["status"] == "failed" for c in failed)
    assert [c["attempt"] for c in failed] == [1, 2, 3, 4]
    assert failed[1]["input"]["correction"]
    assert not any(e.kind == "votes" for e in state.history)
    if failure_kind != "timeout":
        assert failed[0]["output"] == failures[failure_kind]
        assert failed[0]["raw_response"]["fixture"].startswith("TEST_ONLY")


async def test_invalid_vote_is_corrected_within_two_attempts(
    engine, ready_game, provider, no_retry_delay
):
    state = ready_game
    enter_phase(engine, state, "vote")
    provider.overrides[("vote", "p1")].append(
        {"candidate_id": "p1", "reason": "Недопустимый тестовый голос", "note": ""}
    )
    await engine.step(state)
    assert state.phase == "eliminate"
    assert provider.counts[("vote", "p1")] == 2
    records = [
        r for r in provider.records if r["actor"] == "p1" and r["schema"] == "Vote"
    ]
    assert records[0]["correction"] is None
    assert "себя" in records[1]["correction"]


async def test_tied_vote_runs_once_then_uses_seeded_lottery(
    engine, ready_game, provider
):
    state = ready_game
    enter_phase(engine, state, "vote")
    tied_votes = {
        "p1": "p2",
        "p2": "p1",
        "p3": "p2",
        "p4": "p1",
        "p5": "p2",
        "p6": "p1",
    }
    for phase in ("vote", "runoff"):
        for actor, candidate in tied_votes.items():
            provider.overrides[(phase, actor)].append(
                {"candidate_id": candidate, "reason": "Тестовая ничья", "note": ""}
            )
    await engine.step(state)
    assert state.phase == "runoff"
    assert state.vote_candidates == ["p1", "p2"]
    assert all(p.alive for p in state.players)
    await engine.step(state)
    expected, _, _ = resolve_votes(tied_votes, state.config.seed, 1, True)
    assert state.phase == "eliminate"
    assert state.resolved_id == expected
    assert [e.kind for e in state.history] == ["votes", "votes"]
    assert "Жеребьёвка SHA-256" in state.history[-1].data["reason"]
    await engine.step(state)
    assert state.phase == "aftermath"
    assert [p.id for p in state.players if not p.alive] == [expected]


async def test_host_cannot_change_established_elimination(
    engine, ready_game, provider, no_retry_delay
):
    state = ready_game
    state.resolved_id = "p1"
    state.players[0].alive = False
    enter_phase(engine, state, "aftermath")
    invalid = {"text": "Тестовая неверная ремарка", "eliminated_id": "p2"}
    provider.overrides[("aftermath", "host")].extend([invalid] * 4)
    await engine.run(state)
    assert state.status == "paused"
    assert state.phase == "aftermath"
    assert [p.id for p in state.players if not p.alive] == ["p1"]
    assert not state.history
    assert "Ведущий изменил" in state.error


async def test_stop_cancels_inflight_request_and_marks_it_uncertain(
    engine, ready_game, provider
):
    state = ready_game
    started = asyncio.Event()
    wait_forever = asyncio.Event()

    async def blocked_request(phase, actor):
        started.set()
        await wait_forever.wait()

    provider.on_call = blocked_request
    engine.command(state.id, "start")
    await asyncio.wait_for(started.wait(), timeout=5)
    engine.command(state.id, "stop")
    await asyncio.gather(engine.tasks[state.id], return_exceptions=True)
    assert state.status == "stopped"
    assert state.phase == "opening"
    assert not state.history
    call = engine.store.calls(state.id, detail=True)[-1]
    assert call["status"] == "uncertain"
    assert "неизвестно" in call["error"]
    assert engine.store.get(state.id).status == "stopped"


async def test_restart_recovers_pending_batch_and_marks_unknown_call_uncertain(
    engine, ready_game, provider, tmp_path
):
    state = ready_game
    enter_phase(engine, state, "vote")
    state.pending = {
        "p1": Vote(
            candidate_id="p2", reason="Сохранённый голос", note="план"
        ).model_dump()
    }
    engine.store.save(state)
    call = engine.store.begin_call(
        state.id, "test-only-interrupted-call", "p2", "test", "vote", {}
    )
    engine.store.db.close()
    restarted_store = Store(tmp_path / "test-only.sqlite3")
    engine.store = restarted_store
    try:
        restarted_store.recover()
        restarted = Engine(restarted_store, provider)
        restored = restarted.state(state.id)
        assert restored.status == "paused"
        assert restored.pending == state.pending
        assert restored.phase == "vote"
        recovered_call = next(
            c for c in restarted_store.calls(state.id, True) if c["id"] == call["id"]
        )
        assert recovered_call["status"] == "uncertain"
        assert "неизвестно" in recovered_call["error"]
        restored.status = "running"
        await restarted.step(restored)
        assert provider.counts[("vote", "p1")] == 0
        assert restored.phase == "eliminate"
        assert sum(e.kind == "votes" for e in restored.history) == 1
    finally:
        restarted_store.db.close()
