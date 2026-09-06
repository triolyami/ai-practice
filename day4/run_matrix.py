import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import complete
from defaults import API_CAP, DEFAULT_PROMPT, FACT_CHECKS, MODEL_TEMPERATURES, SAMPLES

RESULTS_PATH = Path(__file__).parent / "results.json"


def run_one(model: str, temperature: float, sample: int) -> dict:
    messages = [{"role": "user", "content": DEFAULT_PROMPT}]
    started = time.perf_counter()
    resp = complete(messages, model=model, temperature=temperature)
    choice = resp.choices[0]
    content = choice.message.content or ""
    usage = resp.usage
    return {
        "model": model,
        "temperature": temperature,
        "sample": sample,
        "content": content,
        "finish_reason": choice.finish_reason,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "chars": len(content.strip()),
        "words": len(content.split()),
    }


def main() -> None:
    runs = []
    for model, temperatures in MODEL_TEMPERATURES.items():
        for temperature in temperatures:
            for sample in range(1, SAMPLES + 1):
                print(f"-> {model} t={temperature} #{sample} ...", flush=True)
                run = run_one(model, temperature, sample)
                runs.append(run)
                print(
                    f"   {run['words']} слов, {run['completion_tokens']} токенов, {run['latency_ms']} мс",
                    flush=True,
                )
    payload = {
        "meta": {
            "prompt": DEFAULT_PROMPT,
            "fact_checks": FACT_CHECKS,
            "model_temperatures": MODEL_TEMPERATURES,
            "api_cap": API_CAP,
            "samples": SAMPLES,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "runs": runs,
    }
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"сохранено: {RESULTS_PATH}", flush=True)

    print("\nИтог (различных ответов из общего числа):", flush=True)
    for model, temperatures in MODEL_TEMPERATURES.items():
        for temperature in temperatures:
            group = [r["content"] for r in runs if r["model"] == model and r["temperature"] == temperature]
            print(f"   {model} t={temperature}: {len(set(group))} из {len(group)}", flush=True)


if __name__ == "__main__":
    main()
