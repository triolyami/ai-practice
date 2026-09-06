import os
from pathlib import Path

from openai import BadRequestError, OpenAI


def load_env(path: str = ".env") -> None:
    for base in (Path(__file__).parent, Path(__file__).parent.parent):
        p = base / path
        if p.exists():
            break
    else:
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_env()

client = OpenAI(
    api_key=os.environ["GLM_API_KEY"],
    base_url="https://api.z.ai/api/paas/v4/",
    timeout=180.0,
)

MODELS = {
    "glm-4.5-flash": {
        "tier": "weak",
        "tier_name": "Слабая",
        "thinking": {"type": "disabled"},
        "price_in": 0.0,
        "price_out": 0.0,
        "free": True,
        "note": "бесплатная; сама по умолчанию включает рассуждения, здесь отключены",
    },
    "glm-4.6": {
        "tier": "medium",
        "tier_name": "Средняя",
        "thinking": {"type": "disabled"},
        "price_in": 0.60,
        "price_out": 2.20,
        "free": False,
        "note": "рассуждения отключены",
    },
    "glm-5.3": {
        "tier": "strong",
        "tier_name": "Сильная",
        "thinking": {"effort": "low"},
        "price_in": 1.40,
        "price_out": 4.40,
        "free": False,
        "note": "всегда думает; effort low — минимальный доступный уровень",
    },
}
JUDGE_MODEL = "glm-5.3"


def complete(messages: list, model: str, stream: bool = False, **params):
    extra = {"thinking": MODELS[model]["thinking"]}
    if not stream:
        return client.chat.completions.create(
            model=model,
            messages=messages,
            extra_body=extra,
            **params,
        )
    extra["stream_options"] = {"include_usage": True}
    try:
        return client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            extra_body=extra,
            **params,
        )
    except BadRequestError:
        extra.pop("stream_options", None)
        return client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            extra_body=extra,
            **params,
        )
