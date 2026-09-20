import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

from config import DEFAULT_MODEL, MODELS, complete
from memory import (
    LONGTERM_PATH,
    MEMORY_CHUNK,
    MEMORY_LOCK,
    read_longterm,
    render_longterm_message,
    update_memory,
    write_longterm,
)
from profiles import SLUG_RE, read_profile, render_profile_message
from tokens import breakdown, context_used_pct, estimate_text

DEFAULT_NAME = "Ассистент"
DEFAULT_SYSTEM_PROMPT = (
    "Ты — {name}, дружелюбный и полезный ИИ-ассистент. "
    "Отвечай на русском языке: кратко, точно и по делу."
)
MAX_TURNS = 250
MAX_CONTENT = 600_000
TEMPERATURE = 0

LAYER_KEYS = ("short", "profile", "longterm")
DEFAULT_LAYERS = {"short": True, "profile": True, "longterm": True}
PROFILE_MAX_SLUG = 80

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


class Agent:
    def __init__(
        self,
        name: str = DEFAULT_NAME,
        system_prompt: str | None = None,
        model: str = DEFAULT_MODEL,
        client=None,
        layers: dict | None = None,
        store=None,
        longterm_path=None,
    ):
        self.name = (name or DEFAULT_NAME).strip() or DEFAULT_NAME
        self.model = model if model in MODELS else DEFAULT_MODEL
        self._client = client
        self.layers = normalize_layers(layers)
        self.session_id: str | None = None
        self.profile_id: str = ""
        self.covered: int = 0
        self._store = store
        self._longterm_path = Path(longterm_path) if longterm_path else LONGTERM_PATH
        self.history: list[dict] = []
        self.totals: dict = {"chat": dict(EMPTY_BUCKET), "memory_calls": dict(EMPTY_BUCKET)}
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
        profile = self._active_profile()
        missing = bool(self.profile_id) and profile is None
        steps = profile["pipeline"] if (profile and self.layers["profile"]) else []
        if steps:
            yield from self._run_pipeline(content, profile, steps, missing)
        else:
            yield from self._run_single(content, profile, missing)

    def _run_single(self, content: str, profile, profile_missing: bool) -> Iterator[dict]:
        messages, lt_text, prof_text, tail = self._request(content, profile=profile)
        est = breakdown(self.system_prompt, lt_text, prof_text, tail, content)
        limit = MODELS[self.model]["context_limit"]
        started = time.perf_counter()
        result = yield from self._call_stream(messages)
        if result.get("error"):
            yield {"event": "error", "message": result["error"]}
            return
        reply = result["reply"]
        self._commit_turn(content, reply)
        meta = self._meta(
            est,
            limit,
            result["finish_reason"],
            result["usage"],
            round((time.perf_counter() - started) * 1000),
            answer_est=estimate_text(reply),
            profile=profile,
            profile_missing=profile_missing,
        )
        self.history[-1]["meta"] = meta
        self._log_turn(est, meta)
        yield {"event": "done", "content": reply, "meta": meta}
        yield from self._update_memory()

    def _run_pipeline(self, content: str, profile: dict, steps: list, profile_missing: bool) -> Iterator[dict]:
        names = [s["name"] for s in steps]
        n = len(steps)
        outputs: list[str] = []
        started = time.perf_counter()
        tot_prompt = 0
        tot_completion = 0
        usage_seen = False
        finish_reason = None
        est = None
        limit = MODELS[self.model]["context_limit"]
        for i, step in enumerate(steps):
            yield {"event": "step_start", "step": i, "name": step["name"], "pipeline": names}
            user_msg = content
            if outputs:
                user_msg += "\n\n" + "\n\n".join(
                    f"Результат шага «{s['name']}»:\n{out}"
                    for s, out in zip(steps, outputs)
                )
            messages, lt_text, prof_text, tail = self._request(
                user_msg,
                profile=profile,
                step_label=f"ШАГ {i + 1}/{n} — {step['name']}: {step['instruction']}",
                with_tail=(i == 0),
            )
            est = breakdown(self.system_prompt, lt_text, prof_text, tail, user_msg)
            result = yield from self._call_stream(messages, step=i)
            if result.get("error"):
                yield {
                    "event": "error",
                    "message": f"Шаг {i + 1} «{step['name']}»: {result['error']}",
                }
                return
            outputs.append(result["reply"])
            usage = result["usage"]
            if usage is not None:
                usage_seen = True
                tot_prompt += getattr(usage, "prompt_tokens", None) or 0
                tot_completion += getattr(usage, "completion_tokens", None) or 0
            yield {
                "event": "step_done",
                "step": i,
                "name": step["name"],
                "content": result["reply"],
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
            }
            finish_reason = result["finish_reason"]
        reply = outputs[-1]
        self._commit_turn(content, reply)
        total_usage = (
            SimpleNamespace(prompt_tokens=tot_prompt, completion_tokens=tot_completion)
            if usage_seen
            else None
        )
        meta = self._meta(
            est,
            limit,
            finish_reason,
            total_usage,
            round((time.perf_counter() - started) * 1000),
            answer_est=estimate_text(reply),
            profile=profile,
            profile_missing=profile_missing,
            pipeline=names,
        )
        self.history[-1]["meta"] = meta
        self._log_turn(est, meta)
        yield {"event": "done", "content": reply, "meta": meta}
        yield from self._update_memory()

    def _call_stream(self, messages: list[dict], step: int | None = None) -> Iterator[dict]:
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
                    event = {"event": "delta", "text": delta}
                    if step is not None:
                        event["step"] = step
                    yield event
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
            "longterm_est": est["longterm"],
            "profile_est": est["profile"],
            "history_est": est["history"],
            "request_est": est["request"],
            "prompt_tokens": meta["prompt_tokens"],
            "completion_tokens": meta["completion_tokens"],
            "cost_usd": meta["cost_usd"],
        })

    def reset(self) -> None:
        self.history.clear()
        self.covered = 0
        self.totals = {"chat": dict(EMPTY_BUCKET), "memory_calls": dict(EMPTY_BUCKET)}
        self.token_log.clear()

    def configure(
        self,
        name: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        profile: str | None = None,
        layers: dict | None = None,
    ) -> None:
        if model is not None:
            if model not in MODELS:
                raise ValueError(f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}.")
            self.model = model
        if layers is not None:
            if not isinstance(layers, dict):
                raise ValueError("layers должен быть объектом {short, profile, longterm}.")
            for key, value in layers.items():
                if key in LAYER_KEYS:
                    if not isinstance(value, bool):
                        raise ValueError(f"layers.{key} должен быть true или false.")
                    self.layers[key] = value
        if profile is not None:
            if not isinstance(profile, str):
                raise ValueError("profile должен быть строкой-слэгом или пустой строкой.")
            slug = profile.strip()[:PROFILE_MAX_SLUG]
            if slug and not SLUG_RE.match(slug):
                raise ValueError("profile — слэг из букв, цифр, - и _ (до 80 символов).")
            self.profile_id = slug
        if name is not None and name.strip():
            self.name = name.strip()
        if system_prompt is not None and system_prompt.strip():
            self.system_prompt = system_prompt.strip()
            self._default_prompt = False
        if self._default_prompt:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=self.name)

    def _active_profile(self) -> dict | None:
        if not self.profile_id:
            return None
        return read_profile(self.profile_id)

    def profile_info(self) -> dict:
        prof = self._active_profile()
        return {
            "id": self.profile_id,
            "name": (prof or {}).get("name") or "",
            "missing": bool(self.profile_id) and prof is None,
            "pipeline": [s["name"] for s in prof["pipeline"]] if prof else [],
        }

    def describe(self) -> dict:
        lt = read_longterm(self._longterm_path)
        info = self.profile_info()
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "layers": dict(self.layers),
            "profile_id": info["id"],
            "profile": info["name"],
            "profile_missing": info["missing"],
            "pipeline": info["pipeline"],
            "turns": len(self.history) // 2,
            "messages": [dict(m) for m in self.history],
            "covered": min(self.covered, len(self.history)),
            "longterm": {
                "chars": len(lt["content"]),
                "items": sum(len(v) for v in lt["sections"].values()),
            },
            "context_preview": self.context_preview(),
            "totals": self._totals_out(),
            "token_log": [dict(r) for r in self.token_log],
            "context_limit": MODELS[self.model]["context_limit"],
        }

    def context_preview(self) -> dict:
        info = self.profile_info()
        profile = self._active_profile() if self.layers["profile"] else None
        _messages, lt_text, prof_text, tail = self._request("", profile=profile)
        est = breakdown(self.system_prompt, lt_text, prof_text, tail, "")
        return {
            "system": est["system"],
            "longterm": est["longterm"],
            "profile": est["profile"],
            "history": est["history"],
            "request": 0,
            "total": est["total"] - est["request"],
            "history_len": len(tail),
            "layers": dict(self.layers),
            "profile_name": info["name"],
            "profile_missing": info["missing"],
            "pipeline": info["pipeline"] if self.layers["profile"] else [],
            "context_limit": MODELS[self.model]["context_limit"],
        }

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "default_prompt": self._default_prompt,
            "profile_id": self.profile_id,
            "covered": self.covered,
            "layers": dict(self.layers),
            "history": [dict(m) for m in self.history],
            "totals": self._totals_out(),
            "token_log": [dict(r) for r in self.token_log],
        }

    @classmethod
    def from_snapshot(cls, data: dict, client=None, store=None, longterm_path=None) -> "Agent":
        agent = cls(
            name=data.get("name") or DEFAULT_NAME,
            system_prompt=data.get("system_prompt"),
            model=data.get("model", DEFAULT_MODEL),
            client=client,
            layers=data.get("layers"),
            store=store,
            longterm_path=longterm_path,
        )
        if data.get("default_prompt"):
            agent._default_prompt = True
            agent.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=agent.name)
        pid = data.get("profile_id")
        if isinstance(pid, str) and pid and SLUG_RE.match(pid):
            agent.profile_id = pid
        covered = data.get("covered")
        if isinstance(covered, int) and not isinstance(covered, bool) and covered >= 0:
            agent.covered = covered
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
        profile: dict | None = None,
        step_label: str | None = None,
        with_tail: bool = True,
    ) -> tuple[list[dict], str, str, list[dict]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        prof_text = ""
        lt_text = ""
        if self.layers["profile"] and profile and profile["prefs_text"]:
            messages.append(render_profile_message(profile))
            prof_text = profile["prefs_text"]
        if self.layers["longterm"]:
            data = read_longterm(self._longterm_path)
            if data["has_content"]:
                messages.append(render_longterm_message(data["content"]))
                lt_text = data["content"]
        if step_label:
            messages.append({"role": "system", "content": step_label})
        tail = list(self.history) if (with_tail and self.layers["short"]) else []
        messages += [{"role": m["role"], "content": m["content"]} for m in tail]
        messages.append({"role": "user", "content": content})
        return messages, lt_text, prof_text, tail

    def _update_memory(self) -> Iterator[dict]:
        store = self._store
        sid = self.session_id
        if store is None or not sid:
            return
        while True:
            covered = min(self.covered, len(self.history))
            if len(self.history) - covered <= 0:
                return
            chunk = self.history[covered:covered + MEMORY_CHUNK]
            lt = read_longterm(self._longterm_path)
            profile = self._active_profile()
            try:
                result, usage, _raw = update_memory(
                    lt["sections"],
                    chunk,
                    self.model,
                    profile_text=(profile or {}).get("prefs_text", ""),
                    profile_sections=(profile or {}).get("sections"),
                    client=self._client,
                )
            except Exception as exc:
                yield {
                    "event": "notice",
                    "message": (
                        f"Не удалось обновить память: {str(exc)[:200]}. "
                        "Попробую снова после следующего ответа."
                    ),
                }
                return
            if result is None:
                yield {
                    "event": "notice",
                    "message": (
                        "Модель вернула память в неожиданном формате — "
                        "попробую снова после следующего ответа."
                    ),
                }
                return
            with MEMORY_LOCK:
                self.covered = covered + len(chunk)
                added = (
                    write_longterm(self._longterm_path, result["longterm"])
                    if result["longterm"]
                    else []
                )
            self._account_memory(usage)
            yield {
                "event": "memory",
                "covered": self.covered,
                "longterm_added": added,
                "context_preview": self.context_preview(),
                "totals": self._totals_out(),
            }

    def _account_memory(self, usage) -> None:
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
        bucket = self.totals["memory_calls"]
        bucket["requests"] += 1
        bucket["prompt_tokens"] += prompt_tokens or 0
        bucket["completion_tokens"] += completion_tokens or 0
        bucket["cost_usd"] = round(bucket["cost_usd"] + (cost_usd or 0.0), 6)

    def _meta(
        self,
        est: dict,
        limit: int,
        finish_reason: str | None,
        usage,
        latency_ms: int,
        answer_est: int = 0,
        profile: dict | None = None,
        profile_missing: bool = False,
        pipeline: list | None = None,
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
            "profile": (profile or {}).get("name") or (self.profile_id or None),
            "profile_id": self.profile_id,
            "profile_missing": profile_missing,
            "pipeline": pipeline or [],
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "turns": len(self.history) // 2,
            "tokens": {
                "system": est["system"],
                "longterm": est["longterm"],
                "profile": est["profile"],
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
