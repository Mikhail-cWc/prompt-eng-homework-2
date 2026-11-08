async def test_host_can_report_actual_final_three_after_last_exclusion(
    engine, ready_game, provider, no_retry_delay
):
    state = ready_game
    state.status = "running"
    state.phase = "aftermath"
    state.round = 3
    state.resolved_id = "p6"
    for player in state.players:
        player.alive = player.id in {"p1", "p2", "p3"}
    actual = {
        "text": "Трое оставшихся получили места.",
        "winner_ids": ["p1", "p2", "p3"],
        "eliminated_id": "p6",
    }
    provider.overrides[("aftermath", "host")].extend([actual, actual])
    await engine.step(state)
    assert state.phase == "epilogue"
