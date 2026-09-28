import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from agent import LAYER_KEYS, MAX_CONTENT, Agent
from config import MODELS, MCP_SERVERS, thinking_label
from mcp_hub import MCPHub
from storage import ChatStore

DAY19_DIR = Path(__file__).parent
DIST_DIR = DAY19_DIR / "frontend" / "dist"
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".map": "application/json",
    ".woff2": "font/woff2",
}
PORT = 7876
MAX_BODY = 4_000_000
SESSION_CAP = 16

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ClientGone(Exception):
    pass


class AgentRegistry:
    def __init__(self, cap: int = SESSION_CAP):
        self._cap = cap
        self._agents: OrderedDict[str, Agent] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Agent | None:
        with self._lock:
            agent = self._agents.get(session_id)
            if agent is not None:
                self._agents.move_to_end(session_id)
            return agent

    def put(self, session_id: str, agent: Agent) -> None:
        with self._lock:
            self._agents[session_id] = agent
            self._agents.move_to_end(session_id)
            while len(self._agents) > self._cap:
                evicted_id, _ = self._agents.popitem(last=False)
                print(f"   LRU: вытеснен агент сессии {evicted_id}", flush=True)

    def drop(self, session_id: str) -> bool:
        with self._lock:
            return self._agents.pop(session_id, None) is not None

    def items(self) -> list:
        with self._lock:
            return list(self._agents.items())


REGISTRY = AgentRegistry()
BUSY_LOCK = threading.Lock()
BUSY = False

DB_PATH = DAY19_DIR / "data" / "chat_history.db"
STORE = ChatStore(DB_PATH)

# Соединения открываются в main() через HUB.start() — до первого запроса.
HUB = MCPHub(MCP_SERVERS)

# OpenAI-спеки инструментов для модели строятся один раз после HUB.start()
# из кэша инструментов ok-серверов; OPENAI_TOOLS = None до старта хаба.
OPENAI_TOOLS: list | None = None

# Кодо-оркестрованная цепочка дня 19: фиксированные этапы через hub.
PIPELINE_STEPS = ("search", "summarize", "save_to_file")


def _pipeline_filename(query: str) -> str:
    """Имя файла из запроса: первые слова через дефис (санитация — в самом
    инструменте, здесь только короткое человеческое имя)."""
    slug = re.sub(r"[^\w]+", "-", query.strip().lower(), flags=re.UNICODE)
    return slug.strip("-")[:40] or "pipeline-result"


def iter_pipeline(query: str, name: str | None, call_fn):
    """Этапы кодовой дорожки: search → summarize → save_to_file через
    настоящие hub-вызовы; выход этапа — аргумент следующего дословно.
    Генерирует stage-события и финальный done; ошибка этапа рвёт цепочку.
    call_fn(qualified, args) -> (text, is_error) — точка подмены для
    офлайн-проверки."""
    prev_sha = None
    hops_exact = True
    for i, tool in enumerate(PIPELINE_STEPS):
        if tool == "search":
            args = {"query": query, "limit": 3}
        elif tool == "summarize":
            args = {"text": prev_text}
        else:  # save_to_file
            fname = (name or "").strip() or _pipeline_filename(query)
            args = {"name": fname, "text": prev_text}
        text, is_error = call_fn(f"pipeline__{tool}", args)
        out_sha = None if is_error else hashlib.sha256(text.encode("utf-8")).hexdigest()
        # честная проверка хопа: хеш того, что ушло в этот вызов,
        # против хеша того, что вернул предыдущий
        hop_exact = None
        if i > 0:
            in_sha = hashlib.sha256(args["text"].encode("utf-8")).hexdigest()
            hop_exact = in_sha == prev_sha
            hops_exact = hops_exact and hop_exact
        yield {
            "event": "stage",
            "i": i,
            "tool": tool,
            "input": args,
            "output": text,
            "ok": not is_error,
            "hop_exact": hop_exact,
            "sha256": out_sha,
        }
        if is_error:
            yield {
                "event": "done", "ok": False,
                "verdict": "error", "failed_stage": i, "tool": tool,
            }
            return
        prev_text, prev_sha = text, out_sha
    yield {
        "event": "done",
        "ok": True,
        "verdict": "exact" if hops_exact else "differs",
        "result": prev_text,
    }


# Ключи JSON Schema, которые оставляем в parameters — GLM-парсеры
# чувствительны к лишнему багажу ($schema, title и пр.), поэтому allowlist.
SCHEMA_KEYS = {
    "type", "properties", "required", "items", "enum", "description",
    "default", "additionalProperties", "anyOf", "oneOf",
    "minimum", "maximum", "minLength", "maxLength", "pattern", "format",
    "minItems", "maxItems",
}


def sanitize_schema(schema):
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key not in SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: sanitize_schema(s) for name, s in value.items()}
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            out[key] = sanitize_schema(value)
        elif key in ("anyOf", "oneOf") and isinstance(value, list):
            out[key] = [sanitize_schema(v) for v in value]
        elif key == "required" and isinstance(value, list):
            out[key] = [str(v) for v in value]
        else:
            out[key] = value
    return out


def build_openai_tools(servers: list[dict]) -> list[dict]:
    tools = []
    for s in servers:
        if s["status"] != "ok":
            continue
        for t in s["tools"]:
            params = sanitize_schema(t.get("input_schema") or {})
            if not isinstance(params, dict) or not params.get("type"):
                params = {"type": "object", **params} if isinstance(params, dict) else {"type": "object"}
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{s['id']}__{t['name']}",
                    "description": t.get("description") or "",
                    "parameters": params,
                },
            })
    return tools


def _result_text(result: dict) -> str:
    parts = [b.get("text", "") for b in result["content"] if b.get("type") == "text"]
    text = "\n".join(p for p in parts if p)
    if not text and result.get("structured_content") is not None:
        text = json.dumps(result["structured_content"], ensure_ascii=False)
    return text or "(пустой результат)"


def call_mcp_tool(qualified: str, args: dict) -> tuple[str, bool]:
    """tool_call-адаптер для Agent: 'srv__tool' → HUB.call_tool → (текст, is_error).
    Любой сбой — (текст «Ошибка: …», True): ход не падает, модель видит."""
    server, sep, tool = qualified.partition("__")
    if not sep or not server or not tool:
        return f"Ошибка: некорректное имя инструмента «{qualified}».", True
    try:
        result = HUB.call_tool(server, tool, args)
    except KeyError:
        return f"Ошибка: MCP-сервер «{server}» не найден в реестре.", True
    except LookupError:
        return f"Ошибка: на сервере «{server}» нет инструмента «{tool}».", True
    except Exception as exc:
        return f"Ошибка: вызов {qualified} не удался: {str(exc)[:300]}", True
    text = _result_text(result)
    if result["is_error"]:
        text = f"Ошибка: {text}"
    return text, bool(result["is_error"])


def resolve_agent(sid: str) -> Agent | None:
    agent = REGISTRY.get(sid)
    if agent is not None:
        return agent
    snapshot = STORE.load(sid)
    if snapshot is None:
        return None
    agent = Agent.from_snapshot(snapshot, tools=OPENAI_TOOLS, tool_call=call_mcp_tool)
    agent.bind(sid, STORE)
    REGISTRY.put(sid, agent)
    print(
        f"   восстановлен диалог сессии {sid} из базы: «{agent.name}», "
        f"реплик {agent.describe()['turns']}",
        flush=True,
    )
    return agent


def parse_config(raw) -> tuple[dict | None, str | None]:
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return None, "Поле config должно быть JSON-объектом."
    for legacy in ("profile", "invariant", "enforce"):
        if legacy in raw:
            return None, f"config.{legacy} больше не поддерживается — в этом дне агент без профилей и инвариантов."
    out = {}
    for key in ("name", "system_prompt"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return None, f"config.{key} должен быть строкой."
        if len(value) > 2000:
            return None, f"config.{key} длиннее 2000 символов."
        out[key] = value
    model = raw.get("model")
    if model is not None:
        if model not in MODELS:
            return None, f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}."
        out["model"] = model
    layers = raw.get("layers")
    if layers is not None:
        if not isinstance(layers, dict):
            return None, "config.layers должен быть объектом {short}."
        for key, value in layers.items():
            if key not in LAYER_KEYS:
                return None, f"config.layers: неизвестный слой «{key}»."
            if not isinstance(value, bool):
                return None, f"config.layers.{key} должен быть true или false."
        out["layers"] = {k: v for k, v in layers.items() if k in LAYER_KEYS}
    tools = raw.get("tools")
    if tools is not None:
        if not isinstance(tools, bool):
            return None, "config.tools должен быть true или false."
        out["tools"] = tools
    return out, None


class Day19Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def _line(self, payload: dict) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            raise ClientGone()

    def _read_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= MAX_BODY:
            self._json(400, {"error": "Некорректное тело запроса"})
            return None
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "Тело запроса — не JSON"})
            return None
        if not isinstance(body, dict):
            self._json(400, {"error": "Тело запроса — не JSON-объект"})
            return None
        return body

    def _session_id(self, body: dict) -> str | None:
        sid = body.get("session_id")
        if not isinstance(sid, str) or not SESSION_RE.match(sid):
            self._json(400, {"error": "session_id — строка из латиницы, цифр, - и _ (до 64 символов)."})
            return None
        return sid

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)
        if path == "/":
            self._dist_index()
        elif path.startswith("/assets/"):
            self._asset(path)
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        elif path == "/api/agent":
            self._agent_info(params)
        elif path == "/api/mcp":
            self._json(200, {"servers": HUB.servers()})
        else:
            self._json(404, {"error": "Нет такого адреса"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        handler = {
            "/api/chat": self._api_chat,
            "/api/reset": self._api_reset,
            "/api/forget": self._api_forget,
            "/api/mcp/call": self._api_mcp_call,
            "/api/pipeline": self._api_pipeline,
        }.get(path)
        if handler is None:
            self._json(404, {"error": "Нет такого адреса"})
            return
        body = self._read_body()
        if body is None:
            return
        handler(body)

    def _dist_index(self):
        index = DIST_DIR / "index.html"
        if not index.exists():
            body = "Фронтенд не собран. Выполните: cd day19/frontend && npm install && npm run build"
            self._send(503, body.encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._file(index, "text/html; charset=utf-8")

    def _file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self._json(404, {"error": "Файл не найден"})
            return
        self._send(200, path.read_bytes(), ctype)

    def _asset(self, path: str) -> None:
        assets = (DIST_DIR / "assets").resolve()
        target = (assets / path[len("/assets/"):]).resolve()
        if not target.is_relative_to(assets) or not target.is_file():
            self._json(404, {"error": "Нет такого адреса"})
            return
        self._send(200, target.read_bytes(), ASSET_TYPES.get(target.suffix, "application/octet-stream"))

    def _agent_info(self, params: dict) -> None:
        sid = (params.get("session_id") or [""])[0]
        if not SESSION_RE.match(sid):
            self._json(400, {"error": "Некорректный session_id"})
            return
        agent = resolve_agent(sid)
        if agent is None:
            self._json(200, {"exists": False, "session_id": sid})
            return
        self._json(200, {"exists": True, "session_id": sid, **agent.describe()})

    def _with_global(self, handler) -> None:
        global BUSY
        with BUSY_LOCK:
            if BUSY:
                self._json(409, {"error": "Агент ещё отвечает на предыдущий запрос — подождите."})
                return
            BUSY = True
        try:
            handler()
        finally:
            with BUSY_LOCK:
                BUSY = False

    def _api_chat(self, body: dict) -> None:
        sid = self._session_id(body)
        if sid is None:
            return
        config, err = parse_config(body.get("config"))
        if err:
            self._json(400, {"error": err})
            return
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            self._json(400, {"error": "Поле message должно быть непустой строкой."})
            return
        if len(message) > MAX_CONTENT:
            self._json(400, {"error": f"Сообщение длиннее {MAX_CONTENT} символов."})
            return
        self._with_global(lambda: self._chat_locked(sid, config, message.strip()))

    def _chat_locked(self, sid: str, config: dict, message: str) -> None:
        agent = resolve_agent(sid)
        conf = dict(config)
        if "tools" in conf:
            conf["tools_enabled"] = conf.pop("tools")
        try:
            if agent is None:
                ctor = {
                    k: conf[k]
                    for k in ("name", "system_prompt", "model", "layers", "tools_enabled")
                    if k in conf
                }
                agent = Agent(**ctor, tools=OPENAI_TOOLS, tool_call=call_mcp_tool)
                agent.bind(sid, STORE)
                REGISTRY.put(sid, agent)
            else:
                agent.configure(**conf)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._stream_chat(sid, agent, message)

    def _stream_chat(self, sid: str, agent: Agent, message: str) -> None:
        info = agent.describe()
        print(
            f"-> чат: сессия {sid}, агент «{agent.name}», модель {agent.model}, "
            f"слои {agent.layers}, реплик в памяти {info['turns']}",
            flush=True,
        )
        done_event = None
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._line({
                "event": "start",
                "meta": {
                    "agent": agent.name,
                    "model": agent.model,
                    "thinking": thinking_label(agent.model),
                    "layers": dict(agent.layers),
                    "tools": agent.tools_enabled,
                    "tools_available": len(agent._tools or []),
                },
            })
            gen = agent.send_stream(message)
            try:
                for event in gen:
                    self._line(event)
                    if event["event"] == "error":
                        break
                    if event["event"] == "done":
                        done_event = event
            except ClientGone:
                print("   клиент отключился — агент прервал генерацию", flush=True)
            finally:
                gen.close()
        except (ClientGone, BrokenPipeError, ConnectionResetError):
            print("   клиент отключился", flush=True)
        finally:
            if done_event is not None:
                meta = done_event["meta"]
                cost = meta.get("cost_usd")
                cost_note = f", ${cost:.4f}" if cost is not None else ""
                tools_note = ""
                if meta.get("tool_calls"):
                    tools_note = f", инструментов {len(meta['tool_calls'])}"
                print(
                    f"   ответ готов: промпт {meta['prompt_tokens']} + ответ "
                    f"{meta['completion_tokens']} токенов{cost_note}, "
                    f"{meta['latency_ms']} мс{tools_note}",
                    flush=True,
                )
                try:
                    STORE.save(sid, agent.snapshot())
                    print(f"   диалог сохранён в {DB_PATH.name}", flush=True)
                except Exception as exc:
                    print(f"   не удалось сохранить диалог: {str(exc)[:200]}", flush=True)

    def _api_reset(self, body: dict) -> None:
        sid = self._session_id(body)
        if sid is None:
            return
        agent = resolve_agent(sid)
        if agent is None:
            self._json(404, {"error": "У этой сессии ещё нет агента — нечего сбрасывать."})
            return
        self._with_global(lambda: self._do_reset(sid, agent))

    def _do_reset(self, sid: str, agent: Agent) -> None:
        agent.reset()
        try:
            STORE.delete(sid)
        except Exception as exc:
            self._json(500, {"error": f"Не удалось удалить диалог из базы: {str(exc)[:200]}"})
            return
        print(f"   история агента «{agent.name}» очищена, диалог удалён из базы", flush=True)
        self._json(200, {"ok": True, **agent.describe()})

    def _api_forget(self, body: dict) -> None:
        sid = self._session_id(body)
        if sid is None:
            return

        def drop():
            REGISTRY.drop(sid)
            try:
                STORE.delete(sid)
            except Exception as exc:
                self._json(500, {"error": f"Не удалось удалить диалог из базы: {str(exc)[:200]}"})
                return
            print(f"   агент сессии {sid} удалён вместе с сохранённой историей", flush=True)
            self._json(200, {"ok": True})

        if REGISTRY.get(sid) is None and STORE.load(sid) is None:
            self._json(200, {"ok": True})
            return
        self._with_global(drop)

    def _api_mcp_call(self, body: dict) -> None:
        server = body.get("server")
        if not isinstance(server, str) or not server:
            self._json(400, {"error": "server — id сервера из реестра."})
            return
        tool = body.get("tool")
        if not isinstance(tool, str) or not tool:
            self._json(400, {"error": "tool — имя инструмента."})
            return
        arguments = body.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            self._json(400, {"error": "arguments — JSON-объект с аргументами."})
            return
        try:
            result = HUB.call_tool(server, tool, arguments)
        except KeyError:
            self._json(404, {"error": f"MCP-сервер «{server}» не найден в реестре."})
            return
        except LookupError:
            self._json(400, {"error": f"На сервере «{server}» нет инструмента «{tool}»."})
            return
        except Exception as exc:
            self._json(502, {"error": f"Вызов на сервере «{server}» не удался: {str(exc)[:300]}"})
            return
        print(
            f"   mcp[{server}].{tool}: is_error={result['is_error']}",
            flush=True,
        )
        self._json(200, result)

    def _api_pipeline(self, body: dict) -> None:
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            self._json(400, {"error": "Поле query должно быть непустой строкой."})
            return
        name = body.get("name")
        if name is not None and not isinstance(name, str):
            self._json(400, {"error": "Поле name должно быть строкой."})
            return
        self._with_global(lambda: self._pipeline_locked(query.strip(), name))

    def _pipeline_locked(self, query: str, name: str | None) -> None:
        """Кодо-оркестрованная цепочка: логика в iter_pipeline, здесь —
        только NDJSON-стрим событий."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self._line({"event": "start", "lane": "code", "query": query})
            done = None
            for event in iter_pipeline(query, name, call_mcp_tool):
                self._line(event)
                if event["event"] == "done":
                    done = event
            if done and not done["ok"]:
                print(
                    f"   пайплайн: этап {done['tool']} упал", flush=True)
            elif done:
                print(
                    f"   пайплайн «{query[:50]}»: {len(PIPELINE_STEPS)} этапа, "
                    f"verdict={done['verdict']}",
                    flush=True,
                )
        except (ClientGone, BrokenPipeError, ConnectionResetError):
            print("   пайплайн: клиент отключился", flush=True)


def main():
    print(
        f"День 19, композиция MCP-инструментов: "
        f"http://127.0.0.1:{PORT} (или eth0-IP из WSL), Ctrl+C — остановка",
        flush=True,
    )
    print(f"   подключаюсь к MCP-реестру ({len(MCP_SERVERS)} записей)…", flush=True)
    for s in HUB.start():
        if s["status"] == "ok":
            info = s.get("server_info") or {}
            print(
                f"   mcp[{s['id']}]: {info.get('name') or '?'} — протокол "
                f"{s['protocol_version']}, инструментов {len(s['tools'])}",
                flush=True,
            )
        else:
            print(f"   mcp[{s['id']}]: не подключён — {s['error']}", flush=True)
    global OPENAI_TOOLS
    OPENAI_TOOLS = build_openai_tools(HUB.servers())
    by_srv = {}
    for t in OPENAI_TOOLS:
        srv = t["function"]["name"].partition("__")[0]
        by_srv[srv] = by_srv.get(srv, 0) + 1
    print(
        f"   инструментов для модели: {len(OPENAI_TOOLS)}"
        + (f" ({', '.join(f'{k}: {v}' for k, v in by_srv.items())})" if by_srv else ""),
        flush=True,
    )
    print(f"   история диалогов: {DB_PATH} (сохранённых чатов: {STORE.count()})", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Day19Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
