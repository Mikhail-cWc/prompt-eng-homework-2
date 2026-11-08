import jsonschema
import pytest

from bunker.context import player_view
from bunker.domain import Speech, Vote
from bunker.provider import YandexProvider


async def test_wire_schema_rejects_names_and_self_vote(ready_game):
    provider = YandexProvider.__new__(YandexProvider)
    view = player_view(ready_game, "p1", {"candidates": ["p1", "p2", "p3"]})
    speech = Speech(
        text="Оставьте меня", note="защитить место", addressed_to=["Имя вместо ID"]
    )
    schema = provider.parameters("deepseek-v4.1-flash", Speech, view)["text"]["format"][
        "schema"
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(speech.model_dump(), schema)
    speech.addressed_to = ["p2"]
    jsonschema.validate(speech.model_dump(), schema)
    schema = provider.parameters("deepseek-v4.1-flash", Vote, view)["text"]["format"][
        "schema"
    ]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            Vote(candidate_id="p1", reason="сам", note="план").model_dump(), schema
        )
