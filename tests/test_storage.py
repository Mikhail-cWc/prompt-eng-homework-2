from bunker.domain import GameState


def test_search_filters_future_rounds_and_other_games(store, scenario):
    store.index_documents("first", scenario.documents)
    other = scenario.documents[0].model_copy(update={"id": "other-secret"})
    store.index_documents("second", [other])
    for round_number in range(1, 4):
        found = store.search("first", round_number, "вода фильтр")
        assert {d["id"] for d in found} == {
            f"doc{i}" for i in range(1, round_number + 1)
        }
        assert all("other-secret" != d["id"] for d in found)
    assert store.search("first", 1, '" OR * --') == []
    assert store.search("first", 1, "()?!") == []
    assert store.search("missing-game", 3, "вода") == []


def test_event_cursor_replays_only_missing_events_in_order(store):
    state = GameState()
    events = [store.emit(state, "test_only", {"index": i}) for i in range(5)]
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert [e["seq"] for e in store.events(state.id, after=2)] == [3, 4, 5]
    assert store.events(state.id, after=5) == []
    assert store.events("missing", after=0) == []


def test_recovery_does_not_change_completed_or_stopped_games(store):
    for status in ("completed", "stopped", "ready", "paused"):
        state = GameState(status=status)
        store.save(state)
    store.recover()
    assert {s.status for s in store.all()} == {
        "completed",
        "stopped",
        "ready",
        "paused",
    }
    assert all(store.events(s.id) == [] for s in store.all())
