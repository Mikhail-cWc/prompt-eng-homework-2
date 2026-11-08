import time

from fastapi.testclient import TestClient

from bunker.web import create_app


def test_api_controls_exports_and_inspector(tmp_path, provider):
    provider.configured = True
    with TestClient(create_app(tmp_path / "web.sqlite3", provider)) as client:
        assert client.get("/api/health").json()["configured"]
        assert client.get("/api/games/nope").status_code == 404
        created = client.post("/api/games", json={})
        assert created.status_code == 201
        game_id = created.json()["id"]
        for _ in range(100):
            state = client.get(f"/api/games/{game_id}").json()
            if state["status"] == "ready":
                break
            time.sleep(0.01)
        assert state["status"] == "ready"
        assert client.post("/api/games", json={}).status_code == 409
        assert (
            client.post(
                f"/api/games/{game_id}/commands", json={"action": "pause"}
            ).status_code
            == 409
        )
        calls = client.get(f"/api/games/{game_id}/calls").json()
        assert calls and "input" not in calls[0]
        detail = client.get(f"/api/games/{game_id}/calls/{calls[0]['id']}").json()
        assert detail["input"]["context"]
        inspector = client.get(f"/api/games/{game_id}/players/p1/inspector")
        assert inspector.status_code == 200
        assert inspector.json()["latest_call"] is None
        assert inspector.json()["note"] == ""
        assert (
            client.get(f"/api/games/{game_id}/players/nope/inspector").status_code
            == 404
        )
        assert "state" in client.get(f"/api/games/{game_id}/export").json()
        assert (
            "Реальная запись"
            in client.get(f"/api/games/{game_id}/export?format=markdown").text
        )
        assert (
            client.post(
                f"/api/games/{game_id}/commands", json={"action": "stop"}
            ).json()["status"]
            == "stopped"
        )
        assert (
            client.post(
                "/api/games", json={}, headers={"Origin": "https://outside.example"}
            ).status_code
            == 403
        )


def test_player_inspector_keeps_saved_note_separate_from_failed_answer(
    tmp_path, provider, scenario
):
    from bunker.domain import GameState, Player
    from bunker.storage import Store

    path = tmp_path / "inspector.sqlite3"
    store = Store(path)
    state = GameState(
        status="paused",
        scenario=scenario,
        players=[
            Player(id=f"p{i + 1}", model="TEST_ONLY", **p.model_dump())
            for i, p in enumerate(scenario.players)
        ],
    )
    state.players[0].note = "Принятый личный план"
    store.save(state)
    call = store.begin_call(
        state.id,
        "TEST_ONLY",
        "p1",
        "TEST_ONLY",
        "defense",
        {
            "context": {
                "self": {"id": "p1", "note": "Принятый личный план"},
                "round": 1,
                "phase": "defense",
            },
        },
    )
    call.update(status="failed", output={"note": "Непринятый план"})
    store.finish_call(call)
    store.db.close()
    with TestClient(create_app(path, provider)) as client:
        result = client.get(f"/api/games/{state.id}/players/p1/inspector").json()
        assert result["note"] == "Принятый личный план"
        assert result["latest_call"]["status"] == "failed"
        assert result["latest_call"]["phase"] == "defense"
        assert "input" not in result["latest_call"]
        assert result["note_call"] is None
        full = client.get(f"/api/games/{state.id}/calls/{call['id']}").json()
        assert full["input"]["context"]["self"]["id"] == "p1"
