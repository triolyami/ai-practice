"""Пробник тулколлинга: какие модели реально вызывают инструменты.

Для каждой модели из MODELS отправляет один тривиальный инструмент
(`add`) и промпт, который требует его вызвать — в потоковом и
непотоковом режиме. Печатает таблицу: модель / режим / пришли ли
tool_calls / finish_reason / текст ошибки. Работает без сервера:

    env -u all_proxy -u ALL_PROXY .venv/bin/python day18/tool_probe.py

Глубокая проверка: у thinking-моделей tool_calls могут не прийти —
провайдеры исторически капризничают; по таблице решаем, у каких моделей
в UI предупреждать.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import MODELS, complete  # noqa: E402

TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Сложить два числа",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "первое слагаемое"},
                "b": {"type": "number", "description": "второе слагаемое"},
            },
            "required": ["a", "b"],
        },
    },
}

PROMPT = (
    "Вызови инструмент add с аргументами a=2 и b=3. Не считай сам, "
    "не пиши текст ответа — только вызови инструмент."
)
MESSAGES = [{"role": "user", "content": PROMPT}]


def probe_nonstream(model: str) -> dict:
    try:
        resp = complete(MESSAGES, model=model, stream=False, tools=[TOOL], temperature=0)
    except Exception as exc:
        return {"calls": 0, "finish": None, "error": str(exc)[:160]}
    choice = resp.choices[0]
    calls = getattr(choice.message, "tool_calls", None) or []
    return {"calls": len(calls), "finish": choice.finish_reason, "error": None}


def probe_stream(model: str) -> dict:
    calls = {}
    finish = None
    try:
        stream = complete(MESSAGES, model=model, stream=True, tools=[TOOL], temperature=0)
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish = choice.finish_reason
                delta = choice.delta
                for tc in (getattr(delta, "tool_calls", None) or []) if delta else []:
                    idx = getattr(tc, "index", 0) or 0
                    slot = calls.setdefault(idx, {"name": "", "arguments": ""})
                    fn = getattr(tc, "function", None)
                    if fn:
                        slot["name"] += getattr(fn, "name", None) or ""
                        slot["arguments"] += getattr(fn, "arguments", None) or ""
        finally:
            stream.close()
    except Exception as exc:
        return {"calls": 0, "finish": finish, "error": str(exc)[:160]}
    return {"calls": len(calls), "finish": finish, "error": None}


def main() -> int:
    print(f"Пробник tool_calls: моделей {len(MODELS)}, инструмент «add»\n")
    print(f"{'модель':<20} {'режим':<10} {'calls':>5}  {'finish':<12} ошибка")
    print("-" * 78)
    bad = 0
    for model in MODELS:
        for mode, probe in (("stream", probe_stream), ("plain", probe_nonstream)):
            res = probe(model)
            err = (res["error"] or "").replace("\n", " ")
            print(f"{model:<20} {mode:<10} {res['calls']:>5}  {str(res['finish']):<12} {err}", flush=True)
            if res["calls"] == 0:
                bad += 1
    print()
    print("проб без единого tool_calls:", bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
