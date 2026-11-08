import jsonschema
import pytest
from pydantic import ValidationError

from bunker.context import player_view
from bunker.domain import Intent, Narration, Speech, Vote
from bunker.provider import YandexProvider


@pytest.mark.parametrize(
    "schema,payload",
    [
        (
            Speech,
            {"text": "я" * 1200, "note": "п" * 1000, "stage_direction": "р" * 240},
        ),
        (Narration, {"text": "я" * 1200}),
        (Intent, {"kind": "topic", "goal": "ц" * 400, "note": "п" * 1000}),
        (Vote, {"candidate_id": "p2", "reason": "п" * 600, "note": "м" * 1000}),
    ],
)
def test_larger_outputs_fit_but_next_character_is_rejected(schema, payload):
    schema.model_validate(payload)
    for key, value in payload.items():
        if key in {"text", "note", "stage_direction", "goal", "reason"}:
            with pytest.raises(ValidationError):
                schema.model_validate({**payload, key: value + "я"})


@pytest.mark.parametrize(
    "phase,limit", [("speech", 1200), ("closing", 700), ("defense", 700)]
)
async def test_server_and_wire_schema_share_new_speech_limits(
    engine, ready_game, phase, limit
):
    state = ready_game
    state.phase = phase
    view = player_view(state, "p1", {"text_limit": limit})
    provider = YandexProvider.__new__(YandexProvider)
    params = provider.parameters("deepseek-v4.1-flash", Speech, view)
    assert params["max_output_tokens"] == 2400
    wire = params["text"]["format"]["schema"]
    speech = Speech(text="я" * limit, note="п" * 1000)
    jsonschema.validate(speech.model_dump(), wire)
    engine.check_speech(
        state, "p1", speech, closing=phase == "closing", defense=phase == "defense"
    )
    speech.text += "я"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(speech.model_dump(), wire)
    if phase != "speech":
        with pytest.raises(ValueError):
            engine.check_speech(
                state,
                "p1",
                speech,
                closing=phase == "closing",
                defense=phase == "defense",
            )
    assert f'"maxLength": {limit}' in provider.instructions(view, Speech)


async def test_long_speech_is_published_whole_and_note_remains_private(
    engine, ready_game, provider
):
    from bunker.domain import Intent

    state = ready_game
    state.phase = "speech"
    state.selected = "p1"
    state.selection = Intent(kind="topic", goal="TEST_ONLY")
    text, note = "я" * 1200, "м" * 1000
    provider.overrides[("speech", "p1")].append({"text": text, "note": note})
    await engine.step(state)
    assert state.history[-1].data["text"] == text
    assert "note" not in state.history[-1].data
    assert state.players[0].note == note
    assert engine.store.get(state.id).history[-1].data["text"] == text
    assert provider.counts[("speech", "p1")] == 1


def test_longer_reading_window_matches_the_new_text_size():
    from bunker.engine import Engine

    assert Engine.reading_duration("я" * 1200) == pytest.approx(1200 / 35)
    assert Engine.reading_duration("я" * 10000) == 40
