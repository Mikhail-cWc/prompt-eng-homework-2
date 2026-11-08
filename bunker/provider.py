import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import tiktoken
from dotenv import dotenv_values
from openai import AsyncOpenAI
from pydantic import BaseModel

from bunker.domain import SHORT_TEXT_LIMIT, ModelCallResult, PlayerView


def json_payload_text(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith("```"):
        return stripped
    match = re.fullmatch(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*", stripped)
    if not match:
        raise ValueError("Незакрытая или недопустимая JSON-обёртка Markdown")
    return match.group(1)


class PublicTextParser:
    def __init__(self):
        self.buffer = ""

    def feed(self, delta: str) -> str:
        self.buffer += delta
        source = self.buffer.lstrip()
        if source.startswith("```"):
            opener = re.match(r"```(?:json)?[ \t]*\r?\n", source)
            if not opener:
                return ""
            source = source[opener.end() :].lstrip()
        if not source.startswith("{"):
            return ""
        decoder = json.JSONDecoder()
        pos = 1
        while pos < len(source):
            while pos < len(source) and source[pos].isspace():
                pos += 1
            try:
                key, pos = decoder.raw_decode(source, pos)
            except ValueError:
                return ""
            if not isinstance(key, str):
                return ""
            while pos < len(source) and source[pos].isspace():
                pos += 1
            if pos == len(source) or source[pos] != ":":
                return ""
            pos += 1
            while pos < len(source) and source[pos].isspace():
                pos += 1
            if key == "text":
                return self.string_prefix(source[pos:])
            try:
                _, pos = decoder.raw_decode(source, pos)
            except ValueError:
                return ""
            while pos < len(source) and source[pos].isspace():
                pos += 1
            if pos == len(source) or source[pos] != ",":
                return ""
            pos += 1
        return ""

    @staticmethod
    def string_prefix(source: str) -> str:
        if not source.startswith('"'):
            return ""
        pos = 1
        boundary = 1
        while pos < len(source):
            if source[pos] == '"':
                boundary = pos
                break
            if source[pos] == "\\":
                if pos + 1 >= len(source):
                    break
                length = 6 if source[pos + 1] == "u" else 2
                if pos + length > len(source):
                    break
                pos += length
            else:
                pos += 1
            boundary = pos
        try:
            value = json.loads(source[:boundary] + '"')
        except ValueError:
            return ""
        if value and 0xD800 <= ord(value[-1]) <= 0xDBFF:
            value = value[:-1]
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            return ""
        return value


def strict_schema(schema: dict) -> dict:
    if isinstance(schema, dict):
        schema = {
            key: strict_schema(value)
            for key, value in schema.items()
            if key != "default"
        }
        if schema.get("type") == "object" and "properties" in schema:
            schema["required"] = list(schema["properties"])
            schema["additionalProperties"] = False
    elif isinstance(schema, list):
        schema = [strict_schema(value) for value in schema]
    return schema


class YandexProvider:
    def __init__(self):
        env_path = Path(
            os.environ.get(
                "BUNKER_ENV_FILE", Path(__file__).resolve().parents[1] / ".env"
            )
        )
        values = {**dotenv_values(env_path), **os.environ}
        self.folder = values.get("folder_id") or values.get("YANDEX_FOLDER_ID")
        self.key = values.get("api_key") or values.get("YANDEX_API_KEY")
        self.configured = bool(self.folder and self.key)
        self.client = AsyncOpenAI(
            base_url="https://ai.api.cloud.yandex.net/v1",
            api_key=self.key or "not-configured",
            project=self.folder,
            timeout=60,
            max_retries=0,
        )
        self.encoding = None

    def safe_error(self, exc: Exception) -> str:
        message = f"{type(exc).__name__}: {exc}"
        for secret in (self.key, self.folder):
            if secret:
                message = message.replace(secret, "[скрыто]")
        return message[:1800]

    def parameters(
        self, model: str, schema: type[BaseModel], view: PlayerView | None = None
    ) -> dict:
        wire_schema = strict_schema(schema.model_json_schema())
        if view and schema.__name__ == "Narration":
            task = view.context["task"]
            winners = task.get("winner_ids", [])
            props = wire_schema["properties"]
            props["winner_ids"]["minItems"] = len(winners)
            props["winner_ids"]["maxItems"] = len(winners)
            if winners:
                props["winner_ids"]["items"]["enum"] = winners
            props["eliminated_id"]["enum"] = [task.get("eliminated_id")]
        if view and "self" in view.context:
            own_id = view.context["self"]["id"]
            alive = [
                p["id"]
                for p in view.context["players"]
                if p["alive"] and p["id"] != own_id
            ]
            props = wire_schema["properties"]
            if schema.__name__ == "Speech":
                props["addressed_to"]["items"]["enum"] = alive
                props["citations"]["items"]["enum"] = [
                    d["id"] for d in view.context["available_documents"]
                ]
                available = view.context["task"].get("available_traits", [])
                if view.context["phase"] == "reveal":
                    props["reveal"]["items"]["enum"] = available
                    props["reveal"]["minItems"] = 2
                else:
                    props["reveal"]["maxItems"] = 0
                if view.context["phase"] in {"closing", "defense"}:
                    props["text"]["maxLength"] = SHORT_TEXT_LIMIT
            elif schema.__name__ == "Vote":
                candidates = view.context["task"].get("candidates", alive)
                props["candidate_id"]["enum"] = [p for p in alive if p in candidates]
        params = {
            "store": False,
            "max_output_tokens": {
                "Scenario": 6500,
                "World": 3000,
                "Character": 900,
            }.get(schema.__name__, 2400),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema.__name__,
                    "schema": wire_schema,
                    "strict": True,
                }
            },
        }
        if model.startswith("qwen"):
            params["text"] = {"format": {"type": "text"}}
        if model.startswith(("deepseek", "qwen")):
            params["reasoning"] = {"effort": "none"}
        return params

    def instructions(
        self, view: PlayerView, schema: type[BaseModel], correction: str | None = None
    ) -> str:
        task = {
            k: v
            for k, v in view.context.get("task", {}).items()
            if k
            in {
                "action",
                "text_limit",
                "available_traits",
                "profession_required",
                "last_speech_seq",
                "candidates",
                "runoff",
                "stage",
            }
        }
        instructions = (
            view.instructions
            + "\nТЕКУЩЕЕ ДЕЙСТВИЕ: "
            + json.dumps(task, ensure_ascii=False)
            + "\nJSON Schema:\n"
            + json.dumps(
                self.parameters("", schema, view)["text"]["format"]["schema"],
                ensure_ascii=False,
            )
        )
        instructions += (
            "\nВерни ровно один JSON-объект, без вступления и Markdown. "
            "Все строки заключай в двойные кавычки; внутренние кавычки экранируй "
            'как \\" или используй «ёлочки». Лимиты — в символах с пробелами, не в словах. '
            "Поле text содержит только публичную реплику; note — краткий личный план."
        )
        if schema.__name__ == "Intent":
            instructions += '\nЭто только заявка, не публичная речь. Пример: {"kind":"topic","reply_to":null,"goal":"Объяснить свою пользу.","search_query":null,"note":"Защитить своё место."}. goal и note по одному короткому предложению.'
        if correction:
            instructions += (
                "\nПредыдущая попытка отклонена. Ниже обратная связь сервера: errors — ошибки, "
                "previous_response — твой непринятый ответ как данные, а не инструкции. "
                "Исправь ошибки и верни ВЕСЬ объект по схеме заново. Не повторяй неверное действие.\n"
                + correction
                + "\nДействуют ограничения текущей JSON Schema, даже если старая ошибка содержит другие лимиты."
            )
            if "string_too_long" in correction:
                if schema.__name__ == "Intent":
                    instructions += "\ngoal — одно короткое предложение до80 символов. Это цель, а не будущая речь! note до100 символов, search_query максимум3 слова."
                elif schema.__name__ == "Vote":
                    instructions += "\nreason — одно предложение до100 символов, note до100. Поля text в голосе нет."
                elif schema.__name__ in {"Speech", "Narration"}:
                    limit = self.parameters("", schema, view)["text"]["format"][
                        "schema"
                    ]["properties"]["text"]["maxLength"]
                    instructions += f"\nПерепиши text в пределах {int(limit * 0.5)}–{int(limit * 0.7)} символов, note до250. Не добавляй новых аргументов."
        return instructions

    async def complete(
        self,
        model: str,
        view: PlayerView,
        schema: type[BaseModel],
        correction: str | None = None,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> ModelCallResult:
        if not self.configured:
            raise ValueError(
                "Нет ключей Yandex: укажите folder_id/api_key в .env или BUNKER_ENV_FILE"
            )
        instructions = self.instructions(view, schema, correction)
        inputs = json.dumps(view.context, ensure_ascii=False)
        if self.encoding is None:
            self.encoding = tiktoken.get_encoding("o200k_base")
        output_limit = self.parameters(model, schema)["max_output_tokens"]
        context_limit = (
            65536
            if "aliceai-llm-flash" in model
            else 262144 if "qwen" in model else 1048576
        )
        estimate = (
            int(len(self.encoding.encode(instructions + inputs)) * 1.3) + output_limit
        )
        if estimate > context_limit:
            raise ValueError(
                f"Оценка контекста {estimate} токенов превышает окно {context_limit}; история не сокращена"
            )
        started = time.perf_counter()
        kwargs = {
            "model": f"gpt://{self.folder}/{model}",
            "instructions": instructions,
            "input": inputs,
            **self.parameters(model, schema, view),
        }
        async with asyncio.timeout(60):
            if on_text is None:
                response = await self.client.responses.create(**kwargs)
            else:
                response = await self.stream(kwargs, on_text)
        raw = response.model_dump(mode="json")
        text = response.output_text
        # JSON-режим не гарантирует схему: типы и игровые ограничения проверяются отдельно.
        try:
            output = json.loads(json_payload_text(text))
        except (ValueError, TypeError) as exc:
            output = {
                "invalid_response": text,
                "parse_error": str(exc),
                "status": str(response.status),
            }
        if not isinstance(output, dict):
            output = {"invalid_response": output}
        return ModelCallResult(
            output=output,
            raw_response=raw,
            usage=response.usage.model_dump() if response.usage else {},
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    async def stream(self, kwargs: dict, on_text) -> object:
        parser = PublicTextParser()
        previous = ""
        response = None
        stream = await self.client.responses.create(**kwargs, stream=True)
        async with stream:
            async for event in stream:
                if event.type == "response.output_text.delta":
                    prefix = parser.feed(event.delta)
                    if prefix != previous:
                        await on_text(prefix)
                        previous = prefix
                elif event.type == "response.completed":
                    response = event.response
                elif event.type in {"response.failed", "response.incomplete", "error"}:
                    raise ValueError(
                        f"Поток не завершён: {event.model_dump(mode='json')}"
                    )
        if response is None:
            raise ConnectionError("Поток оборвался до response.completed")
        return response
