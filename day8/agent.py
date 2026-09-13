import time
from collections.abc import Iterator

from config import DEFAULT_MODEL, MODELS, complete

DEFAULT_NAME = "Ассистент"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — {name}, дружелюбный и полезный ИИ-ассистент. "
    "Отвечай на русском языке: кратко, точно и по делу."
)
MAX_TURNS = 20
MAX_CONTENT = 600_000
TEMPERATURE = 0
OVERFLOW_MODES = ("error", "trim")

# По этим фразам в ответе провайдера понимаем, что отказ именно из-за
# переполнения контекста, а не из-за плохого ключа, сети и т.п.
CONTEXT_OVERFLOW_MARKERS = (
    "context length",
    "maximum context",
    "context window",
    "too many tokens",
    "prompt is too long",
    "input length",
    "превышает лимит",
    "превышен лимит",
)


def is_context_overflow(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is not None and status != 400:
        return False
    text = str(exc).lower()
    return any(marker in text for marker in CONTEXT_OVERFLOW_MARKERS)


class Agent:
    def __init__(
        self,
        name: str = DEFAULT_NAME,
        system_prompt: str | None = None,
        model: str = DEFAULT_MODEL,
        client=None,
        overflow: str = "error",
    ):
        self.name = (name or DEFAULT_NAME).strip() or DEFAULT_NAME
        self.model = model if model in MODELS else DEFAULT_MODEL
        self._client = client
        self.overflow = overflow if overflow in OVERFLOW_MODES else "error"
        self.history: list[dict] = []
        self.totals = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        self.token_log: list[dict] = []
        if system_prompt and system_prompt.strip():
            self.system_prompt = system_prompt.strip()
            self._default_prompt = False
        else:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=self.name)
            self._default_prompt = True

    def send(self, user_input: str) -> str:
        parts = []
        for event in self.send_stream(user_input):
            if event["event"] == "delta":
                parts.append(event["text"])
            elif event["event"] == "error":
                raise RuntimeError(event["message"])
        return "".join(parts)

    def send_stream(self, user_input: str) -> Iterator[dict]:
        content, err = self._validate(user_input)
        if err:
            yield {"event": "error", "message": err}
            return

        limit = MODELS[self.model]["context_limit"]
        started = time.perf_counter()

        # Точный размер запроса до отправки знает только провайдер, поэтому
        # никаких локальных проверок: отправляем как есть, а об отказе из-за
        # переполнения судим по ошибке самой модели. В режиме trim такой отказ
        # означает «забыть старейшую реплику и повторить».
        trimmed_turns = 0
        while True:
            try:
                stream = complete(
                    messages=self._messages(content),
                    model=self.model,
                    stream=True,
                    client=self._client,
                    temperature=TEMPERATURE,
                )
            except RuntimeError as exc:
                yield {"event": "error", "message": str(exc)}
                return
            except Exception as exc:
                if is_context_overflow(exc) and self.overflow == "trim" and self.history:
                    self.history = self.history[2:]
                    trimmed_turns += 1
                    continue
                yield {"event": "error", "message": self._request_error_message(exc)}
                return
            break

        parts: list[str] = []
        finish_reason = None
        usage = None
        try:
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta.content if choice.delta else None
                if delta:
                    parts.append(delta)
                    yield {"event": "delta", "text": delta}
        finally:
            try:
                stream.close()
            except Exception:
                pass

        reply = "".join(parts)
        self.history.append({"role": "user", "content": content})
        self.history.append({"role": "assistant", "content": reply})
        self._trim()

        meta = self._meta(
            limit,
            trimmed_turns,
            finish_reason,
            usage,
            round((time.perf_counter() - started) * 1000),
        )
        self.history[-1]["meta"] = meta
        self.token_log.append({
            "turn": len(self.history) // 2,
            "prompt_tokens": meta["prompt_tokens"],
            "completion_tokens": meta["completion_tokens"],
            "cost_usd": meta["cost_usd"],
            "context_used_pct": meta["tokens"]["context_used_pct"],
            "trimmed_turns": trimmed_turns,
            "totals": dict(self.totals),
        })

        yield {"event": "done", "content": reply, "meta": meta}

    def reset(self) -> None:
        self.history.clear()
        self.totals = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        self.token_log.clear()

    def configure(
        self,
        name: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        overflow: str | None = None,
    ) -> None:
        if model is not None:
            if model not in MODELS:
                raise ValueError(f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}.")
            self.model = model
        if overflow is not None:
            if overflow not in OVERFLOW_MODES:
                raise ValueError(
                    f"Неизвестный режим переполнения: {overflow}. Доступны: {', '.join(OVERFLOW_MODES)}."
                )
            self.overflow = overflow
        if name is not None and name.strip():
            self.name = name.strip()
        if system_prompt is not None and system_prompt.strip():
            self.system_prompt = system_prompt.strip()
            self._default_prompt = False
        if self._default_prompt:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=self.name)

    def describe(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "overflow": self.overflow,
            "turns": len(self.history) // 2,
            "messages": [dict(m) for m in self.history],
            "totals": dict(self.totals),
            "token_log": [dict(row) for row in self.token_log],
            "context_limit": MODELS[self.model]["context_limit"],
        }

    def _messages(self, content: str) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt}]
        messages += [{"role": m["role"], "content": m["content"]} for m in self.history]
        messages.append({"role": "user", "content": content})
        return messages

    def _meta(
        self,
        limit: int,
        trimmed_turns: int,
        finish_reason: str | None,
        usage,
        latency_ms: int,
    ) -> dict:
        spec = MODELS[self.model]
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        cost_usd = None
        if prompt_tokens is not None and spec.get("price_in") is not None:
            cost_usd = round(
                prompt_tokens / 1e6 * spec["price_in"]
                + (completion_tokens or 0) / 1e6 * spec["price_out"],
                6,
            )
        self.totals["requests"] += 1
        self.totals["prompt_tokens"] += prompt_tokens or 0
        self.totals["completion_tokens"] += completion_tokens or 0
        self.totals["cost_usd"] = round(self.totals["cost_usd"] + (cost_usd or 0.0), 6)
        used_pct = round(prompt_tokens / limit * 100, 1) if prompt_tokens else 0.0
        return {
            "agent": self.name,
            "model": self.model,
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "turns": len(self.history) // 2,
            "tokens": {
                "context_limit": limit,
                "context_used_pct": used_pct,
                "trimmed_turns": trimmed_turns,
            },
            "totals": dict(self.totals),
        }

    def _request_error_message(self, exc: Exception) -> str:
        if is_context_overflow(exc):
            detail = str(exc)[:400]
            if self.overflow == "trim":
                return f"Диалог не влезает в контекст даже без старых реплик — модель отказала: {detail}"
            return f"Модель не приняла запрос: диалог не влезает в контекстное окно. Ответ провайдера: {detail}"
        return f"Модель не приняла запрос: {str(exc)[:400]}"

    def _validate(self, user_input: str) -> tuple[str | None, str | None]:
        if not isinstance(user_input, str) or not user_input.strip():
            return None, "Пустой запрос."
        text = user_input.strip()
        if len(text) > MAX_CONTENT:
            return None, f"Сообщение длиннее {MAX_CONTENT} символов."
        return text, None

    def _trim(self) -> None:
        while len(self.history) > MAX_TURNS * 2:
            self.history.pop(0)
