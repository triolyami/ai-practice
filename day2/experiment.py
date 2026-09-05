import json
import sys
import time
from pathlib import Path

from config import MODEL, THINKING_DISABLED, complete

BASE_PROMPT = "Расскажи, как устроен интернет"
FORMAT_SUFFIX = (
    " Ответь строго валидным JSON без markdown-ограждений и пояснений: "
    '{"тема": "...", "суть": "кратко", "факты": ["..."]}'
)
LENGTH_SUFFIX = " Ответь не более чем 30 словами."
STOP_SUFFIX = " Заверши ответ после первого абзаца, не добавляя ничего после."

GROUPS = {
    "format": {
        "name": "Формат ответа",
        "question": "Заставит ли модель отвечать структурированным JSON?",
    },
    "length": {
        "name": "Длина ответа",
        "question": "Сдержит ли модель длину ответа?",
    },
    "stop": {
        "name": "Условие завершения",
        "question": "Сможем ли остановить генерацию в нужной точке?",
    },
}

VARIANTS = [
    {
        "id": "baseline",
        "group": None,
        "title": "Без ограничений",
        "mechanism": "Эталонный запуск: только базовый промпт, без дополнительных инструкций и параметров.",
        "prompt": BASE_PROMPT,
        "params": {},
    },
    {
        "id": "format-prompt",
        "group": "format",
        "title": "Инструкция в промпте",
        "mechanism": "Формат описан словами прямо в запросе. Для модели это просьба: обычно она слушается, но без гарантий.",
        "prompt": BASE_PROMPT + FORMAT_SUFFIX,
        "params": {},
    },
    {
        "id": "format-api",
        "group": "format",
        "title": "response_format: json_object",
        "mechanism": "Тот же промпт плюс API-параметр response_format. Сервер гарантирует парсируемый JSON, но схему всё равно описывает промпт.",
        "prompt": BASE_PROMPT + FORMAT_SUFFIX,
        "params": {"response_format": {"type": "json_object"}},
    },
    {
        "id": "length-prompt",
        "group": "length",
        "title": "Инструкция в промпте",
        "mechanism": "Просьба уложиться в 30 слов. Выполнит ли модель её — как повезёт.",
        "prompt": BASE_PROMPT + LENGTH_SUFFIX,
        "params": {},
    },
    {
        "id": "length-api",
        "group": "length",
        "title": "max_tokens = 60",
        "mechanism": "Базовый промпт плюс жёсткий лимит выходных токенов на стороне API: ответ обрывается на полуслове, finish_reason = length.",
        "prompt": BASE_PROMPT,
        "params": {"max_tokens": 60},
    },
    {
        "id": "stop-prompt",
        "group": "stop",
        "title": "Инструкция в промпте",
        "mechanism": "Явная инструкция остановиться после первого абзаца. Станет ли она границей текста — решает модель.",
        "prompt": BASE_PROMPT + STOP_SUFFIX,
        "params": {},
    },
    {
        "id": "stop-api",
        "group": "stop",
        "title": 'stop: ["\\n\\n"]',
        "mechanism": "Базовый промпт плюс stop-последовательность на стороне API: генерация обрывается на первом разрыве абзаца, остаток ответа просто не существует.",
        "prompt": BASE_PROMPT,
        "params": {"stop": ["\n\n"]},
    },
]


def compute_metrics(content: str) -> dict:
    text = content.strip()
    metrics = {
        "chars": len(text),
        "words": len(text.split()),
        "paragraphs": text.count("\n\n") + 1 if text else 0,
        "markdown_fence": text.startswith("```"),
        "ends_mid_sentence": bool(text) and text[-1] not in ".!?…»\"",
    }
    try:
        json.loads(text)
        metrics["valid_json"] = True
    except (json.JSONDecodeError, ValueError):
        metrics["valid_json"] = False
    return metrics


def run_variant(variant: dict) -> dict:
    started = time.perf_counter()
    response = complete(
        [{"role": "user", "content": variant["prompt"]}],
        temperature=0,
        **variant["params"],
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    choice = response.choices[0]
    content = choice.message.content or ""
    return {
        "id": variant["id"],
        "group": variant["group"],
        "title": variant["title"],
        "mechanism": variant["mechanism"],
        "request": {"prompt": variant["prompt"], "params": variant["params"]},
        "content": content,
        "finish_reason": choice.finish_reason,
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "latency_ms": elapsed_ms,
        "metrics": compute_metrics(content),
    }


def run_all() -> dict:
    runs = []
    for variant in VARIANTS:
        print(f"-> {variant['id']} ...", flush=True)
        run = run_variant(variant)
        runs.append(run)
        m = run["metrics"]
        print(
            f"   finish={run['finish_reason']} words={m['words']} "
            f"tokens={run['completion_tokens']} valid_json={m['valid_json']}",
            flush=True,
        )
    return {
        "meta": {
            "model": MODEL,
            "temperature": 0,
            "thinking": "disabled",
            "base_prompt": BASE_PROMPT,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "groups": GROUPS,
        "runs": runs,
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
        results = json.loads((Path(__file__).parent / "results.json").read_text(encoding="utf-8"))
    else:
        results = run_all()
        (Path(__file__).parent / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("results.json: сохранено")
    render_page(results)


if __name__ == "__main__":
    main()
