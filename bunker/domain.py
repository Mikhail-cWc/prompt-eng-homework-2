from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TRAITS = ("profession", "health", "skill", "biography", "hobby", "baggage")
MODELS = ("deepseek-v4.1-flash", "qwen3.6-35b-a3b", "aliceai-llm-flash")
PUBLIC_TEXT_LIMIT = 1200
SHORT_TEXT_LIMIT = 700
NOTE_LIMIT = 1000


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Traits(StrictModel):
    profession: str = Field(min_length=1, max_length=250)
    health: str = Field(min_length=1, max_length=250)
    skill: str = Field(min_length=1, max_length=250)
    biography: str = Field(min_length=1, max_length=250)
    hobby: str = Field(min_length=1, max_length=250)
    baggage: str = Field(min_length=1, max_length=250)


class Character(StrictModel):
    name: str = Field(min_length=1, max_length=70)
    personality: str = Field(min_length=1, max_length=600)
    traits: Traits


class Document(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    title: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=2000)
    available_round: int = Field(ge=1, le=3)


class Act(StrictModel):
    round: int = Field(ge=1, le=3)
    title: str = Field(min_length=1, max_length=100)
    event: str = Field(min_length=1, max_length=800)


class Scenario(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    catastrophe: str = Field(min_length=1, max_length=1000)
    bunker: str = Field(min_length=1, max_length=1000)
    players: list[Character] = Field(min_length=6, max_length=6)
    documents: list[Document] = Field(min_length=3, max_length=9)
    acts: list[Act] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def unique_package(self):
        if sorted(a.round for a in self.acts) != [1, 2, 3]:
            raise ValueError("Нужны действия 1, 2, 3")
        if len({d.id for d in self.documents}) != len(self.documents):
            raise ValueError("Идентификаторы документов должны быть уникальны")
        if len({p.name for p in self.players}) != 6:
            raise ValueError("Имена персонажей должны быть различны")
        return self


class World(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    catastrophe: str = Field(min_length=1, max_length=1000)
    bunker: str = Field(min_length=1, max_length=1000)
    documents: list[Document] = Field(min_length=3, max_length=9)
    acts: list[Act] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_world(self):
        if sorted(a.round for a in self.acts) != [1, 2, 3]:
            raise ValueError("Нужны действия 1, 2, 3")
        if len({d.id for d in self.documents}) != len(self.documents):
            raise ValueError("Идентификаторы документов должны быть уникальны")
        return self


class Player(StrictModel):
    id: str
    name: str
    model: str
    personality: str
    traits: dict[str, str]
    revealed: list[str] = Field(default_factory=list)
    alive: bool = True
    note: str = ""


class GameConfig(StrictModel):
    models: list[str] = Field(
        default_factory=lambda: list(MODELS) * 2, min_length=6, max_length=6
    )
    director_model: str = MODELS[0]
    seed: str = Field(default_factory=lambda: uuid4().hex)
    debate_limit: Literal[8] = 8
    debate_seconds: Literal[600] = 600
    speech_quota: Literal[2] = 2
    reading_pause: bool = True


class Intent(StrictModel):
    kind: Literal["pass", "answer", "object", "topic"]
    reply_to: int | None = None
    goal: str = Field(default="", max_length=400)
    search_query: str | None = Field(default=None, max_length=200)
    note: str = Field(default="", max_length=NOTE_LIMIT)

    @field_validator("kind", mode="before")
    @classmethod
    def normalize_kind(cls, value):
        return {"speech": "topic", "reply": "answer", "objection": "object"}.get(
            value, value
        )


class Speech(StrictModel):
    text: str = Field(min_length=1, max_length=PUBLIC_TEXT_LIMIT)
    stage_direction: str = Field(default="", max_length=240)
    addressed_to: list[str] = Field(default_factory=list, max_length=5)
    reveal: list[
        Literal["profession", "health", "skill", "biography", "hobby", "baggage"]
    ] = Field(default_factory=list, max_length=2)
    citations: list[str] = Field(default_factory=list, max_length=3)
    note: str = Field(max_length=NOTE_LIMIT)


class Vote(StrictModel):
    candidate_id: str
    reason: str = Field(min_length=1, max_length=600)
    note: str = Field(max_length=NOTE_LIMIT)


class Narration(StrictModel):
    text: str = Field(min_length=1, max_length=PUBLIC_TEXT_LIMIT)
    winner_ids: list[str] = Field(default_factory=list)
    eliminated_id: str | None = None


class Probe(StrictModel):
    status: Literal["ok"]


class GameEvent(StrictModel):
    seq: int
    kind: str
    round: int
    data: dict
    actor_id: str | None = None
    created_at: str = Field(default_factory=now)


class ReadingPause(StrictModel):
    event_seq: int
    remaining: float = Field(ge=0)
    deadline: float | None = None


class GameState(StrictModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str = "Новая партия"
    created_at: str = Field(default_factory=now)
    status: str = "preparing"
    rules_version: Literal["1.0", "2.0"] = "1.0"
    round: int = 1
    phase: str = "preflight"
    config: GameConfig = Field(default_factory=GameConfig)
    scenario: Scenario | None = None
    players: list[Player] = Field(default_factory=list)
    history: list[GameEvent] = Field(default_factory=list)
    queue: list[dict] = Field(default_factory=list)
    debate_count: int = 0
    debate_counts: dict[str, int] = Field(default_factory=dict)
    debate_elapsed: float = 0
    cursor: int = 0
    pending: dict = Field(default_factory=dict)
    selected: str | None = None
    selection: Intent | None = None
    tool_result: list[dict] = Field(default_factory=list)
    vote_candidates: list[str] = Field(default_factory=list)
    resolved_id: str | None = None
    winners: list[str] = Field(default_factory=list)
    error: str | None = None
    operation: str | None = None
    reading: ReadingPause | None = None


class PlayerView(StrictModel):
    instructions: str
    context: dict


class ModelCallResult(StrictModel):
    output: dict
    raw_response: dict
    usage: dict
    duration_ms: float
