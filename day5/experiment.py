import json
import sys
import time
from datetime import datetime
from pathlib import Path

from openai import BadRequestError

sys.path.insert(0, str(Path(__file__).parent))

from config import JUDGE_MODEL, MODELS, complete
from prompts import REQUESTS

ATTEMPTS = 3
MODEL_ORDER = ("glm-4.5-flash", "glm-4.6", "glm-5.3")
PRICES_SOURCE = "docs.z.ai/guides/overview/pricing, цены за 1M токенов, сняты 2026-09-06"
RESULTS_PATH = Path(__file__).parent / "results.json"

JUDGE_PROMPT = """Ниже три ответа разных языковых моделей на один и тот же запрос. Оцени каждый ответ по шкале 0–10: точность, полнота, структура, отсутствие ошибок и воды.

{answers}

Запрос был такой: «{task}»

Верни строго валидный JSON без markdown-ограждений:
{{"ranking": [{{"id": "A", "score": 0, "comment": "краткое пояснение"}}], "best": "A", "verdict": "1-3 предложения по-русски: различается ли качество ответов здесь и какая модель оправдана для такого запроса"}}"""


def run_one(model: str, prompt: str) -> dict:
    messages = [{"role": "user", "content": prompt}]
    spec = MODELS[model]
    started = time.perf_counter()
    ttft_ms = None
    parts = []
    usage = None
    finish_reason = None
    stream = complete(messages, model, stream=True, temperature=0)
    for chunk in stream:
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.delta and choice.delta.content:
            if ttft_ms is None:
                ttft_ms = round((time.perf_counter() - started) * 1000)
            parts.append(choice.delta.content)
        if choice.finish_reason:
            finish_reason = choice.finish_reason
    latency_ms = round((time.perf_counter() - started) * 1000)
    prompt_tokens = usage.prompt_tokens if usage else None
    completion_tokens = usage.completion_tokens if usage else None
    if spec["free"]:
        cost_usd = 0.0
    elif prompt_tokens is not None and completion_tokens is not None:
        cost_usd = round(
            (prompt_tokens * spec["price_in"] + completion_tokens * spec["price_out"]) / 1e6,
            6,
        )
    else:
        cost_usd = None
    return {
        "content": "".join(parts),
        "ttft_ms": ttft_ms,
        "latency_ms": latency_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost_usd,
        "finish_reason": finish_reason,
    }


def fmt_cost(cost) -> str:
    if cost is None:
        return "н/д"
    if cost == 0:
        return "$0"
    return f"${cost:.6f}"


def median_attempt(runs: list) -> dict:
    ranked = sorted(
        runs,
        key=lambda r: (r["completion_tokens"] if r["completion_tokens"] is not None else 0, r["attempt"]),
    )
    return ranked[len(ranked) // 2]


def extract_json(text: str):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def judge_request(request: dict, candidates: list, rot: int):
    ordered = candidates[rot:] + candidates[:rot]
    letters = {}
    lines = []
    for i, cand in enumerate(ordered):
        letter = chr(ord("A") + i)
        letters[letter] = cand["model"]
        lines.append(f"Ответ {letter}:\n{cand['content']}")
    prompt = JUDGE_PROMPT.format(answers="\n\n".join(lines), task=request["prompt"])
    try:
        response = complete(
            [{"role": "user", "content": prompt}],
            JUDGE_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
        )
    except BadRequestError:
        response = complete([{"role": "user", "content": prompt}], JUDGE_MODEL, temperature=0)
    return extract_json(response.choices[0].message.content or ""), letters


def sanitize_judge(data, letters: dict):
    if not isinstance(data, dict):
        return None
    ranking = []
    seen = set()
    for item in data.get("ranking", []):
        if not isinstance(item, dict):
            continue
        letter = str(item.get("id") or "").strip().upper()
        model = letters.get(letter)
        if model is None or model in seen:
            continue
        seen.add(model)
        try:
            score = max(0, min(10, int(item.get("score"))))
        except (TypeError, ValueError):
            continue
        ranking.append({
            "model": model,
            "score": score,
            "comment": str(item.get("comment") or "")[:400],
        })
    if len(ranking) < 2:
        return None
    best = letters.get(str(data.get("best") or "").strip().upper())
    return {
        "ranking": ranking,
        "best": best or max(ranking, key=lambda r: r["score"])["model"],
        "verdict": str(data.get("verdict") or "")[:800],
    }


def run_all() -> dict:
    judge_enabled = "--no-judge" not in sys.argv
    runs = []
    judgements = []
    for req_index, request in enumerate(REQUESTS):
        print(f"запрос: {request['id']} — «{request['prompt']}»", flush=True)
        for model in MODEL_ORDER:
            for attempt in range(1, ATTEMPTS + 1):
                print(f"  {model} #{attempt} ...", end="", flush=True)
                run = run_one(model, request["prompt"])
                run.update({
                    "request_id": request["id"],
                    "model": model,
                    "attempt": attempt,
                    "score": None,
                    "comment": None,
                })
                runs.append(run)
                print(
                    f" {run['latency_ms']} мс (первый токен {run['ttft_ms']} мс),"
                    f" {run['completion_tokens']} токенов, {fmt_cost(run['cost_usd'])}",
                    flush=True,
                )
        if not judge_enabled:
            continue
        candidates = []
        for model in MODEL_ORDER:
            group = [
                r for r in runs
                if r["request_id"] == request["id"] and r["model"] == model
            ]
            candidates.append(median_attempt(group))
        print("  судья glm-5.3 (вслепую, A/B/C) ...", end="", flush=True)
        data, letters = judge_request(request, candidates, rot=req_index % len(MODEL_ORDER))
        verdict = sanitize_judge(data, letters)
        if verdict is None:
            print(" неполный вердикт — пропущено", flush=True)
            continue
        for item in verdict["ranking"]:
            judged = next(c for c in candidates if c["model"] == item["model"])
            judged["score"] = item["score"]
            judged["comment"] = item["comment"]
        judgements.append({
            "request_id": request["id"],
            "best": verdict["best"],
            "verdict": verdict["verdict"],
            "judged_attempts": [
                {"model": c["model"], "attempt": c["attempt"]} for c in candidates
            ],
        })
        print(f" лучший: {verdict['best']}", flush=True)
    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "prices_source": PRICES_SOURCE,
            "judge_model": JUDGE_MODEL if judgements else None,
            "judge_blind": True,
            "attempts": ATTEMPTS,
            "temperature": 0,
            "models": [
                {
                    "id": model,
                    "tier": MODELS[model]["tier"],
                    "tier_name": MODELS[model]["tier_name"],
                    "price_in": MODELS[model]["price_in"],
                    "price_out": MODELS[model]["price_out"],
                    "free": MODELS[model]["free"],
                    "note": MODELS[model]["note"],
                }
                for model in MODEL_ORDER
            ],
        },
        "requests": REQUESTS,
        "runs": runs,
        "judgements": judgements,
    }


def render_page(results: dict) -> None:
    template_path = Path(__file__).parent / "template.html"
    if not template_path.exists():
        print("template.html: отсутствует, страница не собрана")
        return
    template = template_path.read_text(encoding="utf-8")
    payload = json.dumps(results, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace("__RESULTS_JSON__", payload)
    (Path(__file__).parent / "index.html").write_text(page, encoding="utf-8")
    print("index.html: готово")


def main() -> None:
    if "--render-only" in sys.argv:
        results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    else:
        results = run_all()
        RESULTS_PATH.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("results.json: сохранено")
    render_page(results)


if __name__ == "__main__":
    main()
