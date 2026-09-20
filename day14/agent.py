import time
from collections.abc import Iterator
from types import SimpleNamespace

from config import DEFAULT_MODEL, MODELS, complete
from invariants import (
    SLUG_RE,
    format_violation_list,
    lint_reply,
    read_invariant,
    render_invariants_message,
    synthesized_refusal,
)
from tokens import breakdown, context_used_pct, estimate_text

DEFAULT_NAME = "Ассистент"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — {name}, дружелюбный и полезный ИИ-ассистент. "
    "Отвечай на русском языке: кратко, точно и по делу."
)
MAX_TURNS = 250
MAX_CONTENT = 600_000
TEMPERATURE = 0

LAYER_KEYS = ("short",)
DEFAULT_LAYERS = {"short": True}
INVARIANT_MAX_SLUG = 80
ENFORCE_MODES = ("off", "prompt", "enforce")
DEFAULT_ENFORCE = "prompt"

EMPTY_BUCKET = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}

RETRY_NOTE = (
    "ЛИНТЕР ИНВАРИАНТОВ: твой предыдущий ответ отклонён — сработали проверки: "
    "{checks}. Ответь заново, не нарушая инварианты; если просьба принципиально "
    "им противоречит — начни ответ с «ОТКАЗ:», назови инвариант и предложи "
    "ближайшую разрешённую альтернативу."
)


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


def _combine_usage(usages: list):
    seen = [u for u in usages if u is not None]
    if not seen:
        return None
    return SimpleNamespace(
        prompt_tokens=sum(getattr(u, "prompt_tokens", None) or 0 for u in seen),
        completion_tokens=sum(getattr(u, "completion_tokens", None) or 0 for u in seen),
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
    ):
        self.name = (name or DEFAULT_NAME).strip() or DEFAULT_NAME
        self.model = model if model in MODELS else DEFAULT_MODEL
        self._client = client
        self.layers = normalize_layers(layers)
        self.session_id: str | None = None
        self.invariant_id: str = ""
        self.enforce: str = DEFAULT_ENFORCE
        self._store = store
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
        inv_obj = self._active_invariant()
        missing = bool(self.invariant_id) and inv_obj is None
        inv = inv_obj if (inv_obj and self.enforce != "off") else None
        yield from self._run_single(content, inv, missing)

    def _run_single(self, content: str, inv, inv_missing: bool) -> Iterator[dict]:
        messages, inv_text, tail = self._request(content, invariant=inv)
        est = breakdown(self.system_prompt, inv_text, tail, content)
        limit = MODELS[self.model]["context_limit"]
        started = time.perf_counter()
        checks = inv["checks"] if inv else []
        blocked: list[dict] = []
        usages = []

        result = yield from self._call_stream(messages)
        if result.get("error"):
            yield {"event": "error", "message": result["error"]}
            return
        usages.append(result["usage"])
        reply = result["reply"]
        finish_reason = result["finish_reason"]
        hits = lint_reply(reply, checks) if checks else []

        if hits and self.enforce == "enforce":
            blocked.append({"content": reply, "violations": hits})
            yield {"event": "violation", "attempt": 1, "content": reply, "violations": hits}
            retry_messages, _inv_text, _tail = self._request(
                content,
                invariant=inv,
                feedback=RETRY_NOTE.format(checks=format_violation_list(hits)),
            )
            result = yield from self._call_stream(retry_messages)
            if result.get("error"):
                yield {"event": "error", "message": result["error"]}
                return
            usages.append(result["usage"])
            reply = result["reply"]
            finish_reason = result["finish_reason"]
            hits = lint_reply(reply, checks)
            if hits:
                blocked.append({"content": reply, "violations": hits})
                yield {"event": "violation", "attempt": 2, "content": reply, "violations": hits}
                reply = synthesized_refusal(inv["name"], hits)

        synthesized = len(blocked) == 2
        refusal = reply.lstrip().startswith("ОТКАЗ")
        committed_hits = [] if blocked else hits
        self._commit_turn(content, reply)
        meta = self._meta(
            est,
            limit,
            finish_reason,
            _combine_usage(usages),
            round((time.perf_counter() - started) * 1000),
            answer_est=estimate_text(reply),
            invariant=inv,
            invariant_missing=inv_missing,
            violations=committed_hits,
            attempts=len(usages),
            blocked_attempts=blocked,
            synthesized=synthesized,
            refusal=refusal,
        )
        self.totals["chat"]["requests"] += len(blocked)  # каждая заблокированная попытка — тоже запрос
        self.history[-1]["meta"] = meta
        self._log_turn(est, meta)
        yield {"event": "done", "content": reply, "meta": meta}

    def _call_stream(self, messages: list[dict]) -> Iterator[dict]:
        """Один стриминг-вызов модели. Yield-ит delta-события; результат —
        возвращаемое значение генератора ({reply, finish_reason, usage} или {error})."""
        try:
            stream = complete(
                messages,
                model=self.model,
                stream=True,
                client=self._client,
                temperature=TEMPERATURE,
            )
        except RuntimeError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Модель не приняла запрос: {str(exc)[:400]}"}
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
        except Exception as exc:
            return {"error": f"Генерация прервалась: {str(exc)[:400]}"}
        finally:
            try:
                stream.close()
            except Exception:
                pass
        return {"reply": "".join(parts), "finish_reason": finish_reason, "usage": usage}

    def _commit_turn(self, content: str, reply: str) -> None:
        self.history.append({"role": "user", "content": content})
        self.history.append({"role": "assistant", "content": reply})
        self._trim()

    def _log_turn(self, est: dict, meta: dict) -> None:
        self.token_log.append({
            "turn": len(self.history) // 2,
            "system_est": est["system"],
            "invariants_est": est["invariants"],
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
        invariant: str | None = None,
        enforce: str | None = None,
        layers: dict | None = None,
    ) -> None:
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
        if invariant is not None:
            if not isinstance(invariant, str):
                raise ValueError("invariant должен быть строкой-слэгом или пустой строкой.")
            slug = invariant.strip()[:INVARIANT_MAX_SLUG]
            if slug and not SLUG_RE.match(slug):
                raise ValueError("invariant — слэг из букв, цифр, - и _ (до 80 символов).")
            self.invariant_id = slug
        if enforce is not None:
            if enforce not in ENFORCE_MODES:
                raise ValueError(f"enforce — одно из: {', '.join(ENFORCE_MODES)}.")
            self.enforce = enforce
        if name is not None and name.strip():
            self.name = name.strip()
        if system_prompt is not None and system_prompt.strip():
            self.system_prompt = system_prompt.strip()
            self._default_prompt = False
        if self._default_prompt:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=self.name)

    def _active_invariant(self) -> dict | None:
        if not self.invariant_id:
            return None
        return read_invariant(self.invariant_id)

    def invariant_info(self) -> dict:
        inv = self._active_invariant()
        return {
            "id": self.invariant_id,
            "name": (inv or {}).get("name") or "",
            "missing": bool(self.invariant_id) and inv is None,
        }

    def describe(self) -> dict:
        info = self.invariant_info()
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "layers": dict(self.layers),
            "invariant_id": info["id"],
            "invariant": info["name"],
            "invariant_missing": info["missing"],
            "enforce": self.enforce,
            "turns": len(self.history) // 2,
            "messages": [dict(m) for m in self.history],
            "context_preview": self.context_preview(),
            "totals": self._totals_out(),
            "token_log": [dict(r) for r in self.token_log],
            "context_limit": MODELS[self.model]["context_limit"],
        }

    def context_preview(self) -> dict:
        info = self.invariant_info()
        inv = self._active_invariant() if self.enforce != "off" else None
        _messages, inv_text, tail = self._request("", invariant=inv)
        est = breakdown(self.system_prompt, inv_text, tail, "")
        return {
            "system": est["system"],
            "invariants": est["invariants"],
            "history": est["history"],
            "request": 0,
            "total": est["total"] - est["request"],
            "history_len": len(tail),
            "layers": dict(self.layers),
            "invariant_name": info["name"] if inv else "",
            "invariant_missing": info["missing"],
            "enforce": self.enforce,
            "context_limit": MODELS[self.model]["context_limit"],
        }

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "default_prompt": self._default_prompt,
            "invariant_id": self.invariant_id,
            "enforce": self.enforce,
            "layers": dict(self.layers),
            "history": [dict(m) for m in self.history],
            "totals": self._totals_out(),
            "token_log": [dict(r) for r in self.token_log],
        }

    @classmethod
    def from_snapshot(cls, data: dict, client=None, store=None) -> "Agent":
        agent = cls(
            name=data.get("name") or DEFAULT_NAME,
            system_prompt=data.get("system_prompt"),
            model=data.get("model", DEFAULT_MODEL),
            client=client,
            layers=data.get("layers"),
            store=store,
        )
        if data.get("default_prompt"):
            agent._default_prompt = True
            agent.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=agent.name)
        iid = data.get("invariant_id")
        if isinstance(iid, str) and iid and SLUG_RE.match(iid):
            agent.invariant_id = iid
        enf = data.get("enforce")
        if enf in ENFORCE_MODES:
            agent.enforce = enf
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
        invariant: dict | None = None,
        feedback: str | None = None,
        with_tail: bool = True,
    ) -> tuple[list[dict], str, list[dict]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        inv_text = ""
        if invariant and invariant["rules_text"]:
            messages.append(render_invariants_message(invariant))
            inv_text = invariant["rules_text"]
        if feedback:
            messages.append({"role": "system", "content": feedback})
        tail = list(self.history) if (with_tail and self.layers["short"]) else []
        messages += [{"role": m["role"], "content": m["content"]} for m in tail]
        messages.append({"role": "user", "content": content})
        return messages, inv_text, tail

    def _meta(
        self,
        est: dict,
        limit: int,
        finish_reason: str | None,
        usage,
        latency_ms: int,
        answer_est: int = 0,
        invariant: dict | None = None,
        invariant_missing: bool = False,
        violations: list | None = None,
        attempts: int = 1,
        blocked_attempts: list | None = None,
        synthesized: bool = False,
        refusal: bool = False,
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
        bucket["requests"] += 1
        bucket["prompt_tokens"] += prompt_tokens or 0
        bucket["completion_tokens"] += completion_tokens or 0
        bucket["cost_usd"] = round(bucket["cost_usd"] + (cost_usd or 0.0), 6)
        return {
            "agent": self.name,
            "model": self.model,
            "layers": dict(self.layers),
            "invariant": (invariant or {}).get("name") or (self.invariant_id or None),
            "invariant_id": self.invariant_id,
            "invariant_missing": invariant_missing,
            "enforce": self.enforce,
            "violations": violations or [],
            "attempts": attempts,
            "blocked_attempts": blocked_attempts or [],
            "synthesized": synthesized,
            "refusal": refusal,
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "turns": len(self.history) // 2,
            "tokens": {
                "system": est["system"],
                "invariants": est["invariants"],
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
