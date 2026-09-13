import time
from collections.abc import Iterator

from config import DEFAULT_MODEL, MODELS, complete
from facts import (
    FACTS_CHUNK,
    cap_pairs,
    facts_text,
    render_facts_message,
    update_facts,
)
from tokens import breakdown, context_used_pct, estimate_text

DEFAULT_NAME = "Ассистент"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — {name}, дружелюбный и полезный ИИ-ассистент. "
    "Отвечай на русском языке: кратко, точно и по делу."
)
STRATEGY_MODES = ("window", "facts", "branches")
MODE_LABELS = {
    "window": "скользящее окно",
    "facts": "факты (key-value)",
    "branches": "ветки диалога",
}
DEFAULT_STRATEGY = "window"
WINDOW_DEFAULT = 10
WINDOW_MIN = 2
WINDOW_MAX = 50
MAX_TURNS = 250
MAX_CONTENT = 600_000
TEMPERATURE = 0

EMPTY_BUCKET = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}


def _bucket(value) -> dict:
    out = dict(EMPTY_BUCKET)
    if isinstance(value, dict):
        for key in out:
            v = value.get(key)
            if isinstance(v, (int, float)):
                out[key] = v
    return out


def _clamp_window(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return WINDOW_DEFAULT
    return max(WINDOW_MIN, min(WINDOW_MAX, int(value)))


class Agent:
    def __init__(
        self,
        name: str = DEFAULT_NAME,
        system_prompt: str | None = None,
        model: str = DEFAULT_MODEL,
        client=None,
        strategy: str = DEFAULT_STRATEGY,
        window_size: int = WINDOW_DEFAULT,
    ):
        self.name = (name or DEFAULT_NAME).strip() or DEFAULT_NAME
        self.model = model if model in MODELS else DEFAULT_MODEL
        self._client = client
        self.strategy = strategy if strategy in STRATEGY_MODES else DEFAULT_STRATEGY
        self.window_size = _clamp_window(window_size)
        self.history: list[dict] = []
        self.facts_state: dict = {"facts": [], "covered": 0}
        self.parent_id: str | None = None
        self.fork_len: int | None = None
        self.totals: dict = {mode: dict(EMPTY_BUCKET) for mode in STRATEGY_MODES}
        self.totals["facts_calls"] = dict(EMPTY_BUCKET)
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

        messages, extra_text, tail, outside = self._request(content)
        est = breakdown(self.system_prompt, extra_text, tail, content)
        limit = MODELS[self.model]["context_limit"]

        started = time.perf_counter()
        try:
            stream = complete(
                messages,
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
            outside,
            finish_reason,
            usage,
            round((time.perf_counter() - started) * 1000),
            answer_est=estimate_text(reply),
        )
        self.history[-1]["meta"] = meta
        self.token_log.append({
            "turn": len(self.history) // 2,
            "strategy": self.strategy,
            "system_est": est["system"],
            "extra_est": est["extra"],
            "history_est": est["history"],
            "request_est": est["request"],
            "outside": outside,
            "prompt_tokens": meta["prompt_tokens"],
            "completion_tokens": meta["completion_tokens"],
            "cost_usd": meta["cost_usd"],
        })

        yield {"event": "done", "content": reply, "meta": meta}

        yield from self._update_facts()

    def reset(self) -> None:
        self.history.clear()
        self.facts_state = {"facts": [], "covered": 0}
        self.parent_id = None
        self.fork_len = None
        self.totals = {mode: dict(EMPTY_BUCKET) for mode in STRATEGY_MODES}
        self.totals["facts_calls"] = dict(EMPTY_BUCKET)
        self.token_log.clear()

    def configure(
        self,
        name: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        strategy: str | None = None,
        window_size: int | None = None,
    ) -> None:
        if model is not None:
            if model not in MODELS:
                raise ValueError(f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}.")
            self.model = model
        if strategy is not None:
            if strategy not in STRATEGY_MODES:
                raise ValueError(
                    f"Неизвестная стратегия: {strategy}. "
                    f"Доступны: {', '.join(STRATEGY_MODES)}."
                )
            self.strategy = strategy
        if window_size is not None:
            if isinstance(window_size, bool) or not isinstance(window_size, (int, float)):
                raise ValueError("Размер окна должен быть целым числом.")
            if not WINDOW_MIN <= int(window_size) <= WINDOW_MAX:
                raise ValueError(
                    f"Размер окна должен быть от {WINDOW_MIN} до {WINDOW_MAX}."
                )
            self.window_size = int(window_size)
        if name is not None and name.strip():
            self.name = name.strip()
        if system_prompt is not None and system_prompt.strip():
            self.system_prompt = system_prompt.strip()
            self._default_prompt = False
        if self._default_prompt:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=self.name)

    def fork(self, count: int) -> "Agent":
        snap = self.snapshot()
        snap["history"] = snap["history"][:count]
        child = Agent.from_snapshot(snap, client=self._client)
        child.totals = {mode: dict(EMPTY_BUCKET) for mode in STRATEGY_MODES}
        child.totals["facts_calls"] = dict(EMPTY_BUCKET)
        child.token_log = []
        return child

    def describe(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "strategy": self.strategy,
            "strategy_label": MODE_LABELS[self.strategy],
            "window_size": self.window_size,
            "turns": len(self.history) // 2,
            "messages": [dict(m) for m in self.history],
            "facts": self._facts_out(),
            "context_preview": self.context_preview(),
            "totals": self._totals_out(),
            "token_log": [dict(row) for row in self.token_log],
            "context_limit": MODELS[self.model]["context_limit"],
            "parent_id": self.parent_id,
            "fork_len": self.fork_len,
        }

    def context_preview(self) -> dict:
        _messages, extra_text, tail, outside = self._request("")
        est = breakdown(self.system_prompt, extra_text, tail, "")
        return {
            "strategy": self.strategy,
            "strategy_label": MODE_LABELS[self.strategy],
            "system": est["system"],
            "extra": est["extra"],
            "history": est["history"],
            "request": 0,
            "total": est["total"] - est["request"],
            "outside": outside,
            "verbatim": len(tail),
            "context_limit": MODELS[self.model]["context_limit"],
            "window_size": self.window_size,
        }

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "default_prompt": self._default_prompt,
            "strategy": self.strategy,
            "window_size": self.window_size,
            "history": [dict(m) for m in self.history],
            "facts_state": {
                "facts": [list(pair) for pair in self.facts_state["facts"]],
                "covered": self.facts_state["covered"],
            },
            "parent_id": self.parent_id,
            "fork_len": self.fork_len,
            "totals": self._totals_out(),
            "token_log": [dict(row) for row in self.token_log],
        }

    @classmethod
    def from_snapshot(cls, data: dict, client=None) -> "Agent":
        agent = cls(
            name=data.get("name") or DEFAULT_NAME,
            system_prompt=data.get("system_prompt"),
            model=data.get("model", DEFAULT_MODEL),
            client=client,
            strategy=data.get("strategy", DEFAULT_STRATEGY),
            window_size=data.get("window_size", WINDOW_DEFAULT),
        )
        if data.get("default_prompt"):
            agent._default_prompt = True
            agent.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=agent.name)
        history = [
            {**({"meta": m["meta"]} if "meta" in m else {}), "role": m["role"], "content": m["content"]}
            for m in data.get("history", [])
            if isinstance(m, dict)
            and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
        ]
        agent.history = history[-(MAX_TURNS * 2):]
        agent.facts_state = cls._facts_state_from(data, len(agent.history))
        parent_id = data.get("parent_id")
        agent.parent_id = parent_id if isinstance(parent_id, str) and parent_id else None
        fork_len = data.get("fork_len")
        if isinstance(fork_len, bool) or not isinstance(fork_len, int) or fork_len < 0:
            fork_len = None
        agent.fork_len = fork_len
        raw_totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
        agent.totals = {mode: _bucket(raw_totals.get(mode)) for mode in agent.totals}
        log = data.get("token_log")
        agent.token_log = [dict(row) for row in log if isinstance(row, dict)] if isinstance(log, list) else []
        return agent

    @staticmethod
    def _facts_state_from(data: dict, history_len: int) -> dict:
        raw = data.get("facts_state") if isinstance(data.get("facts_state"), dict) else {}
        raw_pairs = raw.get("facts")
        pairs = cap_pairs(raw_pairs) if isinstance(raw_pairs, list) else []
        covered = raw.get("covered")
        if isinstance(covered, bool) or not isinstance(covered, int) or covered < 0:
            covered = 0
        return {"facts": pairs, "covered": min(covered, history_len)}

    def _request(self, content: str) -> tuple[list[dict], str, list[dict], int]:
        messages = [{"role": "system", "content": self.system_prompt}]
        extra_text = ""
        outside = 0
        if self.strategy == "facts":
            facts = self.facts_state["facts"]
            if facts:
                messages.append(render_facts_message(facts))
                extra_text = facts_text(facts)
            outside = self.facts_state["covered"]
            tail = self.history[-self.window_size:]
        elif self.strategy == "window":
            tail = self.history[-self.window_size:]
            outside = len(self.history) - len(tail)
        else:
            tail = self.history
        messages += [{"role": m["role"], "content": m["content"]} for m in tail]
        messages.append({"role": "user", "content": content})
        return messages, extra_text, tail, outside

    def _update_facts(self) -> Iterator[dict]:
        if self.strategy != "facts":
            return
        state = self.facts_state
        while len(self.history) - state["covered"] > 0:
            chunk = self.history[state["covered"]:state["covered"] + FACTS_CHUNK]
            try:
                pairs, usage, raw = update_facts(
                    state["facts"], chunk, self.model, client=self._client
                )
            except Exception as exc:
                yield {
                    "event": "notice",
                    "message": (
                        f"Не удалось обновить факты: {str(exc)[:200]}. "
                        "Попробую снова после следующего ответа."
                    ),
                }
                return
            if not pairs and raw:
                yield {
                    "event": "notice",
                    "message": (
                        "Модель вернула факты в неожиданном формате — "
                        "попробую снова после следующего ответа."
                    ),
                }
                return
            state["facts"] = pairs
            state["covered"] += len(chunk)
            self._account_facts(usage)
            yield {
                "event": "facts",
                "strategy": "facts",
                "covered": state["covered"],
                "count": len(pairs),
                "chars": len(facts_text(pairs)),
                "facts": self._facts_out(),
                "context_preview": self.context_preview(),
                "totals": self._totals_out(),
            }

    def _account_facts(self, usage) -> None:
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
        bucket = self.totals["facts_calls"]
        bucket["requests"] += 1
        bucket["prompt_tokens"] += prompt_tokens or 0
        bucket["completion_tokens"] += completion_tokens or 0
        bucket["cost_usd"] = round(bucket["cost_usd"] + (cost_usd or 0.0), 6)

    def _meta(
        self,
        est: dict,
        limit: int,
        outside: int,
        finish_reason: str | None,
        usage,
        latency_ms: int,
        answer_est: int = 0,
    ) -> dict:
        spec = MODELS[self.model]
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        # у thinking-моделей completion включает скрытые рассуждения, которые
        # не возвращаются в следующем запросе — в контексте остаётся только текст
        reasoning_tokens = None
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        if details is not None:
            raw = getattr(details, "reasoning_tokens", None)
            if isinstance(raw, (int, float)) and raw >= 0:
                reasoning_tokens = int(raw)
        answer_tokens = None
        if completion_tokens is not None:
            if reasoning_tokens:
                answer_tokens = max(0, completion_tokens - reasoning_tokens)
            else:
                answer_tokens = min(answer_est, completion_tokens)
        est_error_pct = None
        if prompt_tokens:
            est_error_pct = round((est["total"] - prompt_tokens) / prompt_tokens * 100, 1)
        # размер диалога после хода: промпт + текст ответа — столько займёт следующий запрос
        with_answer = None
        if prompt_tokens is not None:
            with_answer = prompt_tokens + (answer_tokens if answer_tokens is not None else 0)
        used = with_answer if with_answer is not None else est["total"]
        cost_usd = None
        if prompt_tokens is not None and spec.get("price_in") is not None:
            cost_usd = round(
                prompt_tokens / 1e6 * spec["price_in"]
                + (completion_tokens or 0) / 1e6 * spec["price_out"],
                6,
            )
        bucket = self.totals[self.strategy]
        bucket["requests"] += 1
        bucket["prompt_tokens"] += prompt_tokens or 0
        bucket["completion_tokens"] += completion_tokens or 0
        bucket["cost_usd"] = round(bucket["cost_usd"] + (cost_usd or 0.0), 6)
        return {
            "agent": self.name,
            "model": self.model,
            "strategy": self.strategy,
            "strategy_label": MODE_LABELS[self.strategy],
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "turns": len(self.history) // 2,
            "outside": outside,
            "tokens": {
                "system": est["system"],
                "extra": est["extra"],
                "history": est["history"],
                "request": est["request"],
                "total_est": est["total"],
                "total_actual": prompt_tokens,
                "answer_tokens": answer_tokens,
                "total_with_answer": with_answer,
                "est_error_pct": est_error_pct,
                "context_limit": limit,
                "context_used_pct": context_used_pct(used, limit),
            },
            "totals": self._totals_out(),
            "context_preview": self.context_preview(),
        }

    def _facts_out(self) -> dict:
        return {
            "pairs": [list(pair) for pair in self.facts_state["facts"]],
            "covered": self.facts_state["covered"],
        }

    def _totals_out(self) -> dict:
        return {mode: dict(bucket) for mode, bucket in self.totals.items()}

    def _validate(self, user_input: str) -> tuple[str | None, str | None]:
        if not isinstance(user_input, str) or not user_input.strip():
            return None, "Пустой запрос."
        text = user_input.strip()
        if len(text) > MAX_CONTENT:
            return None, f"Сообщение длиннее {MAX_CONTENT} символов."
        return text, None

    def _trim(self) -> None:
        overflow = len(self.history) - MAX_TURNS * 2
        if overflow > 0:
            del self.history[:overflow]
            state = self.facts_state
            state["covered"] = max(0, state["covered"] - overflow)
