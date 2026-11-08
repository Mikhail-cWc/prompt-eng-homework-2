import hashlib
from collections import Counter

from bunker.domain import TRAITS, Intent, Player, Vote


def validate_reveal(player: Player, reveal: list[str], round_number: int) -> None:
    if len(reveal) != 2 or len(set(reveal)) != 2:
        raise ValueError("Нужно раскрыть ровно две разные характеристики")
    if any(key not in TRAITS or key in player.revealed for key in reveal):
        raise ValueError("Характеристика неизвестна или уже раскрыта")
    if round_number == 1 and "profession" not in reveal:
        raise ValueError("В первом раунде обязательна профессия")


def validate_vote(
    actor: str, vote: Vote, players: list[Player], candidates: list[str]
) -> None:
    alive = {p.id for p in players if p.alive}
    if actor not in alive or vote.candidate_id == actor:
        raise ValueError("Нельзя голосовать за себя или от имени выбывшего")
    if vote.candidate_id not in alive or (
        candidates and vote.candidate_id not in candidates
    ):
        raise ValueError("Недопустимый кандидат на исключение")


def choose_speaker(
    intents: dict[str, Intent],
    counts: dict[str, int],
    last_actor: str | None,
    addressed: list[str],
    last_seq: int,
    order: list[str],
) -> tuple[str, str] | None:
    ranked = []
    for actor, intent in intents.items():
        if (
            actor not in order
            or actor == last_actor
            or counts.get(actor, 0) >= 2
            or intent.kind == "pass"
        ):
            continue
        direct = (
            intent.kind == "answer"
            and actor in addressed
            and intent.reply_to == last_seq
        )
        reply = intent.kind in {"answer", "object"} and intent.reply_to == last_seq
        priority = 0 if direct else 1 if reply else 2
        reason = (
            "Прямой ответ адресату"
            if direct
            else "Возражение к последней реплике" if reply else "Новая тема"
        )
        ranked.append(
            ((priority, counts.get(actor, 0), order.index(actor)), actor, reason)
        )
    if not ranked:
        return None
    _, actor, reason = min(ranked)
    return actor, reason + "; затем число выступлений и вращающийся порядок"


def resolve_votes(
    votes: dict[str, str], seed: str, round_number: int, runoff: bool
) -> tuple[str | None, list[str], str]:
    counts = Counter(votes.values())
    if not counts:
        raise ValueError("Нет голосов")
    tied = sorted(key for key, value in counts.items() if value == max(counts.values()))
    if len(tied) == 1:
        return tied[0], tied, "Наибольшее число голосов"
    if not runoff:
        return None, tied, "Равенство: одно переголосование"
    digest = hashlib.sha256(
        f"{seed}:{round_number}:{','.join(tied)}".encode()
    ).hexdigest()
    return (
        tied[int(digest, 16) % len(tied)],
        tied,
        f"Жеребьёвка SHA-256(seed:round:sorted_ids), digest={digest}",
    )
