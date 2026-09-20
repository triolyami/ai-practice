import json
import re
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from agent import ENFORCE_MODES, INVARIANT_MAX_SLUG, LAYER_KEYS, MAX_CONTENT, Agent
from config import MODELS, thinking_label
from invariants import (
    INV_MAX_BODY,
    INV_MAX_NAME,
    SLUG_RE,
    delete_invariant,
    list_invariants,
    read_invariant,
    slugify,
    write_invariant,
)
from storage import ChatStore

DAY14_DIR = Path(__file__).parent
DIST_DIR = DAY14_DIR / "frontend" / "dist"
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".map": "application/json",
    ".woff2": "font/woff2",
}
PORT = 7872
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

DB_PATH = DAY14_DIR / "data" / "chat_history.db"
STORE = ChatStore(DB_PATH)


def resolve_agent(sid: str) -> Agent | None:
    agent = REGISTRY.get(sid)
    if agent is not None:
        return agent
    snapshot = STORE.load(sid)
    if snapshot is None:
        return None
    agent = Agent.from_snapshot(snapshot)
    agent.bind(sid, STORE)
    REGISTRY.put(sid, agent)
    info = agent.invariant_info()
    print(
        f"   восстановлен диалог сессии {sid} из базы: «{agent.name}», "
        f"инварианты {info['id'] or '—'} ({agent.enforce}), "
        f"реплик {agent.describe()['turns']}",
        flush=True,
    )
    return agent


def parse_config(raw) -> tuple[dict | None, str | None]:
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return None, "Поле config должно быть JSON-объектом."
    if "profile" in raw:
        return None, "config.profile больше не поддерживается — используйте config.invariant."
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
    invariant = raw.get("invariant")
    if invariant is not None:
        if not isinstance(invariant, str):
            return None, "config.invariant должен быть строкой-слэгом."
        slug = invariant.strip()
        if len(slug) > INVARIANT_MAX_SLUG:
            return None, f"config.invariant длиннее {INVARIANT_MAX_SLUG} символов."
        if slug and not SLUG_RE.match(slug):
            return None, "config.invariant — слэг из букв, цифр, - и _."
        out["invariant"] = slug
    enforce = raw.get("enforce")
    if enforce is not None:
        if enforce not in ENFORCE_MODES:
            return None, f"config.enforce — одно из: {', '.join(ENFORCE_MODES)}."
        out["enforce"] = enforce
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
    return out, None


class Day14Handler(BaseHTTPRequestHandler):
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
        elif path == "/api/invariants":
            self._json(200, {"invariants": list_invariants()})
        elif path == "/api/invariant":
            self._invariant_get(params)
        else:
            self._json(404, {"error": "Нет такого адреса"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        handler = {
            "/api/chat": self._api_chat,
            "/api/reset": self._api_reset,
            "/api/forget": self._api_forget,
            "/api/invariant/delete": self._invariant_delete,
        }.get(path)
        if handler is None:
            self._json(404, {"error": "Нет такого адреса"})
            return
        body = self._read_body()
        if body is None:
            return
        handler(body)

    def do_PUT(self):
        path = self.path.split("?", 1)[0]
        handler = {
            "/api/invariant": self._invariant_put,
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
            body = "Фронтенд не собран. Выполните: cd day14/frontend && npm install && npm run build"
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
        try:
            if agent is None:
                ctor = {k: config[k] for k in ("name", "system_prompt", "model", "layers") if k in config}
                agent = Agent(**ctor)
                agent.bind(sid, STORE)
                extra = {k: config[k] for k in ("invariant", "enforce") if k in config}
                if extra:
                    agent.configure(**extra)
                REGISTRY.put(sid, agent)
            else:
                agent.configure(**config)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._stream_chat(sid, agent, message)

    def _stream_chat(self, sid: str, agent: Agent, message: str) -> None:
        info = agent.describe()
        iinfo = agent.invariant_info()
        print(
            f"-> чат: сессия {sid}, агент «{agent.name}», модель {agent.model}, "
            f"инварианты «{iinfo['name'] or iinfo['id'] or '—'}», режим {agent.enforce}, "
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
                    "invariant": iinfo["name"] or None,
                    "invariant_id": iinfo["id"],
                    "invariant_missing": iinfo["missing"],
                    "enforce": agent.enforce,
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
                    elif event["event"] == "violation":
                        print(
                            f"   инварианты: попытка {event['attempt']} заблокирована "
                            f"линтером ({len(event['violations'])} срабатываний)",
                            flush=True,
                        )
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
                attempts_note = f", попыток {meta['attempts']}" if meta.get("attempts", 1) > 1 else ""
                print(
                    f"   ответ готов: промпт {meta['prompt_tokens']} + ответ "
                    f"{meta['completion_tokens']} токенов{cost_note}, {meta['latency_ms']} мс{attempts_note}",
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

    def _invariant_get(self, params: dict) -> None:
        iid = (params.get("id") or [""])[0]
        if not SLUG_RE.match(iid):
            self._json(400, {"error": "id набора — слэг из букв, цифр, - и _."})
            return
        inv = read_invariant(iid)
        if inv is None:
            self._json(404, {"error": f"Набор инвариантов «{iid}» не найден."})
            return
        self._json(200, {"id": iid, "name": inv["name"], "content": inv["content"]})

    def _invariant_put(self, body: dict) -> None:
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            self._json(400, {"error": "Поле content должно быть непустой строкой (markdown набора)."})
            return
        if len(content) > INV_MAX_BODY:
            self._json(400, {"error": f"Файл набора длиннее {INV_MAX_BODY} символов."})
            return
        name = body.get("name")
        if name is not None and (not isinstance(name, str) or len(name) > INV_MAX_NAME):
            self._json(400, {"error": f"name — строка до {INV_MAX_NAME} символов."})
            return
        iid = body.get("id")
        if iid is not None:
            if not isinstance(iid, str) or not SLUG_RE.match(iid):
                self._json(400, {"error": "id набора — слэг из букв, цифр, - и _ (до 80 символов)."})
                return
        else:
            if not isinstance(name, str) or not name.strip():
                self._json(400, {"error": "Для нового набора нужно имя (name) или готовый id."})
                return
            iid = slugify(name)
            if name.strip() and not re.search(r"^#\s", content, re.MULTILINE):
                content = f"# {name.strip()}\n\n" + content
        try:
            result = write_invariant(iid, content)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        print(f"   набор инвариантов {result['id']} «{result['name']}» сохранён", flush=True)
        self._json(200, {"ok": True, **result})

    def _invariant_delete(self, body: dict) -> None:
        iid = body.get("id")
        if not isinstance(iid, str) or not SLUG_RE.match(iid):
            self._json(400, {"error": "id набора — слэг из букв, цифр, - и _ (до 80 символов)."})
            return
        existed = delete_invariant(iid)
        if existed:
            print(f"   набор инвариантов {iid} удалён; привязанные чаты продолжат без блока", flush=True)
        self._json(200, {"ok": True, "deleted": existed})


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Day14Handler)
    print(
        f"День 14, инварианты и ограничения состояния: "
        f"http://127.0.0.1:{PORT} (или eth0-IP из WSL), Ctrl+C — остановка",
        flush=True,
    )
    print(f"   история диалогов: {DB_PATH} (сохранённых чатов: {STORE.count()})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
