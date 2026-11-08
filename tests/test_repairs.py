import json

import pytest

from bunker.context import player_view
from bunker.domain import Speech


async def test_defense_repairs_three_bad_answers_and_accepts_fourth(
    engine, ready_game, provider, no_retry_delay
):
    state = ready_game
    state.status = "running"
    state.phase = "defense"
    invalid = {"text": "я" * 720, "note": "TEST_ONLY_MY_PLAN"}
    provider.overrides[("defense", "p1")].extend([invalid] * 3)
    result = await engine.ask(
        state,
        "p1",
        state.players[0].model,
        "defense",
        player_view(state, "p1", {"text_limit": 700}),
        Speech,
        lambda value: engine.check_speech(state, "p1", value, defense=True),
    )
    assert len(result.text) <= 700
    assert provider.counts[("defense", "p1")] == 4
    feedback = json.loads(provider.records[-1]["correction"])
    assert feedback["errors"][0]["field"] == "text"
    assert feedback["errors"][0]["actual_length"] == 720
    assert feedback["errors"][0]["max_length"] == 700
    assert feedback["previous_response"] == invalid
    assert "PRIVATE_2" not in provider.records[-1]["correction"]
    assert not state.history and not state.players[0].revealed


@pytest.mark.parametrize(
    "raw",
    [
        "Я хочу остаться в бункере.",
        '{"text":"Оставьте меня","note":"Покажу пользу "бытового" навыка"}',
    ],
)
async def test_json_errors_produce_actionable_feedback(
    engine, ready_game, provider, no_retry_delay, raw
):
    state = ready_game
    state.phase = "defense"
    provider.overrides[("defense", "p1")].append({"invalid_response": raw})
    await engine.ask(
        state,
        "p1",
        state.players[0].model,
        "defense",
        player_view(state, "p1", {"text_limit": 700}),
        Speech,
    )
    feedback = json.loads(provider.records[-1]["correction"])
    assert feedback["errors"][0]["type"] == "invalid_json"
    assert feedback["previous_response"] == raw
    assert "JSON" in feedback["errors"][0]["message"]


async def test_resume_reuses_saved_repair_feedback(
    engine, ready_game, provider, no_retry_delay
):
    state = ready_game
    state.phase = "defense"
    provider.overrides[("defense", "p1")].extend(
        [{"text": "я" * 720, "note": "мой план"}] * 4
    )
    from bunker.engine import GameFailure

    view = player_view(state, "p1", {"text_limit": 700})
    with pytest.raises(GameFailure):
        await engine.ask(state, "p1", state.players[0].model, "defense", view, Speech)
    saved = engine.store.calls(state.id, detail=True)[-1]
    await engine.ask(state, "p1", state.players[0].model, "defense", view, Speech)
    assert provider.records[-1]["correction"] == saved["feedback"]


async def test_resume_upgrades_legacy_error_to_feedback_with_previous_answer(
    engine, ready_game, provider
):
    state = ready_game
    state.phase = "defense"
    key = f"{state.round}:{state.phase}:{state.cursor}:{state.debate_count}:p1:defense"
    call = engine.store.begin_call(
        state.id, key, "p1", state.players[0].model, "defense", {}
    )
    call.update(
        status="failed",
        error="TEST_ONLY_JSON_DECODE_ERROR",
        output={"invalid_response": "Ответ без JSON"},
    )
    engine.store.finish_call(call)
    await engine.ask(
        state,
        "p1",
        state.players[0].model,
        "defense",
        player_view(state, "p1", {"text_limit": 700}),
        Speech,
    )
    feedback = json.loads(provider.records[-1]["correction"])
    assert feedback["previous_response"] == "Ответ без JSON"
    assert feedback["errors"][0]["type"] == "invalid_json"
