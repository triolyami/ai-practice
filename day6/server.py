import json
import re
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent import MAX_CONTENT, Agent
from config import MODELS, thinking_label

DAY6_DIR = Path(__file__).parent
DIST_DIR = DAY6_DIR / "frontend" / "dist"
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".map": "application/json",
    ".woff2": "font/woff2",
}
PORT = 7865
MAX_BODY = 100_000
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


REGISTRY = AgentRegistry()
BUSY: set[str] = set()
BUSY_LOCK = threading.Lock()


def parse_config(raw) -> tuple[dict | None, str | None]:
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return None, "Поле config должно быть JSON-объектом."
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
    return out, None


class Day6Handler(BaseHTTPRequestHandler):
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
        path, _, query = self.path.partition("?")
        path = path.rstrip("/") or "/"
        if path == "/":
            self._dist_index()
        elif path.startswith("/assets/"):
            self._asset(path)
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        elif path == "/api/agent":
            self._agent_info(query)
        else:
            self._json(404, {"error": "Нет такого адреса"})

    def _dist_index(self):
        index = DIST_DIR / "index.html"
        if not index.exists():
            body = "Фронтенд не собран. Выполните: cd day6/frontend && npm install && npm run build"
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

    def _agent_info(self, query: str) -> None:
        params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
        sid = params.get("session_id", "")
        if not SESSION_RE.match(sid):
            self._json(400, {"error": "Некорректный session_id"})
            return
        agent = REGISTRY.get(sid)
        if agent is None:
            self._json(200, {"exists": False, "session_id": sid})
            return
        self._json(200, {"exists": True, "session_id": sid, **agent.describe()})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        handler = {
            "/api/chat": self._api_chat,
            "/api/reset": self._api_reset,
            "/api/forget": self._api_forget,
        }.get(path)
        if handler is None:
            self._json(404, {"error": "Нет такого адреса"})
            return
        body = self._read_body()
        if body is None:
            return
        sid = self._session_id(body)
        if sid is None:
            return
        handler(sid, body)

    def _with_session(self, sid: str, handler) -> None:
        with BUSY_LOCK:
            if sid in BUSY:
                self._json(409, {"error": "Агент ещё отвечает на предыдущий запрос — подождите."})
                return
            BUSY.add(sid)
        try:
            handler()
        finally:
            with BUSY_LOCK:
                BUSY.discard(sid)

    def _api_chat(self, sid: str, body: dict) -> None:
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
        self._with_session(sid, lambda: self._chat_locked(sid, config, message.strip()))

    def _chat_locked(self, sid: str, config: dict, message: str) -> None:
        agent = REGISTRY.get(sid)
        if agent is not None:
            try:
                agent.configure(**config)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
        self._stream_chat(sid, agent, config, message)

    def _stream_chat(self, sid: str, agent: Agent | None, config: dict, message: str) -> None:
        if agent is None:
            agent = Agent(**config) if config else Agent()
            REGISTRY.put(sid, agent)
        print(
            f"-> чат: сессия {sid}, агент «{agent.name}», модель {agent.model}, "
            f"реплик в памяти {agent.describe()['turns']}",
            flush=True,
        )
        finished = None
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._line({
                "event": "start",
                "meta": {"agent": agent.name, "model": agent.model, "thinking": thinking_label(agent.model)},
            })
            gen = agent.send_stream(message)
            try:
                for event in gen:
                    self._line(event)
                    finished = event
                    if event["event"] == "error":
                        break
            except ClientGone:
                print("   клиент отключился — агент прервал генерацию", flush=True)
            finally:
                gen.close()
        except (ClientGone, BrokenPipeError, ConnectionResetError):
            print("   клиент отключился", flush=True)
        finally:
            if finished is not None and finished.get("event") == "done":
                meta = finished["meta"]
                print(
                    f"   ответ готов: {meta['completion_tokens']} токенов, {meta['latency_ms']} мс",
                    flush=True,
                )

    def _api_reset(self, sid: str, body: dict) -> None:
        agent = REGISTRY.get(sid)
        if agent is None:
            self._json(404, {"error": "У этой сессии ещё нет агента — нечего сбрасывать."})
            return
        self._with_session(sid, lambda: self._do_reset(agent))

    def _do_reset(self, agent: Agent) -> None:
        agent.reset()
        print(f"   память агента «{agent.name}» очищена", flush=True)
        self._json(200, {"ok": True, **agent.describe()})

    def _api_forget(self, sid: str, body: dict) -> None:
        def drop():
            REGISTRY.drop(sid)
            print(f"   агент сессии {sid} удалён", flush=True)
            self._json(200, {"ok": True})

        if not REGISTRY.get(sid):
            self._json(200, {"ok": True})
            return
        self._with_session(sid, drop)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Day6Handler)
    print(f"День 6, первый агент: http://127.0.0.1:{PORT} (или eth0-IP из WSL), Ctrl+C — остановка", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
