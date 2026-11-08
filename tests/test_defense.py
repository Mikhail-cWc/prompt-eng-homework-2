import asyncio

import pytest

from bunker.cards import CATALOG, deal_cards
from bunker.context import character_view, player_view
from bunker.domain import GameConfig, GameState
from bunker.engine import Engine
from bunker.rules import resolve_votes
from scripts.verify_game import verify


def start_new_voting(state):
    state.rules_version = "2.0"
    state.status = "running"
    state.phase = "vote"


async def to_final_vote(engine, state):
    while state.phase == "defense":
        await engine.step(state)
    assert state.phase == "final_vote"


async def test_preliminary_majority_grants_defense_without_elimination(
    engine, ready_game
):
    state = ready_game
    start_new_voting(state)
    await engine.step(state)
    assert state.phase == "defense"
    assert state.vote_candidates == ["p1"]
    assert state.resolved_id is None
    assert all(p.alive for p in state.players)
    assert state.history[-1].data["stage"] == "preliminary"
    await engine.step(state)
    assert state.history[-1].kind == "defense"
    assert state.history[-1].actor_id == "p1"
    assert state.players[0].revealed == []


async def test_defense_can_redirect_final_vote_to_any_remaining_player(
    engine, ready_game, provider
):
    state = ready_game
    start_new_voting(state)
    await engine.step(state)
    await to_final_vote(engine, state)
    for p in state.players:
        provider.overrides[("final_vote", p.id)].append(
            {
                "candidate_id": "p3" if p.id != "p3" else "p4",
                "reason": "После защиты изменяю решение",
                "note": "PRIVATE_FINAL_NOTE",
            }
        )
    await engine.step(state)
    assert state.phase == "eliminate"
    assert state.resolved_id == "p3"
    calls = [
        r["context"]
        for r in provider.records
        if r["context"].get("phase") == "final_vote"
    ]
    public = [{k: v for k, v in c.items() if k != "self"} for c in calls]
    assert all(c == public[0] for c in public)
    assert all(c["task"]["candidates"] == [p.id for p in state.players] for c in calls)
    assert all(sum(e["kind"] == "votes" for e in c["history"]) == 1 for c in calls)
    assert all(any(e["kind"] == "defense" for e in c["history"]) for c in calls)
    assert state.history[-1].data["stage"] == "final"
    await engine.step(state)
    assert [p.id for p in state.players if not p.alive] == ["p3"]
    assert "на откуп судьбе" in state.history[-1].data["text"]


async def test_tied_nominees_each_defend_once_and_final_tie_uses_lottery(
    engine, ready_game, provider
):
    state = ready_game
    start_new_voting(state)
    tied = {p.id: "p2" if i % 2 == 0 else "p1" for i, p in enumerate(state.players)}
    for phase in ("vote", "final_vote"):
        for actor, candidate in tied.items():
            provider.overrides[(phase, actor)].append(
                {"candidate_id": candidate, "reason": "Ничья", "note": ""}
            )
    await engine.step(state)
    assert state.vote_candidates == ["p1", "p2"]
    await engine.step(state)
    restored = engine.store.get(state.id)
    restarted = Engine(engine.store, provider)
    await to_final_vote(restarted, restored)
    assert [e.actor_id for e in restored.history if e.kind == "defense"] == ["p1", "p2"]
    await restarted.step(restored)
    assert restored.phase == "eliminate"
    assert restored.resolved_id == resolve_votes(tied, state.config.seed, 1, True)[0]
    assert "Жеребьёвка" in restored.history[-1].data["reason"]
    assert sum(e.kind == "votes" for e in restored.history) == 2


@pytest.mark.parametrize("bad", [{"reveal": ["health"]}, {"text": "я" * 701}])
async def test_invalid_defense_does_not_reveal_or_eliminate(
    engine, ready_game, provider, no_retry_delay, bad
):
    state = ready_game
    start_new_voting(state)
    await engine.step(state)
    invalid = {"text": "Хочу жить и остаться", "note": "", **bad}
    provider.overrides[("defense", "p1")].extend([invalid] * 4)
    await engine.run(state)
    assert state.status == "paused"
    assert state.phase == "defense"
    assert not any(e.kind == "defense" for e in state.history)
    assert all(p.alive and not p.revealed for p in state.players)
    assert provider.counts[("defense", "p1")] == 4


async def test_full_new_game_has_exactly_two_ballots_per_round(engine, ready_game):
    state = ready_game
    state.rules_version = "2.0"
    state.status = "running"
    await asyncio.wait_for(engine.run(state), timeout=5)
    assert state.status == "completed", state.error
    assert len(state.winners) == 3
    assert sum(not p.alive for p in state.players) == 3
    for round_number in (1, 2, 3):
        events = [e for e in state.history if e.round == round_number]
        assert [e.data["stage"] for e in events if e.kind == "votes"] == [
            "preliminary",
            "final",
        ]
        assert sum(e.kind == "elimination" for e in events) == 1
        assert sum(e.kind == "defense" for e in events) >= 1
    assert (
        verify(
            {
                "state": state.model_dump(),
                "events": engine.store.events(state.id),
                "calls": engine.store.calls(state.id, True),
            }
        )["rules_version"]
        == "2.0"
    )


async def test_final_ballot_resumes_only_missing_votes(
    engine, ready_game, provider, no_retry_delay
):
    state = ready_game
    start_new_voting(state)
    await engine.step(state)
    await to_final_vote(engine, state)
    provider.overrides[("final_vote", "p3")].extend([TimeoutError("TEST_ONLY")] * 4)
    await engine.run(state)
    assert state.status == "paused"
    assert state.phase == "final_vote"
    pending = set(state.pending)
    assert pending == {"p1", "p2", "p4", "p5", "p6"}
    counts = dict(provider.counts)
    engine.store.recover()
    restored = engine.store.get(state.id)
    restarted = Engine(engine.store, provider)
    restored.status = "running"
    await restarted.step(restored)
    assert restored.phase == "eliminate"
    assert sum(e.kind == "defense" for e in restored.history) == 1
    assert sum(e.kind == "votes" for e in restored.history) == 2
    for actor in pending:
        assert provider.counts[("final_vote", actor)] == counts[("final_vote", actor)]
    assert provider.counts[("final_vote", "p3")] == counts[("final_vote", "p3")] + 1


async def test_new_games_use_new_rule_and_legacy_states_keep_old_rule(engine):
    assert GameState.model_validate({"config": {}}).rules_version == "1.0"
    state = engine.create(GameConfig(seed="new-rule", reading_pause=False))
    await asyncio.wait_for(engine.tasks[state.id], timeout=5)
    assert state.rules_version == "2.0"
    assert state.status == "ready", state.error
    engine.command(state.id, "start")
    await asyncio.wait_for(engine.tasks[state.id], timeout=5)
    assert state.status == "completed", state.error
    assert len(state.winners) == 3


def test_life_goal_and_generated_cards_are_explicit(ready_game):
    view = player_view(ready_game, "p1", {})
    assert "хочешь жить" in view.instructions
    assert "не означает" in view.instructions
    cards = [
        character_view({}, slot, seed="author-deck").context["task"]["cards"]
        for slot in range(6)
    ]
    assert len({c["profession"] for c in cards}) == 6
    assert cards == [
        character_view({}, slot, seed="author-deck").context["task"]["cards"]
        for slot in range(6)
    ]
    assert all(set(c) == set(ready_game.players[0].traits) for c in cards)
    assert cards != [
        character_view({}, slot, seed="another-deck").context["task"]["cards"]
        for slot in range(6)
    ]


def test_catalog_has_six_valid_categories_and_no_duplicate_draws():
    assert sum(len(values) for values in CATALOG.values()) == 76
    for seed in ("first", "second", "third"):
        cards = deal_cards(seed)
        for key, values in CATALOG.items():
            assert len({card[key] for card in cards}) == 6
            assert all(
                card[key] in values and 0 < len(card[key]) <= 100 for card in cards
            )


async def test_scenario_writer_cannot_strengthen_drawn_cards(
    engine, provider, no_retry_delay
):
    state = GameState(rules_version="2.0", phase="setup")
    engine.states[state.id] = state
    engine.store.save(state)
    original = provider.complete

    async def corrupt_one_card(model, view, schema, correction=None):
        result = await original(model, view, schema, correction)
        if schema.__name__ == "Character" and view.context["task"]["slot"] == 0:
            result.output["traits"]["health"] = "Придуманное усиление карты"
        return result

    provider.complete = corrupt_one_card
    await engine.run(state)
    assert state.status == "paused"
    assert state.phase == "setup"
    assert state.scenario is None
    assert "cards" in state.error
