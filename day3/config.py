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

DEEPSEEK_KEY_MISSING = (
    "Для моделей DeepSeek нужен ключ DEEPSEEK_API_KEY — добавьте его "
    "в файл .env в корне репозитория и перезапустите сервер."
)

_clients = {}


def get_client(provider: str):
    if provider not in _clients:
        if provider == "zai":
            _clients[provider] = OpenAI(
                api_key=os.environ["GLM_API_KEY"],
                base_url="https://api.z.ai/api/paas/v4/",
                timeout=180.0,
            )
        elif provider == "deepseek":
            key = os.environ.get("DEEPSEEK_API_KEY", "")
            if not key:
                raise RuntimeError(DEEPSEEK_KEY_MISSING)
            _clients[provider] = OpenAI(
                api_key=key,
                base_url="https://api.deepseek.com/v1",
                timeout=180.0,
            )
        else:
            raise RuntimeError(f"Неизвестный провайдер: {provider}")
    return _clients[provider]

MODELS = {
    "glm-4.6": {
        "provider": "zai",
        "thinking": "off",
        "note": "рассуждения отключены — способ рассуждения задаёт только промпт",
    },
    "glm-5.3": {
        "provider": "zai",
        "thinking": "effort",
        "note": "всегда думает сам — усилие задаёт параметр effort",
    },
    "glm-5.3-flash": {
        "provider": "zai",
        "thinking": "effort",
        "note": "быстрая и дешёвая, тоже всегда думает — API отвергает отключение",
    },
    "deepseek-chat": {
        "provider": "deepseek",
        "thinking": "off",
        "note": "DeepSeek V3, без рассуждений",
    },
    "deepseek-reasoner": {
        "provider": "deepseek",
        "thinking": "native",
        "note": "рассуждает сам, рассуждение приходит отдельным полем",
    },
}
EFFORTS = ("low", "high", "max")
DEFAULT_EFFORT = "low"
DEFAULT_MODEL = "glm-4.6"


def thinking_config(model: str, effort: str | None = None) -> dict:
    spec = MODELS[model]
    if spec["thinking"] == "effort":
        return {"thinking": {"effort": effort if effort in EFFORTS else DEFAULT_EFFORT}}
    if spec["thinking"] == "off" and spec["provider"] == "zai":
        return {"thinking": {"type": "disabled"}}
    return {}


def thinking_label(model: str, effort: str | None = None) -> str:
    spec = MODELS[model]
    if spec["thinking"] == "effort":
        return f"effort: {effort if effort in EFFORTS else DEFAULT_EFFORT}"
    if spec["thinking"] == "native":
        return "native"
    return "disabled"


def missing_key(model: str) -> str | None:
    if MODELS[model]["provider"] == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
        return DEEPSEEK_KEY_MISSING
    return None


def complete(messages: list, model: str, stream: bool = False, effort: str | None = None, **params):
    client = get_client(MODELS[model]["provider"])
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
