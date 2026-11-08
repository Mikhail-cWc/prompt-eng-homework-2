import argparse
import json
from collections import Counter
from pathlib import Path

from bunker.domain import GameState
from bunker.storage import Store
from bunker.web import markdown_export


def verify(bundle):
    game = GameState.model_validate(bundle["state"])
    assert game.status == "completed", f"Партия не завершена: {game.status}"
    assert len(game.winners) == 3
    eliminated = [
        e.data["eliminated_id"] for e in game.history if e.kind == "elimination"
    ]
    assert len(eliminated) == len(set(eliminated)) == 3
    assert set(game.winners).isdisjoint(eliminated)
    alive = {p.id for p in game.players}
    revealed = {p.id: set() for p in game.players}
    for event in game.history:
        if event.kind == "reveal":
            keys = set(event.data["traits"])
            assert event.actor_id in alive and len(keys) == 2
            assert keys.isdisjoint(revealed[event.actor_id])
            if event.round == 1:
                assert "profession" in keys
            revealed[event.actor_id].update(keys)
        elif event.kind == "votes":
            assert {v["player_id"] for v in event.data["votes"]} == alive
            assert all(v["candidate_id"] in alive for v in event.data["votes"])
        elif event.kind == "elimination":
            assert event.data["eliminated_id"] in alive
            alive.remove(event.data["eliminated_id"])
    assert alive == set(game.winners)
    assert all(len(revealed[p]) == 6 for p in alive)
    for round_number in range(1, 4):
        if game.rules_version == "2.0":
            events = [e for e in game.history if e.round == round_number]
            ballots = [e for e in events if e.kind == "votes"]
            assert [e.data.get("stage") for e in ballots] == ["preliminary", "final"]
            defenses = [e for e in events if e.kind == "defense"]
            assert sorted(e.actor_id for e in defenses) == sorted(
                ballots[0].data["defense_candidates"]
            )
            assert all(ballots[0].seq < e.seq < ballots[1].seq for e in defenses)
            assert all(not e.data.get("reveal") for e in defenses)
            exits = [e for e in events if e.kind == "elimination"]
            assert len(exits) == 1 and exits[0].seq > ballots[1].seq
        speeches = [
            e for e in game.history if e.round == round_number and e.kind == "speech"
        ]
        assert len(speeches) <= 8
        assert all(n <= 2 for n in Counter(e.actor_id for e in speeches).values())
        assert all(a.actor_id != b.actor_id for a, b in zip(speeches, speeches[1:]))
        for event in (
            e for e in game.history if e.round == round_number and e.kind == "votes"
        ):
            assert all(v["player_id"] != v["candidate_id"] for v in event.data["votes"])
    for call in bundle["calls"]:
        context = call["input"]["context"]
        if "self" not in context:
            continue
        assert (
            "acts" not in context
            and "queue" not in context
            and "pending" not in context
        )
        for player in context["players"]:
            assert set(player) == {"id", "name", "alive", "revealed_traits"}
        assert all("note" not in event["data"] for event in context["history"])
    tools = [e for e in bundle["events"] if e["kind"] == "tool_result"]
    calls = bundle["calls"]
    return {
        "game_id": game.id,
        "rules_version": game.rules_version,
        "status": game.status,
        "winners": game.winners,
        "eliminations": eliminated,
        "public_events": len(game.history),
        "model_attempts": len(calls),
        "completed_calls": sum(c["status"] == "completed" for c in calls),
        "failed_calls": sum(c["status"] == "failed" for c in calls),
        "models": dict(Counter(c["model"] for c in calls)),
        "tool_calls": len(tools),
        "tool_hits": sum(bool(e["data"]["results"]) for e in tools),
        "input_tokens": sum(c["usage"].get("input_tokens", 0) for c in calls),
        "output_tokens": sum(c["usage"].get("output_tokens", 0) for c in calls),
        "pause_events": sum(
            e["data"].get("status") == "paused" for e in bundle["events"]
        ),
        "technical_pauses": sum(e["kind"] == "error" for e in bundle["events"]),
        "checks": [
            "6→3",
            "three_unique_eliminations",
            "speech_quotas",
            "no_consecutive_speaker",
            "no_self_votes",
            "player_context_isolation",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("game_id")
    args = parser.parse_args()
    store = Store("data/bunker.sqlite3")
    state = store.get(args.game_id)
    bundle = {
        "state": state.model_dump(),
        "events": store.events(state.id),
        "calls": store.calls(state.id, detail=True),
    }
    report = verify(bundle)
    outputs = Path("outputs")
    outputs.mkdir(exist_ok=True)
    (outputs / "latest.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2)
    )
    (outputs / "latest.md").write_text(markdown_export(state))
    (outputs / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
