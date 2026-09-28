import os
import sys
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
    "deepseek-v4-flash": {
        "provider": "deepseek",
        "thinking": "native",
        "context_limit": 1_000_000,
        "price_in": 0.15,
        "price_out": 0.60,
        "tools_ok": True,
        "note": "быстрая, рассуждает сама — рассуждение приходит отдельным полем",
    },
    "deepseek-v4-pro": {
        "provider": "deepseek",
        "thinking": "native",
        "context_limit": 1_000_000,
        "price_in": 0.66,
        "price_out": 1.98,
        "tools_ok": True,
        "note": "старшая, рассуждает сама — рассуждение приходит отдельным полем",
    },
    "glm-4.6": {
        "provider": "zai",
        "thinking": "off",
        "context_limit": 200_000,
        "price_in": 0.60,
        "price_out": 2.20,
        "tools_ok": None,
        "note": "рассуждения отключены — быстрый вариант для чата (нужен баланс Z.ai)",
    },
    "glm-5.3": {
        "provider": "zai",
        "thinking": "effort",
        "context_limit": 1_000_000,
        "price_in": 1.40,
        "price_out": 4.40,
        "tools_ok": None,
        "note": "всегда думает: отвечает глубже, но медленнее (нужен баланс Z.ai)",
    },
}
DEFAULT_MODEL = "deepseek-v4-flash"


def thinking_config(model: str) -> dict:
    spec = MODELS[model]
    if spec["thinking"] == "off":
        return {"thinking": {"type": "disabled"}}
    if spec["thinking"] == "effort":
        return {"thinking": {"effort": "low"}}
    return {}


def thinking_label(model: str) -> str:
    spec = MODELS[model]
    if spec["thinking"] == "off":
        return "disabled"
    if spec["thinking"] == "effort":
        return "effort: low"
    return "native"


def missing_key(model: str) -> str | None:
    if MODELS[model]["provider"] == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
        return DEEPSEEK_KEY_MISSING
    return None


DAY18_DIR = Path(__file__).parent

# Реестр MCP-серверов. transport: "stdio" (command + args + опц. env/cwd —
# хаб порождает подпроцесс) или "http" (url — Streamable HTTP). Запись с
# неизвестным транспортом становится строкой со статусом error.
# Сюда же можно добавить, например:
#   {"id": "py-tools-http", "transport": "http", "url": "http://127.0.0.1:7875/mcp"}
#   (тот же tools_server.py, поднятый через `mcp run --transport streamable-http`).
MCP_SERVERS = [
    {
        "id": "py-tools",
        "transport": "stdio",
        # sys.executable — интерпретатор венва, где стоит пакет mcp
        "command": sys.executable,
        "args": [str(DAY18_DIR / "tools_server.py")],
    },
    {
        "id": "ts-tools",
        "transport": "stdio",
        # локальный tsx из day18/ts-tools/node_modules — без npx и PATH-танцев
        "command": "node",
        "args": [
            str(DAY18_DIR / "ts-tools" / "node_modules" / "tsx" / "dist" / "cli.mjs"),
            str(DAY18_DIR / "ts-tools" / "server.ts"),
        ],
    },
    {
        "id": "tracker",
        "transport": "stdio",
        # tracker_server.py поднимает REST API (tracker_api.py) потоком
        # внутри себя и пробрасывает вызовы инструментов по HTTP
        "command": sys.executable,
        "args": [str(DAY18_DIR / "tracker_server.py")],
    },
    {
        "id": "scheduler",
        "transport": "stdio",
        # scheduler_server.py держит SQLite-базу задач и daemon-тикер
        # внутри своего процесса: умер хаб — умер и тикер, сирот нет
        "command": sys.executable,
        "args": [str(DAY18_DIR / "scheduler_server.py")],
    },
]


def complete(messages: list, model: str, stream: bool = False, client: OpenAI | None = None, **params):
    cli = client or get_client(MODELS[model]["provider"])
    extra = thinking_config(model)
    if not stream:
        return cli.chat.completions.create(
            model=model,
            messages=messages,
            extra_body=extra or None,
            **params,
        )
    extra["stream_options"] = {"include_usage": True}
    try:
        return cli.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            extra_body=extra,
            **params,
        )
    except BadRequestError:
        extra.pop("stream_options", None)
        return cli.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            extra_body=extra,
            **params,
        )
