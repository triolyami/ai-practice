"""Прогон сценария дня 20 через живой сервер + проверка трассы.

    .venv/bin/python day20/flow_run.py --list
    .venv/bin/python day20/flow_run.py cross-server
    .venv/bin/python day20/flow_run.py cross-server-explicit --model deepseek-v4-pro

Никаких новых эндпоинтов: постит сценарий в обычный /api/chat свежей
сессией, читает NDJSON-стрим, печатает трасса и вердикт flow.check.
Код выхода: 0 — сценарий прошёл, 1 — вердикт fail, 2 — ошибка хода.
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flow import SCENARIOS, check  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:7877"


def run(base_url: str, scenario_id: str, model: str | None) -> list[dict]:
    spec = SCENARIOS[scenario_id]
    body = {
        "session_id": f"flow-{scenario_id}-{int(time.time())}",
        "message": spec["prompt"],
        "config": {"tools": True},
    }
    if model:
        body["config"]["model"] = model
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    events = []
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if line:
                events.append(json.loads(line))
    return events


def report(events: list[dict], spec: dict) -> int:
    step = 0
    done = None
    for e in events:
        kind = e["event"]
        if kind == "tool_call":
            step += 1
            print(f"  {step}. вызов  {e['name']}  {json.dumps(e.get('arguments'), ensure_ascii=False)[:160]}")
        elif kind == "tool_result":
            mark = "ok" if e.get("ok") else "FAIL"
            print(f"      → {mark}  {str(e.get('preview', ''))[:140]}")
        elif kind == "error":
            print(f"Ошибка хода: {e.get('message')}")
            return 2
        elif kind == "done":
            done = e
    if done is None:
        print("Поток оборвался без done — вердикт невозможен")
        return 2

    meta = done.get("meta") or {}
    trace = meta.get("tool_calls") or []
    verdict = check(trace, spec)
    print()
    print(f"Трасса: {verdict['calls']} вызовов, серверы: "
          + (", ".join(verdict["servers"]) or "нет"))
    if verdict["hops_exact"] or verdict["hops_changed"]:
        print(f"Хопы: дословно {verdict['hops_exact']}, переписано {verdict['hops_changed']}")
    for c in verdict["criteria"]:
        print(f"  [{'ok' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}")
    print()
    print("ВЕРДИКТ:", "PASS" if verdict["ok"] else "FAIL")
    reply = (done.get("content") or "").strip()
    if reply:
        print("\nОтвет модели:\n" + reply[:800])
    return 0 if verdict["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", choices=sorted(SCENARIOS))
    parser.add_argument("--list", action="store_true", help="показать сценарии и выйти")
    parser.add_argument("--model", help="модель из реестра (по умолчанию — серверная)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"базовый URL сервера ({DEFAULT_URL})")
    args = parser.parse_args()

    if args.list:
        for sid, spec in SCENARIOS.items():
            print(f"{sid}\t{spec['title']}")
        return 0
    if not args.scenario:
        parser.error("укажите сценарий или --list")

    spec = SCENARIOS[args.scenario]
    print(f"Сценарий «{args.scenario}»: {spec['title']}")
    print(f"Промпт: {spec['prompt'][:120]}…\n")
    try:
        events = run(args.url, args.scenario, args.model)
    except OSError as exc:
        print(f"Сервер недоступен ({args.url}): {exc}")
        return 2
    return report(events, spec)


if __name__ == "__main__":
    sys.exit(main())
