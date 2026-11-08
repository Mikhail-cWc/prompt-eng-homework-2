from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    "domain",
    "cards",
    "rules",
    "storage",
    "context",
    "provider",
    "engine",
    "web",
]
EXPLANATIONS = {
    "domain": "Типы действий и отдельное представление игрока PlayerView.",
    "cards": "Раздача авторских карточек без повторов внутри категории.",
    "rules": "Код проверяет раскрытия, очередь, голоса и жеребьёвку.",
    "storage": "SQLite: история, вызовы, восстановление и поиск FTS5.",
    "context": "Контекст содержит свою карточку и публичную историю, без чужих секретов.",
    "provider": "Yandex Responses API: JSON Schema, поток публичного text и валидация.",
    "engine": "Этапы игры, ограниченная дискуссия, защита, голосование и повторы запросов.",
    "web": "FastAPI: сайт, управление партией, инспектор и события SSE.",
}


def build():
    cells = [
        nbf.v4.new_markdown_cell("""# Бункер · автономный театр LLM

Шесть LLM борются за три места. Полный Python-код включён из `bunker/`;
ячейки `%%bunker_module` загружают его в память. Сайт — в `frontend/`.
По умолчанию воспроизводится настоящая партия без API и ключей.
Запись сыграна по правилам 2.0: после первого голосования кандидаты защищаются.
Идея пользователя, реализация с Codex; результаты и выводы — в [REPORT.md](REPORT.md).
"""),
        nbf.v4.new_code_cell("""from pathlib import Path
import sys
import types
from IPython.display import Markdown, display

ROOT = Path.cwd()
if not (ROOT / "bunker").is_dir():
    ROOT = ROOT.parent
assert (ROOT / "bunker").is_dir(), "Откройте ноутбук из корня Agent_Theatre"

package = types.ModuleType("bunker")
package.__path__ = [str(ROOT / "bunker")]
sys.modules["bunker"] = package

"""),
    ]
    cells[1].source += """def load_bunker_module(line, cell):
    name = "bunker." + line.strip()
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / "bunker" / (line.strip() + ".py"))
    sys.modules[name] = module
    exec(compile(cell, module.__file__, "exec"), module.__dict__)

get_ipython().register_magic_function(load_bunker_module, "cell", "bunker_module")
"""
    for name in MODULES:
        source = (ROOT / "bunker" / f"{name}.py").read_text()
        cells.append(nbf.v4.new_markdown_cell(f"## {name}\n\n{EXPLANATIONS[name]}"))
        cells.append(nbf.v4.new_code_cell(f"%%bunker_module {name}\n" + source))
    cells.extend(
        [
            nbf.v4.new_markdown_cell("""## Настоящие результаты

Запись — `outputs/rules-2.0.json.gz`, стенограмма — `outputs/rules-2.0.md`,
проверка — `outputs/rules-2.0-verification.json`.
"""),
            nbf.v4.new_code_cell("""import gzip
import json

with gzip.open(ROOT / "outputs/rules-2.0.json.gz", "rt", encoding="utf-8") as file:
    bundle = json.load(file)
state = bundle["state"]
print("Партия:", state["id"], state["title"])
print("Статус:", state["status"], "Раунд:", state["round"])
print("Модельные вызовы:", len(bundle["calls"]))
names = {p["id"]: p["name"] for p in state["players"]}
print("Места получили:", ", ".join(names[i] for i in state["winners"]))
display(Markdown((ROOT / "outputs/rules-2.0.md").read_text()))
"""),
            nbf.v4.new_markdown_cell("""## Проверка потоковых ответов

`outputs/streaming_preflight.json`: четыре настоящие пробы трёх моделей,
включая повтор Qwen. Это отдельная проверка, не часть стенограммы.
"""),
            nbf.v4.new_code_cell(
                """streaming_path = ROOT / "outputs/streaming_preflight.json"
if streaming_path.exists():
    streaming_checks = json.loads(streaming_path.read_text())
    print("Настоящих HTTP-запросов:", streaming_checks.get("actual_http_calls"))
    for check in streaming_checks["models"]:
        print(check["model"], check["status"], "фрагментов:", len(check["prefixes"]))
    if streaming_checks.get("verification_note"):
        print(streaming_checks["verification_note"])
else:
    print("Потоковые пробы ещё не сохранены.")
"""
            ),
            nbf.v4.new_markdown_cell("""## Запуск новой партии

Установка и запуск сайта — в [README.md](README.md).
Для запуска здесь задайте ключи в `.env` и включите `RUN_LIVE`:
это **платные запросы**. При сбое партия сохраняется на паузе.
"""),
            nbf.v4.new_code_cell("""RUN_LIVE = False
if RUN_LIVE:
    from bunker.domain import GameConfig
    from bunker.engine import Engine
    from bunker.provider import YandexProvider
    from bunker.storage import Store

    live_store = Store(ROOT / "data/notebook.sqlite3")
    live_store.recover()
    live_engine = Engine(live_store, YandexProvider())
    game = live_engine.create(GameConfig())
    await live_engine.tasks[game.id]
    if game.status == "ready":
        live_engine.command(game.id, "start")
        await live_engine.tasks[game.id]
    print(game.id, game.status, game.error)
"""),
        ]
    )
    book = nbf.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python (Agent_Theatre .venv)",
                "language": "python",
                "name": "bunker",
            }
        },
    )
    nbf.write(book, ROOT / "LLM_Theatre.ipynb")


if __name__ == "__main__":
    build()
