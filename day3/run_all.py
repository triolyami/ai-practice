import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import complete
from puzzle import GROUND_TRUTH, TASK
from server import PIPELINES

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

PIPELINES_RUN = (
    {"id": "meta", "name": "Сначала промпт", "model": "glm-4.6"},
    {"id": "experts_multi", "name": "Эксперты по очереди", "model": "glm-4.6"},
)


def compose(task: str, instruction: str) -> str:
    text = instruction.strip()
    return f"{text}\n\nЗадача:\n{task}" if text else task


def compute_metrics(content: str) -> dict:
    text = content.strip()
    return {"chars": len(text), "words": len(text.split())}


def run_step(model: str, content_text: str, name: str) -> dict:
    messages = [{"role": "user", "content": content_text}]
    started = time.perf_counter()
    resp = complete(messages, model=model, temperature=0)
    content = resp.choices[0].message.content or ""
    usage = resp.usage
    return {
        "name": name,
        "content": content,
        "meta": {
            "model": model,
            "finish_reason": resp.choices[0].finish_reason,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        },
        "request": {"content": content_text, "params": {}},
    }


def run_agent(task: str, agent: dict) -> dict:
    content_text = compose(task, agent["instruction"])
    print(f"агент: {agent['id']} ({agent['model']}) ...", flush=True)
    phase = run_step(agent["model"], content_text, "solve")
    print(f"    готово: {phase['meta']['completion_tokens']} токенов, {phase['meta']['latency_ms']} мс", flush=True)
    return {
        "id": agent["id"],
        "title": agent["name"],
        "content": phase["content"],
        "metrics": compute_metrics(phase["content"]),
        "phases": [phase],
        "meta": phase["meta"],
    }


def run_pipeline(task: str, spec: dict) -> dict:
    plan = PIPELINES[spec["id"]](task, {})
    print(f"пайплайн: {spec['id']} ({spec['model']}) ...", flush=True)
    outputs = {}
    phases = []
    for name, build in plan:
        phase = run_step(spec["model"], build(outputs), name)
        outputs[name] = phase["content"]
        phases.append(phase)
        print(f"    шаг {name}: {phase['meta']['completion_tokens']} токенов, {phase['meta']['latency_ms']} мс", flush=True)
    final = phases[-1]["content"]
    return {
        "id": spec["id"],
        "title": spec["name"],
        "content": final,
        "metrics": compute_metrics(final),
        "phases": phases,
        "meta": {
            "model": spec["model"],
            "finish_reason": phases[-1]["meta"]["finish_reason"],
            "steps": len(phases),
            "prompt_tokens": sum(p["meta"]["prompt_tokens"] or 0 for p in phases),
            "completion_tokens": sum(p["meta"]["completion_tokens"] or 0 for p in phases),
            "latency_ms": sum(p["meta"]["latency_ms"] for p in phases),
        },
    }


def main() -> None:
    runs = []
    for agent in AGENTS:
        runs.append(run_agent(TASK, agent))
    for spec in PIPELINES_RUN:
        runs.append(run_pipeline(TASK, spec))
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
