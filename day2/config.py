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
)

MODEL = "glm-4.6"
THINKING_DISABLED = {"thinking": {"type": "disabled"}}


def complete(messages: list, **params):
    return client.chat.completions.create(
        model=MODEL,
        messages=messages,
        extra_body=THINKING_DISABLED,
        **params,
    )
