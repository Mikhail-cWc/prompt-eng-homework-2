import gzip
import json
from contextlib import closing
from pathlib import Path

from bunker.storage import Store, encode
from scripts.verify_game import verify

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "outputs/rules-2.0.json.gz"
DATABASE = ROOT / "data/replay.sqlite3"


def main():
    with gzip.open(ARCHIVE, "rt", encoding="utf-8") as file:
        bundle = json.load(file)
    game_id = verify(bundle)["game_id"]
    with closing(Store(DATABASE).db) as db, db:
        inserted = db.execute(
            "INSERT OR IGNORE INTO games VALUES (?,?)",
            (game_id, encode(bundle["state"])),
        )
        if inserted.rowcount:
            db.executemany(
                "INSERT INTO events VALUES (?,?,?)",
                ((game_id, e["seq"], encode(e)) for e in bundle["events"]),
            )
            db.executemany(
                "INSERT INTO calls VALUES (?,?,?,?)",
                (
                    (c["id"], game_id, c["action_key"], encode(c))
                    for c in bundle["calls"]
                ),
            )
    print(f"Запись {game_id} доступна в {DATABASE}")


if __name__ == "__main__":
    main()
