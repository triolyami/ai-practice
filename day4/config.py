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
    "glm-4.6": {
        "thinking": "off",
        "note": "рассуждения отключены — температура влияет только на выбор слов",
    },
    "glm-5.3": {
        "thinking": "effort",
        "note": "всегда думает сам — проверяем, чувствительна ли к температуре видимая часть",
    },
}
DEFAULT_MODEL = "glm-4.6"
EFFORTS = ("low", "high", "max")
DEFAULT_EFFORT = "low"


def thinking_config(model: str, effort: str | None = None) -> dict:
    if MODELS[model]["thinking"] == "effort":
        return {"thinking": {"effort": effort if effort in EFFORTS else DEFAULT_EFFORT}}
    return {"thinking": {"type": "disabled"}}


def thinking_label(model: str, effort: str | None = None) -> str:
    if MODELS[model]["thinking"] == "effort":
        return f"effort: {effort if effort in EFFORTS else DEFAULT_EFFORT}"
    return "disabled"


def complete(messages: list, model: str, stream: bool = False, effort: str | None = None, **params):
    extra = thinking_config(model, effort)
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
