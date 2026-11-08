import pytest

from bunker.domain import Intent, Player, Speech, Vote
from bunker.rules import choose_speaker, resolve_votes, validate_reveal, validate_vote


def players():
    return [
        Player(
            id=f"p{i}",
            name=f"Тест {i}",
            model="test",
            personality="тест",
            traits={
                key: f"{key}-{i}"
                for key in (
                    "profession",
                    "health",
                    "skill",
                    "biography",
                    "hobby",
                    "baggage",
                )
            },
        )
        for i in range(1, 7)
    ]


def test_invalid_reveal():
    p = players()[0]
    with pytest.raises(ValueError):
        validate_reveal(p, ["health", "skill"], 1)
    p.revealed = ["profession", "health"]
    with pytest.raises(ValueError):
        validate_reveal(p, ["profession", "skill"], 2)
    with pytest.raises(ValueError):
        validate_reveal(p, ["skill", "skill"], 2)


def test_self_and_dead_votes():
    ps = players()
    ps[1].alive = False
    for candidate in ("p1", "p2", "unknown"):
        with pytest.raises(ValueError):
            validate_vote(
                "p1", Vote(candidate_id=candidate, reason="тест", note="план"), ps, []
            )


def test_priority_and_quota():
    intents = {
        "p1": Intent(kind="answer", reply_to=5, goal="ответ"),
        "p2": Intent(kind="topic", goal="тема"),
    }
    assert (
        choose_speaker(intents, {"p1": 2}, "p3", ["p1"], 5, ["p1", "p2", "p3"])[0]
        == "p2"
    )
    assert choose_speaker(intents, {}, "p3", ["p1"], 5, ["p1", "p2", "p3"])[0] == "p1"
    assert (
        choose_speaker(
            {"p3": Intent(kind="topic", goal="тема")},
            {},
            "p3",
            [],
            5,
            ["p1", "p2", "p3"],
        )
        is None
    )


def test_tie_is_not_elimination_until_runoff():
    votes = {"p1": "p2", "p2": "p1", "p3": "p2", "p4": "p1"}
    assert resolve_votes(votes, "seed", 1, False)[0] is None
    first = resolve_votes(votes, "seed", 1, True)
    assert first == resolve_votes(votes, "seed", 1, True)
    assert first[0] in {"p1", "p2"}


def test_speech_limits():
    with pytest.raises(ValueError):
        Speech(text="x" * 1201, note="план")


def test_known_intent_alias_is_normalized_without_inventing_content():
    intent = Intent(kind="speech", goal="Доказать пользу врача")
    assert intent.kind == "topic"
    assert intent.goal == "Доказать пользу врача"
    with pytest.raises(ValueError):
        Intent(kind="eliminate", goal="Самому исключить соседа")
