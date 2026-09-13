import time
from collections.abc import Iterator

from config import DEFAULT_MODEL, MODELS, complete
from tokens import breakdown, context_used_pct, fits, trim_to_fit

DEFAULT_NAME = "Ассистент"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — {name}, дружелюбный и полезный ИИ-ассистент. "
    "Отвечай на русском языке: кратко, точно и по делу."
)
MAX_TURNS = 20
MAX_CONTENT = 600_000
TEMPERATURE = 0
OVERFLOW_MODES = ("error", "trim")
RESPONSE_HEADROOM_LABEL = 8192


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
        est = breakdown(self.system_prompt, self.history, content)
        trimmed_turns = 0
        if not fits(est["total"], limit):
            if self.overflow == "trim":
                self.history, trimmed_turns = trim_to_fit(
                    self.system_prompt, self.history, content, limit
                )
                est = breakdown(self.system_prompt, self.history, content)
            if not fits(est["total"], limit):
                yield {"event": "error", "message": self._overflow_message(est, limit)}
                return

        started = time.perf_counter()
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
            yield {"event": "error", "message": f"Модель не приняла запрос: {str(exc)[:400]}"}
            return

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
            est,
            limit,
            trimmed_turns,
            finish_reason,
            usage,
            round((time.perf_counter() - started) * 1000),
        )
        self.history[-1]["meta"] = meta
        self.token_log.append({
            "turn": len(self.history) // 2,
            "request_est": est["request"],
            "history_est": est["history"],
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
        est: dict,
        limit: int,
        trimmed_turns: int,
        finish_reason: str | None,
        usage,
        latency_ms: int,
    ) -> dict:
        spec = MODELS[self.model]
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        est_error_pct = None
        if prompt_tokens:
            est_error_pct = round((est["total"] - prompt_tokens) / prompt_tokens * 100, 1)
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
                "system": est["system"],
                "history": est["history"],
                "request": est["request"],
                "total_est": est["total"],
                "est_error_pct": est_error_pct,
                "context_limit": limit,
                "context_used_pct": context_used_pct(est["total"], limit),
                "trimmed_turns": trimmed_turns,
            },
            "totals": dict(self.totals),
        }

    def _overflow_message(self, est: dict, limit: int) -> str:
        base = (
            f"Диалог не влезает в контекст: оценка {est['total']} токенов "
            f"(система {est['system']} + история {est['history']} + запрос {est['request']}), "
            f"лимит модели {limit} токенов (+{RESPONSE_HEADROOM_LABEL} на ответ)."
        )
        if self.overflow == "trim":
            return base + " Даже без старых реплик запрос слишком велик — начните новый чат или уменьшите сообщение."
        return base + " Переключите режим «при переполнении» на «обрезать историю» или начните новый чат."

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
