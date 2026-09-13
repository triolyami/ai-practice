import time
from collections.abc import Iterator

from compressor import compress, render_chunks_message, render_rolling_message
from config import DEFAULT_MODEL, MODELS, complete
from tokens import breakdown, context_used_pct, estimate_text

DEFAULT_NAME = "Ассистент"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — {name}, дружелюбный и полезный ИИ-ассистент. "
    "Отвечай на русском языке: кратко, точно и по делу."
)
COMPRESSION_MODES = ("off", "rolling", "chunks")
MODE_LABELS = {
    "off": "без сжатия",
    "rolling": "скользящее summary",
    "chunks": "summary по чанкам",
}
DEFAULT_COMPRESSION = "rolling"
RECENT_KEEP = 10
SUMMARY_EVERY = 10
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


class Agent:
    def __init__(
        self,
        name: str = DEFAULT_NAME,
        system_prompt: str | None = None,
        model: str = DEFAULT_MODEL,
        client=None,
        compression: str = DEFAULT_COMPRESSION,
    ):
        self.name = (name or DEFAULT_NAME).strip() or DEFAULT_NAME
        self.model = model if model in MODELS else DEFAULT_MODEL
        self._client = client
        self.compression = compression if compression in COMPRESSION_MODES else DEFAULT_COMPRESSION
        self.history: list[dict] = []
        self.comp_state: dict = {
            "rolling": {"summary": None, "covered": 0},
            "chunks": {"chunks": [], "covered": 0},
        }
        self.totals: dict = {mode: dict(EMPTY_BUCKET) for mode in COMPRESSION_MODES}
        self.totals["summary_calls"] = dict(EMPTY_BUCKET)
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

        messages, summary_text, tail, summarized = self._request(content)
        est = breakdown(self.system_prompt, summary_text, tail, content)
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
            summarized,
            finish_reason,
            usage,
            round((time.perf_counter() - started) * 1000),
            answer_est=estimate_text(reply),
        )
        self.history[-1]["meta"] = meta
        self.token_log.append({
            "turn": len(self.history) // 2,
            "mode": self.compression,
            "system_est": est["system"],
            "summary_est": est["summary"],
            "history_est": est["history"],
            "request_est": est["request"],
            "summarized": summarized,
            "prompt_tokens": meta["prompt_tokens"],
            "completion_tokens": meta["completion_tokens"],
            "cost_usd": meta["cost_usd"],
        })

        yield {"event": "done", "content": reply, "meta": meta}

        yield from self._compress_history()

    def reset(self) -> None:
        self.history.clear()
        self.comp_state = {
            "rolling": {"summary": None, "covered": 0},
            "chunks": {"chunks": [], "covered": 0},
        }
        self.totals = {mode: dict(EMPTY_BUCKET) for mode in COMPRESSION_MODES}
        self.totals["summary_calls"] = dict(EMPTY_BUCKET)
        self.token_log.clear()

    def configure(
        self,
        name: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        compression: str | None = None,
    ) -> None:
        if model is not None:
            if model not in MODELS:
                raise ValueError(f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}.")
            self.model = model
        if compression is not None:
            if compression not in COMPRESSION_MODES:
                raise ValueError(
                    f"Неизвестный режим сжатия: {compression}. "
                    f"Доступны: {', '.join(COMPRESSION_MODES)}."
                )
            self.compression = compression
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
            "compression": self.compression,
            "mode_label": MODE_LABELS[self.compression],
            "turns": len(self.history) // 2,
            "messages": [dict(m) for m in self.history],
            "summaries": self._summaries_out(),
            "context_preview": self.context_preview(),
            "totals": self._totals_out(),
            "token_log": [dict(row) for row in self.token_log],
            "context_limit": MODELS[self.model]["context_limit"],
            "recent_keep": RECENT_KEEP,
            "summary_every": SUMMARY_EVERY,
        }

    def context_preview(self) -> dict:
        _messages, summary_text, tail, covered = self._request("")
        est = breakdown(self.system_prompt, summary_text, tail, "")
        return {
            "mode": self.compression,
            "mode_label": MODE_LABELS[self.compression],
            "system": est["system"],
            "summary": est["summary"],
            "history": est["history"],
            "request": 0,
            "total": est["total"] - est["request"],
            "summarized": covered if self.compression != "off" else 0,
            "verbatim": len(tail),
            "context_limit": MODELS[self.model]["context_limit"],
            "recent_keep": RECENT_KEEP,
            "summary_every": SUMMARY_EVERY,
        }

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "default_prompt": self._default_prompt,
            "compression": self.compression,
            "history": [dict(m) for m in self.history],
            "comp_state": {
                "rolling": dict(self.comp_state["rolling"]),
                "chunks": {
                    "chunks": list(self.comp_state["chunks"]["chunks"]),
                    "covered": self.comp_state["chunks"]["covered"],
                },
            },
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
            compression=data.get("compression", DEFAULT_COMPRESSION),
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
        agent.comp_state = cls._comp_state_from(data, len(agent.history))
        raw_totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
        agent.totals = {mode: _bucket(raw_totals.get(mode)) for mode in agent.totals}
        log = data.get("token_log")
        agent.token_log = [dict(row) for row in log if isinstance(row, dict)] if isinstance(log, list) else []
        return agent

    @staticmethod
    def _comp_state_from(data: dict, history_len: int) -> dict:
        raw = data.get("comp_state") if isinstance(data.get("comp_state"), dict) else {}
        rolling = raw.get("rolling") if isinstance(raw.get("rolling"), dict) else {}
        chunks_state = raw.get("chunks") if isinstance(raw.get("chunks"), dict) else {}
        limit = max(0, history_len - RECENT_KEEP)
        summary = rolling.get("summary")
        raw_chunks = chunks_state.get("chunks")
        return {
            "rolling": {
                "summary": summary if isinstance(summary, str) and summary.strip() else None,
                "covered": Agent._clamp_covered(rolling.get("covered"), limit),
            },
            "chunks": {
                "chunks": (
                    [c for c in raw_chunks if isinstance(c, str) and c.strip()]
                    if isinstance(raw_chunks, list)
                    else []
                ),
                "covered": Agent._clamp_covered(chunks_state.get("covered"), limit),
            },
        }

    @staticmethod
    def _clamp_covered(value, limit: int) -> int:
        covered = value if isinstance(value, int) and value > 0 else 0
        return min(covered, limit)

    def _request(self, content: str) -> tuple[list[dict], str, list[dict], int]:
        messages = [{"role": "system", "content": self.system_prompt}]
        summary_text = ""
        covered = 0
        if self.compression != "off":
            state = self.comp_state[self.compression]
            covered = state["covered"]
            if self.compression == "rolling" and state["summary"]:
                messages.append(render_rolling_message(state["summary"]))
                summary_text = state["summary"]
            elif self.compression == "chunks" and state["chunks"]:
                messages.append(render_chunks_message(state["chunks"]))
                summary_text = "\n".join(state["chunks"])
        tail = self.history[covered:]
        messages += [{"role": m["role"], "content": m["content"]} for m in tail]
        messages.append({"role": "user", "content": content})
        return messages, summary_text, tail, covered

    def _compress_history(self) -> Iterator[dict]:
        if self.compression == "off":
            return
        state = self.comp_state[self.compression]
        while len(self.history) - state["covered"] - RECENT_KEEP >= SUMMARY_EVERY:
            start = state["covered"]
            chunk = self.history[start : start + SUMMARY_EVERY]
            old = state["summary"] if self.compression == "rolling" else None
            try:
                text, usage = compress(old, chunk, self.model, client=self._client)
            except Exception as exc:
                yield {
                    "event": "notice",
                    "message": (
                        f"Не удалось сжать историю: {str(exc)[:200]}. "
                        "Попробую снова после следующего ответа."
                    ),
                }
                return
            if not text:
                yield {
                    "event": "notice",
                    "message": "Модель вернула пустую сводку — сжатие отложено до следующего ответа.",
                }
                return
            if self.compression == "rolling":
                state["summary"] = text
            else:
                state["chunks"].append(text)
            state["covered"] = start + len(chunk)
            self._account_summary(usage)
            yield {
                "event": "summary",
                "mode": self.compression,
                "compressed_messages": len(chunk),
                "covered": state["covered"],
                "chunks": len(state.get("chunks") or []),
                "summary_chars": len(text),
                "summaries": self._summaries_out(),
                "context_preview": self.context_preview(),
                "totals": self._totals_out(),
            }

    def _account_summary(self, usage) -> None:
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
        bucket = self.totals["summary_calls"]
        bucket["requests"] += 1
        bucket["prompt_tokens"] += prompt_tokens or 0
        bucket["completion_tokens"] += completion_tokens or 0
        bucket["cost_usd"] = round(bucket["cost_usd"] + (cost_usd or 0.0), 6)

    def _meta(
        self,
        est: dict,
        limit: int,
        summarized: int,
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
        bucket = self.totals[self.compression]
        bucket["requests"] += 1
        bucket["prompt_tokens"] += prompt_tokens or 0
        bucket["completion_tokens"] += completion_tokens or 0
        bucket["cost_usd"] = round(bucket["cost_usd"] + (cost_usd or 0.0), 6)
        return {
            "agent": self.name,
            "model": self.model,
            "mode": self.compression,
            "mode_label": MODE_LABELS[self.compression],
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "turns": len(self.history) // 2,
            "summarized": summarized,
            "tokens": {
                "system": est["system"],
                "summary": est["summary"],
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

    def _summaries_out(self) -> dict:
        return {
            "rolling": {
                "text": self.comp_state["rolling"]["summary"],
                "covered": self.comp_state["rolling"]["covered"],
            },
            "chunks": {
                "texts": list(self.comp_state["chunks"]["chunks"]),
                "covered": self.comp_state["chunks"]["covered"],
            },
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
            for state in self.comp_state.values():
                state["covered"] = max(0, state["covered"] - overflow)
