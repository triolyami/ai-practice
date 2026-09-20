import hashlib
import re
import time
from collections.abc import Iterator
from pathlib import Path

from config import DEFAULT_MODEL, MODELS, complete
from memory import (
    LONGTERM_PATH,
    MEMORY_CHUNK,
    MEMORY_LOCK,
    normalize_working,
    read_longterm,
    render_longterm_message,
    render_working_message,
    update_memory,
    working_text,
    write_longterm,
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

LAYER_KEYS = ("short", "working", "longterm")
DEFAULT_LAYERS = {"short": True, "working": True, "longterm": True}
WORKSPACE_MAX_NAME = 120
PROMOTE_SECTION = "Знания"

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


def workspace_slug(name: str) -> str:
    slug = re.sub(r"[^\w]+", "-", name.strip().lower()).strip("-")
    if not slug:
        slug = "x-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return slug[:60]


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
        self.workspace_id: str = ""
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
        if not self.workspace_id:
            self.workspace_id = session_id

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

        messages, lt_text, wk_text, tail = self._request(content)
        est = breakdown(self.system_prompt, lt_text, wk_text, tail, content)
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
            finish_reason,
            usage,
            round((time.perf_counter() - started) * 1000),
            answer_est=estimate_text(reply),
        )
        self.history[-1]["meta"] = meta
        self.token_log.append({
            "turn": len(self.history) // 2,
            "system_est": est["system"],
            "longterm_est": est["longterm"],
            "working_est": est["working"],
            "history_est": est["history"],
            "request_est": est["request"],
            "prompt_tokens": meta["prompt_tokens"],
            "completion_tokens": meta["completion_tokens"],
            "cost_usd": meta["cost_usd"],
        })

        yield {"event": "done", "content": reply, "meta": meta}

        yield from self._update_memory()

    def reset(self) -> None:
        self.history.clear()
        self.totals = {"chat": dict(EMPTY_BUCKET), "memory_calls": dict(EMPTY_BUCKET)}
        self.token_log.clear()
        if self._store is not None and self.session_id and self.workspace_id:
            try:
                self._store.drop_covered(self.workspace_id, self.session_id)
            except Exception:
                pass

    def configure(
        self,
        name: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        workspace: str | None = None,
        layers: dict | None = None,
    ) -> None:
        if model is not None:
            if model not in MODELS:
                raise ValueError(f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}.")
            self.model = model
        if layers is not None:
            if not isinstance(layers, dict):
                raise ValueError("layers должен быть объектом {short, working, longterm}.")
            for key, value in layers.items():
                if key in LAYER_KEYS:
                    if not isinstance(value, bool):
                        raise ValueError(f"layers.{key} должен быть true или false.")
                    self.layers[key] = value
        if workspace is not None:
            self._assign_workspace(workspace)
        if name is not None and name.strip():
            self.name = name.strip()
        if system_prompt is not None and system_prompt.strip():
            self.system_prompt = system_prompt.strip()
            self._default_prompt = False
        if self._default_prompt:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT.format(name=self.name)

    def _assign_workspace(self, name: str) -> None:
        if self._store is None or not self.session_id:
            raise ValueError("Смена рабочей области недоступна: агент не привязан к сессии.")
        name = (name or "").strip()[:WORKSPACE_MAX_NAME]
        wsid = self.session_id if not name else "ws-" + workspace_slug(name)
        if wsid == self.workspace_id:
            return
        self.workspace_id = wsid
        with MEMORY_LOCK:
            self._store.ensure_workspace(wsid, name)
            row = self._store.load_workspace(wsid) or {"name": name, "state": None, "covered": {}}
            covered = dict(row.get("covered") or {})
            covered[self.session_id] = 0
            self._store.save_workspace(wsid, row.get("name") or name, row.get("state"), covered)
            self._store.set_session_workspace(self.session_id, wsid)

    def promote(self, key: str) -> bool:
        if self._store is None or not self.session_id:
            return False
        key = (key or "").strip()
        if not key:
            return False
        with MEMORY_LOCK:
            row = self._store.load_workspace(self.workspace_id) or {}
            state = normalize_working(row.get("state"))
            hit = None
            for pair in state["facts"]:
                if pair[0] == key:
                    hit = pair
                    break
            if hit is None:
                return False
            state["facts"] = [p for p in state["facts"] if p[0] != key]
            covered = dict(row.get("covered") or {})
            self._store.save_workspace(
                self.workspace_id, row.get("name") or "", state, covered
            )
            write_longterm(self._longterm_path, {PROMOTE_SECTION: [hit]})
        return True

    def describe(self) -> dict:
        row = self._workspace_row()
        state = normalize_working(row.get("state"))
        lt = read_longterm(self._longterm_path)
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "layers": dict(self.layers),
            "workspace": row.get("name") or "",
            "workspace_id": self.workspace_id,
            "turns": len(self.history) // 2,
            "messages": [dict(m) for m in self.history],
            "working": {
                **state,
                "workspace": row.get("name") or "",
                "covered": self._covered_for(row),
            },
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
        _messages, lt_text, wk_text, tail = self._request("")
        est = breakdown(self.system_prompt, lt_text, wk_text, tail, "")
        return {
            "system": est["system"],
            "longterm": est["longterm"],
            "working": est["working"],
            "history": est["history"],
            "request": 0,
            "total": est["total"] - est["request"],
            "history_len": len(tail),
            "layers": dict(self.layers),
            "workspace": self._workspace_row().get("name") or "",
            "context_limit": MODELS[self.model]["context_limit"],
        }

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "default_prompt": self._default_prompt,
            "workspace_id": self.workspace_id,
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
        wsid = data.get("workspace_id")
        if isinstance(wsid, str) and wsid:
            agent.workspace_id = wsid
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

    def _workspace_row(self) -> dict:
        if self._store is None or not self.workspace_id:
            return {"name": "", "state": None, "covered": {}}
        row = self._store.load_workspace(self.workspace_id)
        if row is None:
            return {"name": "", "state": None, "covered": {}}
        return row

    def _covered_for(self, row: dict) -> int:
        covered = (row.get("covered") or {}).get(self.session_id or "", 0)
        if not isinstance(covered, int) or covered < 0:
            return 0
        return min(covered, len(self.history))

    def _request(self, content: str) -> tuple[list[dict], str, str, list[dict]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        lt_text = ""
        wk_text = ""
        if self.layers["longterm"]:
            data = read_longterm(self._longterm_path)
            if data["has_content"]:
                messages.append(render_longterm_message(data["content"]))
                lt_text = data["content"]
        if self.layers["working"]:
            state = normalize_working(self._workspace_row().get("state"))
            text = working_text(state)
            if text:
                messages.append(render_working_message(state))
                wk_text = text
        tail = list(self.history) if self.layers["short"] else []
        messages += [{"role": m["role"], "content": m["content"]} for m in tail]
        messages.append({"role": "user", "content": content})
        return messages, lt_text, wk_text, tail

    def _update_memory(self) -> Iterator[dict]:
        store = self._store
        sid = self.session_id
        if store is None or not sid or not self.workspace_id:
            return
        while True:
            row = self._workspace_row()
            covered = self._covered_for(row)
            if len(self.history) - covered <= 0:
                return
            chunk = self.history[covered:covered + MEMORY_CHUNK]
            lt = read_longterm(self._longterm_path)
            try:
                result, usage, _raw = update_memory(
                    normalize_working(row.get("state")),
                    lt["sections"],
                    chunk,
                    self.model,
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
                row = self._workspace_row()
                covered_map = dict(row.get("covered") or {})
                covered_map[sid] = covered + len(chunk)
                state = {
                    "goal": result["goal"],
                    "plan": result["plan"],
                    "facts": result["facts"],
                }
                store.save_workspace(
                    self.workspace_id, row.get("name") or "", state, covered_map
                )
                added = (
                    write_longterm(self._longterm_path, result["longterm"])
                    if result["longterm"]
                    else []
                )
            self._account_memory(usage)
            yield {
                "event": "memory",
                "workspace": row.get("name") or "",
                "workspace_id": self.workspace_id,
                "working": {**state, "workspace": row.get("name") or "", "covered": covered_map[sid]},
                "longterm_added": added,
                "covered": covered_map[sid],
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
            "workspace": self._workspace_row().get("name") or "",
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "turns": len(self.history) // 2,
            "tokens": {
                "system": est["system"],
                "longterm": est["longterm"],
                "working": est["working"],
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
