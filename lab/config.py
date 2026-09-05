import os
from pathlib import Path

from openai import OpenAI


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
    "glm-4.6": {
        "thinking": {"type": "disabled"},
        "note": "рассуждения отключены — ограничения действуют на видимый ответ",
    },
    "glm-5.3": {
        "thinking": {"effort": "low"},
        "note": "всегда думает: max_tokens и stop могут сработать на скрытых рассуждениях (см. день 2)",
    },
}
DEFAULT_MODEL = "glm-4.6"


def complete(messages: list, model: str, **params):
    return client.chat.completions.create(
        model=model,
        messages=messages,
        extra_body={"thinking": MODELS[model]["thinking"]},
        **params,
    )
