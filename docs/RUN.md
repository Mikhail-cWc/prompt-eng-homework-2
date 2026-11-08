# Запуск «Бункера»

## Просмотр партии на сайте без ключей

Требуются Python 3.11+, uv и Node.js 20.19+ (либо 22.12+).

```sh
uv sync --locked
npm ci --prefix frontend
npm run build --prefix frontend
uv run --locked python -m scripts.load_replay
BUNKER_DB=data/replay.sqlite3 uv run --locked python -m bunker
```

Откройте [localhost:8000](http://127.0.0.1:8000) и нажмите «Смотреть запись».
Импорт сохраняет настоящие события и вызовы для инспектора в отдельной базе;
просмотр не обращается к API моделей.

## Демо на Render

Один Python Web Service на тарифе Free. В переменных окружения задайте
`BUNKER_READ_ONLY=1` и `BUNKER_DB=data/replay.sqlite3`. Сервис открывает запись,
карточки, журнал и экспорт. Команды управления игрой отключены; ключи не нужны.

**Build Command**

```sh
uv sync --locked --no-dev && npm ci --include=dev --prefix frontend && npm run build --prefix frontend
```

**Start Command**

```sh
.venv/bin/python -m scripts.load_replay && exec .venv/bin/uvicorn bunker.web:app --host 0.0.0.0 --port "$PORT" --workers 1
```

Запись импортируется из репозитория при старте, поэтому постоянный диск не нужен.

## Запуск новой партии

```sh
cp -n .env.sample .env
# Заполните folder_id и api_key, затем запустите сервер.
uv run --locked python -m bunker
```

Вместо копирования ключей можно указать `BUNKER_ENV_FILE=/absolute/path/to/.env`.
Откройте [localhost:8000](http://127.0.0.1:8000).
«Новая партия» делает платные запросы подготовки; затем доступна кнопка «Начать».
Игру можно приостановить, продолжить и остановить. Закрытие вкладки её не прерывает.

По два игрока используют DeepSeek V4.1 Flash, Qwen3.6 35B и Alice AI LLM Flash
через Yandex Responses API. Сценарист и ведущий — DeepSeek.
Ключи остаются на сервере, партии — в `data/bunker.sqlite3` (исключены из Git).
Без ключей доступны сохранённые локальные игры и просмотр экспорта в ноутбуке.

## Ноутбук и разработка

Python выполняется в проектной `.venv`. Ноутбук по умолчанию читает сохранённые
результаты (`RUN_LIVE=False`); полный код автоматически включается из `bunker/`.

```sh
uv sync --locked
uv run --locked python -m ipykernel install --prefix .venv --name bunker
uv run python scripts/build_notebook.py
uv run python scripts/execute_notebook.py
uv run pytest -q
uv run black --check bunker scripts tests
uv run ruff check bunker scripts tests
npm test --prefix frontend
npm run build --prefix frontend
```

Для интерактивного открытия можно установить JupyterLab в проект:

```sh
uv add --dev jupyterlab
JUPYTER_PATH="$PWD/.venv/share/jupyter" uv run jupyter lab LLM_Theatre.ipynb
```

Сайт: `npm run dev --prefix frontend` (прокси API на localhost:8000).
Экспорт и проверка завершённой локальной игры:
`uv run python -m scripts.verify_game GAME_ID` (создаёт локальный экспорт
и результаты проверки отдельно от записи для сдачи).
Проверки моделей: `scripts/preflight.py` и `scripts/probe_streaming.py`
делают платные запросы. В репозитории сохранены
[результаты проверки streaming](../outputs/streaming_preflight.json).
API: [localhost:8000/docs](http://127.0.0.1:8000/docs).

[Задание в учебном репозитории](https://github.com/MAILabs-Education/Agent_Theatre/blob/f4650bcc726c9c7de047d88b8a53b49e5247072c/README.md).
