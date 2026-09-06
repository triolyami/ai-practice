import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import complete
from puzzle import GROUND_TRUTH, TASK
from strategies import EXTRA_ORDER, MAIN_ORDER, STRATEGIES, plan

RESULTS_PATH = Path(__file__).parent / "results.json"


def compute_metrics(content: str) -> dict:
    text = content.strip()
    return {"chars": len(text), "words": len(text.split())}


def run_strategy(task: str, strategy: str) -> dict:
    phases = []
    results = {}
    for step in plan(task, strategy):
        messages = step["build"](results)
        started = time.perf_counter()
        print(f"  {strategy} / {step['name']} ...", flush=True)
        resp = complete(messages, model=step["model"], temperature=0)
        content = resp.choices[0].message.content or ""
        usage = resp.usage
        phase = {
            "name": step["name"],
            "content": content,
            "meta": {
                "model": step["model"],
                "finish_reason": resp.choices[0].finish_reason,
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            },
            "request": {"content": messages[-1]["content"], "params": {}},
        }
        phases.append(phase)
        results[step["name"]] = content
        print(f"    готово: {phase['meta']['completion_tokens']} токенов, {phase['meta']['latency_ms']} мс", flush=True)
    final = phases[-1]
    return {
        "id": strategy,
        "title": STRATEGIES[strategy]["title"],
        "content": final["content"],
        "metrics": compute_metrics(final["content"]),
        "phases": phases,
        "meta": {
            "model": final["meta"]["model"],
            "finish_reason": final["meta"]["finish_reason"],
            "prompt_tokens": sum(p["meta"]["prompt_tokens"] or 0 for p in phases) or None,
            "completion_tokens": sum(p["meta"]["completion_tokens"] or 0 for p in phases) or None,
            "latency_ms": sum(p["meta"]["latency_ms"] for p in phases),
        },
    }


def main() -> None:
    order = list(MAIN_ORDER) + list(EXTRA_ORDER)
    runs = []
    for strategy in order:
        print(f"способ: {strategy}", flush=True)
        runs.append(run_strategy(TASK, strategy))
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
