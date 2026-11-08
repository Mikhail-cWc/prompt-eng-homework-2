import argparse
import asyncio
import json
import time
from pathlib import Path

from bunker.domain import MODELS, PlayerView, Speech, now
from bunker.provider import YandexProvider


async def main(models=MODELS, append=False):
    provider = YandexProvider()
    path = Path(__file__).resolve().parents[1] / "outputs/streaming_preflight.json"
    results = (
        json.loads(path.read_text())
        if append
        else {
            "created_at": now(),
            "purpose": "Three real standalone streaming Speech probes; no game created",
            "models": [],
        }
    )
    try:
        for model in models:
            started = time.perf_counter()
            prefixes = []

            async def on_text(value):
                prefixes.append(
                    {
                        "elapsed_ms": (time.perf_counter() - started) * 1000,
                        "text": value,
                    }
                )

            record = {
                "model": model,
                "schema": "Speech",
                "prefixes": prefixes,
                "attempt": sum(item["model"] == model for item in results["models"])
                + 1,
            }
            try:
                result = await provider.complete(
                    model,
                    PlayerView(
                        instructions='Техническая проверка потока. Верни JSON Speech: text="Я хочу остаться в бункере.", note="Проверка связи", stage_direction="", addressed_to=[], reveal=[], citations=[].',
                        context={
                            "task": {
                                "action": "Короткая проверка потокового JSON Speech"
                            }
                        },
                    ),
                    Speech,
                    on_text=on_text,
                )
                record.update(result.model_dump())
                Speech.model_validate(result.output)
                record.update(
                    status=(
                        "passed"
                        if prefixes and prefixes[-1]["text"] == result.output["text"]
                        else "failed"
                    ),
                    **result.model_dump(),
                )
                if record["status"] == "failed":
                    record["error"] = "Public stream did not match validated text"
            except Exception as exc:
                record.update(status="failed", error=provider.safe_error(exc))
            record["elapsed_ms"] = (time.perf_counter() - started) * 1000
            results["models"].append(record)
            results["actual_http_calls"] = len(results["models"])
            if append:
                results["verification_note"] = (
                    "The original Qwen failure preserved its actual validation error but not full raw response. One authorized Qwen-only retry verifies strict Markdown-envelope compatibility; original three records retained."
                )
            serialized = json.dumps(results, ensure_ascii=False, indent=2)
            for secret in (provider.key, provider.folder):
                if secret:
                    serialized = serialized.replace(secret, "[скрыто]")
            path.write_text(serialized)
            print(
                f"{model}: {record['status']}; {len(prefixes)} public prefixes; {record['elapsed_ms']:.0f} ms",
                flush=True,
            )
    finally:
        await provider.client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    asyncio.run(main([args.model] if args.model else MODELS, args.append))
