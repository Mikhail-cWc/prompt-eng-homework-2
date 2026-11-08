import asyncio
import json
from types import SimpleNamespace

import pytest

from bunker.context import player_view
from bunker.domain import ModelCallResult, PlayerView, Speech
from bunker.provider import PublicTextParser, YandexProvider, json_payload_text


@pytest.mark.parametrize("width", [1, 2, 3, 7, 300])
def test_stream_parser_only_emits_root_text_with_arbitrary_boundaries(width):
    expected = 'Привет, "мир"!\n🚀'
    source = json.dumps(
        {"note": "SECRET", "nested": {"text": "SECRET_NESTED"}, "text": expected},
        ensure_ascii=True,
    )
    parser = PublicTextParser()
    seen = []
    for offset in range(0, len(source), width):
        seen.append(parser.feed(source[offset : offset + width]))
    assert seen[-1] == expected
    assert all(expected.startswith(value) for value in seen)
    assert all("SECRET" not in value for value in seen)
    assert not any(any(0xD800 <= ord(c) <= 0xDFFF for c in value) for value in seen)


@pytest.mark.parametrize(
    "source",
    [
        '[{"text":"secret"}]',
        '{"nested":{"text":"secret"}}',
        '{"text":123}',
        'Here is JSON: {"text":"secret"}',
    ],
)
def test_parser_does_not_publish_nested_non_string_or_non_json_text(source):
    assert PublicTextParser().feed(source) == ""


@pytest.mark.parametrize("opener", ["```json", "```"])
def test_strict_fenced_json_compatibility_without_private_leaks(opener):
    payload = {"text": "Синтетическая проверка", "note": "SECRET_NOTE", "reveal": []}
    wrapped = f"  {opener}\n{json.dumps(payload, ensure_ascii=True)}\n```  \n"
    parser = PublicTextParser()
    prefixes = [parser.feed(char) for char in wrapped]
    assert prefixes[-1] == payload["text"]
    assert all(payload["text"].startswith(prefix) for prefix in prefixes)
    assert json.loads(json_payload_text(wrapped)) == payload
    Speech.model_validate(json.loads(json_payload_text(wrapped)))


@pytest.mark.parametrize(
    "source",
    [
        '```json\n{"text":"draft"}',
        'prose\n```json\n{"text":"draft"}\n```',
        '```json\n{"text":"draft"}\n```\nprose',
        '```json\n{"text":"draft"} {"text":"other"}\n```',
        '```python\n{"text":"draft"}\n```',
        '```json\n{"text":"draft"}\n```\n```json\n{}\n```',
    ],
)
def test_final_decoder_rejects_unclosed_fences_prose_and_multiple_roots(source):
    with pytest.raises(ValueError):
        json.loads(json_payload_text(source))


@pytest.mark.parametrize("phase", ["reveal", "defense"])
async def test_stream_is_private_until_validated_publication(
    engine, ready_game, provider, monkeypatch, phase
):
    state = ready_game
    state.status = "running"
    state.phase = phase
    if phase == "defense":
        state.rules_version = "2.0"
        state.vote_candidates = ["p1"]
    original = provider.complete
    observations = []

    async def streaming(model, view, schema, correction=None, on_text=None):
        if on_text:
            await on_text("Черновик")
            observations.append((list(state.players[0].revealed), list(state.history)))
            assert "Черновик" not in player_view(state, "p2", {}).model_dump_json()
        return await original(model, view, schema, correction)

    monkeypatch.setattr(provider, "complete", streaming)
    await engine.step(state)
    assert observations == [([], [])]
    events = [e for e in engine.store.events(state.id) if e["kind"] == "speech_stream"]
    assert [e["data"]["status"] for e in events] == [
        "generating",
        "generating",
        "validating",
        "accepted",
    ]
    assert events[-1]["data"]["public_seq"] == state.history[-1].seq
    assert events[-1]["seq"] > state.history[-1].seq
    assert len(state.players[0].revealed) == (2 if phase == "reveal" else 0)
    assert state.history[-1].kind == phase
    assert all(e.kind != "speech_stream" for e in state.history)


async def test_failed_streams_retry_four_times_and_reveal_nothing(
    engine, ready_game, provider, monkeypatch, no_retry_delay
):
    state = ready_game
    state.status = "running"
    state.phase = "reveal"

    async def invalid(model, view, schema, correction=None, on_text=None):
        await on_text("Непринятый текст")
        return ModelCallResult(
            output={
                "text": "Непринятый текст",
                "reveal": ["health", "skill"],
                "note": "SECRET",
            },
            raw_response={"fixture": "TEST_ONLY"},
            usage={},
            duration_ms=1,
        )

    monkeypatch.setattr(provider, "complete", invalid)
    await engine.run(state)
    assert state.status == "paused"
    assert not state.history and not state.players[0].revealed
    discarded = [
        e
        for e in engine.store.events(state.id)
        if e["kind"] == "speech_stream" and e["data"]["status"] == "discarded"
    ]
    assert len(discarded) == 4
    assert all(e["data"]["text"] == "" for e in discarded)


async def test_coalescing_flushes_pending_text_before_provider_completion(
    engine, ready_game, provider, monkeypatch
):
    state = ready_game
    state.status = "running"
    state.phase = "reveal"
    original = provider.complete

    async def streaming(model, view, schema, correction=None, on_text=None):
        await on_text("Один")
        await on_text("Один два")
        await asyncio.sleep(0.13)
        assert engine.store.current_stream(state.id)["text"] == "Один два"
        assert engine.store.current_stream(state.id)["status"] == "generating"
        assert not state.history
        return await original(model, view, schema, correction)

    monkeypatch.setattr(provider, "complete", streaming)
    await engine.step(state)
    accepted = engine.store.current_stream(state.id)
    await asyncio.sleep(0.11)
    assert engine.store.current_stream(state.id) == accepted
    assert accepted["status"] == "accepted"


async def test_stopped_stream_is_interrupted(engine, ready_game, provider, monkeypatch):
    started = asyncio.Event()

    async def blocked(model, view, schema, correction=None, on_text=None):
        await on_text("Начало")
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(provider, "complete", blocked)
    engine.command(ready_game.id, "start")
    await asyncio.wait_for(started.wait(), 2)
    engine.command(ready_game.id, "stop")
    await asyncio.gather(engine.tasks[ready_game.id], return_exceptions=True)
    snapshot = engine.store.presentation(ready_game.id)
    assert snapshot["stream"]["status"] == "interrupted"
    assert snapshot["stream"]["text"] == ""
    assert not ready_game.history


def test_restart_interrupts_draft_and_snapshot_cursor_is_consistent(store):
    from bunker.domain import GameState

    state = GameState(status="running")
    store.emit(
        state,
        "speech_stream",
        {
            "call_id": "test",
            "actor_id": "p1",
            "attempt": 1,
            "kind": "speech",
            "status": "generating",
            "text": "draft",
        },
    )
    store.recover()
    snapshot = store.presentation(state.id)
    assert snapshot["game"].status == "paused"
    assert snapshot["stream"]["status"] == "interrupted"
    assert snapshot["stream"]["seq"] <= snapshot["event_seq"]
    assert not snapshot["game"].history
    assert not store.events(state.id, snapshot["event_seq"])


async def test_request_timeout_covers_entire_stream_and_has_bounded_retry(
    engine, ready_game, provider, monkeypatch, no_retry_delay
):
    state = ready_game
    state.status = "running"
    state.phase = "reveal"
    engine.request_timeout = 0.01
    cancelled = []

    async def slow(model, view, schema, correction=None, on_text=None):
        await on_text("Первые слова")
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(provider, "complete", slow)
    await engine.run(state)
    assert len(cancelled) == 4
    assert state.status == "paused"
    calls = [c for c in engine.store.calls(state.id) if c["kind"] == "reveal"]
    assert len(calls) == 4
    assert all(c["status"] == "failed" and c["execution_uncertain"] for c in calls)
    assert not state.history and not state.players[0].revealed


class FakeStream:
    def __init__(self, events):
        self.events = events
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    def __aiter__(self):
        async def values():
            for event in self.events:
                yield event

        return values()


async def test_provider_stream_ignores_reasoning_and_preserves_actual_response(
    monkeypatch,
):
    provider = YandexProvider()
    provider.configured = True
    payload = {"text": "Ответ", "note": "SECRET"}
    encoded = json.dumps(payload, ensure_ascii=False)
    response = SimpleNamespace(
        output_text=encoded,
        status="completed",
        usage=None,
        model_dump=lambda **_: {"output": "TEST_ONLY_RAW", "status": "completed"},
    )
    stream = FakeStream(
        [
            SimpleNamespace(
                type="response.reasoning_text.delta", delta="SECRET_REASONING"
            ),
            *[
                SimpleNamespace(type="response.output_text.delta", delta=c)
                for c in encoded
            ],
            SimpleNamespace(type="response.completed", response=response),
        ]
    )
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        return stream

    monkeypatch.setattr(provider.client.responses, "create", create)
    received = []

    async def on_text(value):
        received.append(value)

    try:
        result = await provider.complete(
            "deepseek-v4.1-flash",
            PlayerView(instructions="TEST_ONLY", context={}),
            Speech,
            on_text=on_text,
        )
    finally:
        await provider.client.close()
    assert requests[0]["stream"] is True
    assert received[-1] == "Ответ"
    assert not any("SECRET" in text for text in received)
    assert result.output == payload
    assert result.raw_response["output"] == "TEST_ONLY_RAW"
    assert stream.closed


async def test_provider_rejects_eof_without_completed_event():
    provider = YandexProvider()
    stream = FakeStream(
        [SimpleNamespace(type="response.output_text.delta", delta='{"text":"draft"}')]
    )

    async def create(**kwargs):
        return stream

    provider.client.responses.create = create

    async def on_text(value):
        pass

    try:
        with pytest.raises(ConnectionError, match="оборвался"):
            await provider.stream({}, on_text)
    finally:
        await provider.client.close()
    assert stream.closed


def test_presentation_api_bootstrap_and_resume_cursor(tmp_path, provider):
    from fastapi.testclient import TestClient

    from bunker.domain import GameState
    from bunker.storage import Store
    from bunker.web import create_app

    path = tmp_path / "bootstrap.sqlite3"
    store = Store(path)
    try:
        state = GameState(status="paused")
        original = store.emit(
            state,
            "speech_stream",
            {
                "call_id": "TEST_ONLY",
                "actor_id": "p1",
                "attempt": 1,
                "kind": "speech",
                "status": "generating",
                "text": "Начало",
            },
        )
    finally:
        store.db.close()

    with TestClient(create_app(path, provider)) as client:
        snapshot = client.get(f"/api/games/{state.id}/presentation").json()
        assert snapshot["stream"]["status"] == "interrupted"
        assert snapshot["event_seq"] == snapshot["stream"]["seq"]
        assert original.seq < snapshot["stream"]["seq"]
        assert client.get("/api/games/missing/presentation").status_code == 404
    store = Store(path)
    try:
        later = store.emit(
            state, "speech_stream", {**original.data, "text": "Начало продолжено"}
        )
        missed = store.events(state.id, snapshot["event_seq"])
        assert [event["seq"] for event in missed] == [later.seq]
        assert missed[0]["data"]["text"] == "Начало продолжено"
    finally:
        store.db.close()


async def test_sse_reconnect_honors_last_event_id_without_repeating_drafts(
    engine, ready_game
):
    from bunker.web import create_app

    state = ready_game
    before = engine.store.emit(
        state,
        "speech_stream",
        {
            "call_id": "TEST_ONLY",
            "actor_id": "p1",
            "attempt": 1,
            "kind": "speech",
            "status": "generating",
            "text": "Сначала",
        },
    )
    after = engine.store.emit(
        state, "speech_stream", {**before.data, "text": "Сначала продолжение"}
    )
    app = create_app()
    app.state.engine = engine
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/games/{game_id}/events"
    )

    class Request:
        async def is_disconnected(self):
            return False

    response = await endpoint(
        state.id, Request(), after=0, last_event_id=str(before.seq)
    )
    body = await anext(response.body_iterator)
    await response.body_iterator.aclose()
    assert f"id: {after.seq}\n" in body
    assert f"id: {before.seq}\n" not in body
    assert "Сначала продолжение" in body
