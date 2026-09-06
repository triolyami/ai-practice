import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import complete
from puzzle import GROUND_TRUTH, TASK

RESULTS_PATH = Path(__file__).parent / "results.json"

AGENTS = (
    {"id": "baseline", "name": "Прямой ответ", "instruction": "", "model": "glm-4.6"},
    {"id": "cot", "name": "Пошагово", "instruction": "Решай пошагово.", "model": "glm-4.6"},
    {
        "id": "experts",
        "name": "Группа экспертов",
        "instruction": "Задачу решает группа из трёх экспертов. Аналитик разбирает условия и фиксирует факты. Инженер строит на фактах решение задачи. Критик проверяет решение инженера на ошибки и даёт окончательный вердикт. Каждый эксперт должен предложить своё решение, после чего приведи финальный ответ группы.",
        "model": "glm-4.6",
    },
    {"id": "thinking", "name": "Нативное рассуждение", "instruction": "", "model": "glm-5.3"},
)


def compose(task: str, instruction: str) -> str:
    text = instruction.strip()
    return f"{text}\n\nЗадача:\n{task}" if text else task


def compute_metrics(content: str) -> dict:
    text = content.strip()
    return {"chars": len(text), "words": len(text.split())}


def run_agent(task: str, agent: dict) -> dict:
    content_text = compose(task, agent["instruction"])
    messages = [{"role": "user", "content": content_text}]
    started = time.perf_counter()
    print(f"агент: {agent['id']} ({agent['model']}) ...", flush=True)
    resp = complete(messages, model=agent["model"], temperature=0)
    content = resp.choices[0].message.content or ""
    usage = resp.usage
    phase = {
        "name": "solve",
        "content": content,
        "meta": {
            "model": agent["model"],
            "finish_reason": resp.choices[0].finish_reason,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        },
        "request": {"content": content_text, "params": {}},
    }
    print(f"    готово: {phase['meta']['completion_tokens']} токенов, {phase['meta']['latency_ms']} мс", flush=True)
    return {
        "id": agent["id"],
        "title": agent["name"],
        "content": content,
        "metrics": compute_metrics(content),
        "phases": [phase],
        "meta": {
            "model": phase["meta"]["model"],
            "finish_reason": phase["meta"]["finish_reason"],
            "prompt_tokens": phase["meta"]["prompt_tokens"],
            "completion_tokens": phase["meta"]["completion_tokens"],
            "latency_ms": phase["meta"]["latency_ms"],
        },
    }


def main() -> None:
    runs = []
    for agent in AGENTS:
        runs.append(run_agent(TASK, agent))
    payload = {
        "meta": {
            "task": TASK,
            "ground_truth": GROUND_TRUTH,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "runs": runs,
    }
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"сохранено: {RESULTS_PATH}", flush=True)


if __name__ == "__main__":
    main()
