import json
import time
from collections.abc import Iterator
from types import SimpleNamespace

from config import DEFAULT_MODEL, MODELS, complete
from tokens import breakdown, context_used_pct, estimate_text

DEFAULT_NAME = "Ассистент"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — {name}, дружелюбный и полезный ИИ-ассистент. "
    "Отвечай на русском языке: кратко, точно и по делу."
)
MAX_TURNS = 250
MAX_CONTENT = 600_000
TEMPERATURE = 0
MAX_TOOL_ROUNDS = 5
TOOL_PREVIEW = 500

LAYER_KEYS = ("short",)
DEFAULT_LAYERS = {"short": True}

EMPTY_BUCKET = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}


def _bucket(value) -> dict:
    out = dict(EMPTY_BUCKET)
    if isinstance(value, dict):
        for key in out:
            v = value.get(key)
            if isinstance(v, (int, float)):
                out[key] = v
    return out


def normalize_layers(value) -> dict:
    out = dict(DEFAULT_LAYERS)
    if isinstance(value, dict):
        for key in LAYER_KEYS:
            v = value.get(key)
            if isinstance(v, bool):
                out[key] = v
    return out


class _UsageSum:
    """Сумма usage по всем хопам хода; вид издаётся как openai-usage."""

    def __init__(self):
        self.requests = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0

    def add(self, usage) -> None:
        if usage is None:
            return
        self.requests += 1
        self.prompt_tokens += getattr(usage, "prompt_tokens", None) or 0
        self.completion_tokens += getattr(usage, "completion_tokens", None) or 0
        details = getattr(usage, "completion_tokens_details", None)
        raw = getattr(details, "reasoning_tokens", None) if details else None
        if isinstance(raw, (int, float)) and raw > 0:
            self.reasoning_tokens += int(raw)

    def view(self):
        if not self.requests:
            return None
        details = None
        if self.reasoning_tokens:
            details = SimpleNamespace(reasoning_tokens=self.reasoning_tokens)
        return SimpleNamespace(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            completion_tokens_details=details,
            requests=self.requests,
        )


class Agent:
    def __init__(
        self,
        name: str = DEFAULT_NAME,
        system_prompt: str | None = None,
        model: str = DEFAULT_MODEL,
        client=None,
        layers: dict | None = None,
        store=None,
        tools: list | None = None,
        tool_call=None,
        tools_enabled: bool = True,
    ):
        self.name = (name or DEFAULT_NAME).strip() or DEFAULT_NAME
        self.model = model if model in MODELS else DEFAULT_MODEL
        self._client = client
        self.layers = normalize_layers(layers)
        self.session_id: str | None = None
        self._store = store
        self._tools = list(tools) if tools else None
        self._tool_call = tool_call
        self.tools_enabled = tools_enabled is not False
        self.history: list[dict] = []
        self.totals: dict = {"chat": dict(EMPTY_BUCKET)}
        self.token_log: list[dict] = []
        if system_prompt and system_prompt.strip():
            self.system_prompt = system_prompt.strip()
            self._default_prompt = False
        else:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=self.name)
            self._default_prompt = True

    def bind(self, session_id: str, store) -> None:
        self.session_id = session_id
        self._store = store

    def send(self, user_input: str) -> str:
        reply = ""
        for event in self.send_stream(user_input):
            if event["event"] == "done":
                reply = event["content"]
            elif event["event"] == "error":
                raise RuntimeError(event["message"])
        return reply

    def send_stream(self, user_input: str) -> Iterator[dict]:
        content, err = self._validate(user_input)
        if err:
            yield {"event": "error", "message": err}
            return
        yield from self._run_single(content)

    def _run_single(self, content: str) -> Iterator[dict]:
        messages, tail = self._request(content)
        est = breakdown(self.system_prompt, tail, content)
        limit = MODELS[self.model]["context_limit"]
        started = time.perf_counter()

        trace: list[dict] = []
        usage = _UsageSum()
        rounds = 0
        reply = ""
        finish_reason = None

        while True:
            tools = None
            if self.tools_enabled and self._tools and rounds < MAX_TOOL_ROUNDS:
                tools = self._tools
            result = yield from self._call_stream(messages, tools)
            if result.get("error"):
                yield {"event": "error", "message": result["error"]}
                return
            usage.add(result["usage"])
            finish_reason = result["finish_reason"]
            reply = result["reply"]
            calls = result["tool_calls"]
            if not calls:
                break
            rounds += 1
            messages.append({
                "role": "assistant",
                "content": reply or None,
                "tool_calls": [
                    {
                        "id": c["id"] or f"call_{rounds}_{i}",
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for i, c in enumerate(calls)
                ],
            })
            for i, c in enumerate(calls):
                call_id = c["id"] or f"call_{rounds}_{i}"
                try:
                    args = json.loads(c["arguments"]) if c["arguments"].strip() else {}
                    if not isinstance(args, dict):
                        raise ValueError
                except (json.JSONDecodeError, ValueError):
                    args = None
                yield {
                    "event": "tool_call",
                    "name": c["name"],
                    "arguments": args if args is not None else c["arguments"],
                }
                if args is None:
                    text = f"Ошибка: аргументы — невалидный JSON: {c['arguments'][:200]}"
                    is_error, ms = True, 0
                else:
                    text, is_error, ms = self._exec_tool(c["name"], args)
                preview = text if len(text) <= TOOL_PREVIEW else text[:TOOL_PREVIEW] + "…"
                yield {
                    "event": "tool_result",
                    "name": c["name"],
                    "ok": not is_error,
                    "preview": preview,
                }
                messages.append({"role": "tool", "tool_call_id": call_id, "content": text})
                server, _, tool = c["name"].partition("__")
                trace.append({
                    "name": c["name"],
                    "server": server,
                    "tool": tool or c["name"],
                    "arguments": args,
                    "ok": not is_error,
                    "preview": preview,
                    "latency_ms": ms,
                })

        self._commit_turn(content, reply)
        meta = self._meta(
            est,
            limit,
            finish_reason,
            usage.view(),
            round((time.perf_counter() - started) * 1000),
            answer_est=estimate_text(reply),
        )
        if trace:
            meta["tool_calls"] = trace
            meta["tool_rounds"] = rounds
        self.history[-1]["meta"] = meta
        self._log_turn(est, meta)
        yield {"event": "done", "content": reply, "meta": meta}

    def _exec_tool(self, name: str, args: dict) -> tuple[str, bool, int]:
        """(текст для tool-сообщения, is_error, latency_ms). Любой сбой —
        данные для модели, ход не падает."""
        started = time.perf_counter()
        try:
            if self._tool_call is None:
                raise RuntimeError("tool runtime не настроен")
            text, is_error = self._tool_call(name, args)
        except Exception as exc:
            is_error, text = True, f"Ошибка: {str(exc)[:300]}"
        ms = round((time.perf_counter() - started) * 1000)
        return text, is_error, ms

    def _call_stream(self, messages: list[dict], tools: list | None = None) -> Iterator[dict]:
        """Один стриминг-вызов модели. Yield-ит delta-события; результат —
        возвращаемое значение генератора ({reply, finish_reason, usage,
        tool_calls} или {error})."""
        params = {"tools": tools} if tools else {}
        try:
            stream = complete(
                messages,
                model=self.model,
                stream=True,
                client=self._client,
                temperature=TEMPERATURE,
                **params,
            )
        except RuntimeError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Модель не приняла запрос: {str(exc)[:400]}"}
        parts: list[str] = []
        tool_calls: dict[int, dict] = {}
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
                delta = choice.delta
                if delta is None:
                    continue
                if delta.content:
                    parts.append(delta.content)
                    yield {"event": "delta", "text": delta.content}
                for tc in getattr(delta, "tool_calls", None) or []:
                    idx = getattr(tc, "index", None) or 0
                    slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if getattr(tc, "id", None):
                        slot["id"] += tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        slot["name"] += getattr(fn, "name", None) or ""
                        slot["arguments"] += getattr(fn, "arguments", None) or ""
        except Exception as exc:
            return {"error": f"Генерация прервалась: {str(exc)[:400]}"}
        finally:
            try:
                stream.close()
            except Exception:
                pass
        return {
            "reply": "".join(parts),
            "finish_reason": finish_reason,
            "usage": usage,
            "tool_calls": [tool_calls[i] for i in sorted(tool_calls)],
        }

    def _commit_turn(self, content: str, reply: str) -> None:
        self.history.append({"role": "user", "content": content})
        self.history.append({"role": "assistant", "content": reply})
        self._trim()

    def _log_turn(self, est: dict, meta: dict) -> None:
        self.token_log.append({
            "turn": len(self.history) // 2,
            "system_est": est["system"],
            "history_est": est["history"],
            "request_est": est["request"],
            "prompt_tokens": meta["prompt_tokens"],
            "completion_tokens": meta["completion_tokens"],
            "cost_usd": meta["cost_usd"],
        })

    def reset(self) -> None:
        self.history.clear()
        self.totals = {"chat": dict(EMPTY_BUCKET)}
        self.token_log.clear()

    def configure(
        self,
        name: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        layers: dict | None = None,
        tools_enabled: bool | None = None,
    ) -> None:
        if tools_enabled is not None:
            if not isinstance(tools_enabled, bool):
                raise ValueError("tools должен быть true или false.")
            self.tools_enabled = tools_enabled
        if model is not None:
            if model not in MODELS:
                raise ValueError(f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}.")
            self.model = model
        if layers is not None:
            if not isinstance(layers, dict):
                raise ValueError("layers должен быть объектом {short}.")
            for key, value in layers.items():
                if key in LAYER_KEYS:
                    if not isinstance(value, bool):
                        raise ValueError(f"layers.{key} должен быть true или false.")
                    self.layers[key] = value
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
            "layers": dict(self.layers),
            "tools_enabled": self.tools_enabled,
            "tools_available": len(self._tools or []),
            "turns": len(self.history) // 2,
            "messages": [dict(m) for m in self.history],
            "context_preview": self.context_preview(),
            "totals": self._totals_out(),
            "token_log": [dict(r) for r in self.token_log],
            "context_limit": MODELS[self.model]["context_limit"],
        }

    def context_preview(self) -> dict:
        _messages, tail = self._request("")
        est = breakdown(self.system_prompt, tail, "")
        return {
            "system": est["system"],
            "history": est["history"],
            "request": 0,
            "total": est["total"] - est["request"],
            "history_len": len(tail),
            "layers": dict(self.layers),
            "context_limit": MODELS[self.model]["context_limit"],
        }

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "default_prompt": self._default_prompt,
            "layers": dict(self.layers),
            "tools_enabled": self.tools_enabled,
            "history": [dict(m) for m in self.history],
            "totals": self._totals_out(),
            "token_log": [dict(r) for r in self.token_log],
        }

    @classmethod
    def from_snapshot(cls, data: dict, client=None, store=None, tools=None, tool_call=None) -> "Agent":
        agent = cls(
            name=data.get("name") or DEFAULT_NAME,
            system_prompt=data.get("system_prompt"),
            model=data.get("model", DEFAULT_MODEL),
            client=client,
            layers=data.get("layers"),
            store=store,
            tools=tools,
            tool_call=tool_call,
            tools_enabled=data.get("tools_enabled") is not False,
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
        raw_totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
        agent.totals = {key: _bucket(raw_totals.get(key)) for key in agent.totals}
        log = data.get("token_log")
        agent.token_log = [dict(row) for row in log if isinstance(row, dict)] if isinstance(log, list) else []
        return agent

    def _request(
        self,
        content: str,
        with_tail: bool = True,
    ) -> tuple[list[dict], list[dict]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        tail = list(self.history) if (with_tail and self.layers["short"]) else []
        messages += [{"role": m["role"], "content": m["content"]} for m in tail]
        messages.append({"role": "user", "content": content})
        return messages, tail

    def _meta(
        self,
        est: dict,
        limit: int,
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
        bucket = self.totals["chat"]
        bucket["requests"] += getattr(usage, "requests", None) or 1
        bucket["prompt_tokens"] += prompt_tokens or 0
        bucket["completion_tokens"] += completion_tokens or 0
        bucket["cost_usd"] = round(bucket["cost_usd"] + (cost_usd or 0.0), 6)
        return {
            "agent": self.name,
            "model": self.model,
            "layers": dict(self.layers),
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

    def _totals_out(self) -> dict:
        return {key: dict(bucket) for key, bucket in self.totals.items()}

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
