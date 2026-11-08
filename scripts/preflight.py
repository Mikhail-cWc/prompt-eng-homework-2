import asyncio
import json
from pathlib import Path

from bunker.domain import MODELS, PlayerView, Probe, now
from bunker.provider import YandexProvider


async def main():
    provider = YandexProvider()
    records = []
    for model in MODELS:
        try:
            result = await provider.complete(
                model,
                PlayerView(
                    instructions='Ответь JSON {"status":"ok"}.',
                    context={"task": "Проверка подключения"},
                ),
                Probe,
            )
            Probe.model_validate(result.output)
            records.append({"model": model, "ok": True, **result.model_dump()})
            print(model, "OK", result.usage)
        except Exception as exc:
            records.append(
                {"model": model, "ok": False, "error": provider.safe_error(exc)}
            )
            print(model, records[-1]["error"])
    path = Path("outputs/preflight.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {"created_at": now(), "records": records}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
