import json
import re
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from agent import MAX_CONTENT, LAYER_KEYS, PROFILE_MAX_SLUG, Agent
from config import MODELS, thinking_label
from memory import (
    LONGTERM_MAX_BODY,
    LONGTERM_PATH,
    MEMORY_LOCK,
    read_longterm,
    write_longterm_raw,
)
from profiles import (
    PROFILE_MAX_BODY,
    PROFILE_MAX_NAME,
    SLUG_RE,
    delete_profile,
    list_profiles,
    read_profile,
    slugify,
    write_profile,
)
from storage import ChatStore

DAY12_DIR = Path(__file__).parent
DIST_DIR = DAY12_DIR / "frontend" / "dist"
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".map": "application/json",
    ".woff2": "font/woff2",
}
PORT = 7871
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

DB_PATH = DAY12_DIR / "data" / "chat_history.db"
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
    info = agent.profile_info()
    print(
        f"   восстановлен диалог сессии {sid} из базы: «{agent.name}», "
        f"профиль {info['id'] or '—'}, реплик {agent.describe()['turns']}",
        flush=True,
    )
    return agent


def parse_config(raw) -> tuple[dict | None, str | None]:
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return None, "Поле config должно быть JSON-объектом."
    if "workspace" in raw:
        return None, "config.workspace больше не поддерживается — используйте config.profile."
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
    profile = raw.get("profile")
    if profile is not None:
        if not isinstance(profile, str):
            return None, "config.profile должен быть строкой-слэгом."
        slug = profile.strip()
        if len(slug) > PROFILE_MAX_SLUG:
            return None, f"config.profile длиннее {PROFILE_MAX_SLUG} символов."
        if slug and not SLUG_RE.match(slug):
            return None, "config.profile — слэг из букв, цифр, - и _."
        out["profile"] = slug
    layers = raw.get("layers")
    if layers is not None:
        if not isinstance(layers, dict):
            return None, "config.layers должен быть объектом {short, profile, longterm}."
        for key, value in layers.items():
            if key not in LAYER_KEYS:
                return None, f"config.layers: неизвестный слой «{key}»."
            if not isinstance(value, bool):
                return None, f"config.layers.{key} должен быть true или false."
        out["layers"] = {k: v for k, v in layers.items() if k in LAYER_KEYS}
    return out, None


class Day12Handler(BaseHTTPRequestHandler):
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
        elif path == "/api/longterm":
            self._longterm_get()
        elif path == "/api/profiles":
            self._json(200, {"profiles": list_profiles()})
        elif path == "/api/profile":
            self._profile_get(params)
        else:
            self._json(404, {"error": "Нет такого адреса"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        handler = {
            "/api/chat": self._api_chat,
            "/api/reset": self._api_reset,
            "/api/forget": self._api_forget,
            "/api/profile/delete": self._profile_delete,
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
            "/api/longterm": self._longterm_put,
            "/api/profile": self._profile_put,
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
            body = "Фронтенд не собран. Выполните: cd day12/frontend && npm install && npm run build"
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
                if "profile" in config:
                    agent.configure(profile=config["profile"])
                REGISTRY.put(sid, agent)
            else:
                agent.configure(**config)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._stream_chat(sid, agent, message)

    def _stream_chat(self, sid: str, agent: Agent, message: str) -> None:
        info = agent.describe()
        pinfo = agent.profile_info()
        print(
            f"-> чат: сессия {sid}, агент «{agent.name}», модель {agent.model}, "
            f"профиль «{pinfo['name'] or pinfo['id'] or '—'}», слои {agent.layers}, "
            f"реплик в памяти {info['turns']}",
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
                    "profile": pinfo["name"] or None,
                    "profile_id": pinfo["id"],
                    "profile_missing": pinfo["missing"],
                    "pipeline": pinfo["pipeline"] if agent.layers["profile"] else [],
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
                    elif event["event"] == "step_start":
                        print(
                            f"   шаг {event['step'] + 1}/{len(event['pipeline'])} «{event['name']}»",
                            flush=True,
                        )
                    elif event["event"] == "memory":
                        print(
                            f"   память обновлена: учтено {event['covered']} сообщ., "
                            f"в долговременную +{len(event['longterm_added'])}",
                            flush=True,
                        )
                    elif event["event"] == "notice":
                        print(f"   замечание: {event['message']}", flush=True)
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
                print(
                    f"   ответ готов: промпт {meta['prompt_tokens']} + ответ "
                    f"{meta['completion_tokens']} токенов{cost_note}, {meta['latency_ms']} мс",
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
        print(f"   память агента «{agent.name}» очищена, диалог удалён из базы", flush=True)
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

    def _longterm_get(self) -> None:
        data = read_longterm(LONGTERM_PATH)
        self._json(200, {"content": data["content"], "sections": data["sections"]})

    def _longterm_put(self, body: dict) -> None:
        content = body.get("content")
        if not isinstance(content, str):
            self._json(400, {"error": "Поле content должно быть строкой."})
            return
        if len(content) > LONGTERM_MAX_BODY:
            self._json(400, {"error": f"Файл длиннее {LONGTERM_MAX_BODY} символов."})
            return
        with MEMORY_LOCK:
            data = write_longterm_raw(LONGTERM_PATH, content)
        print(f"   долговременная память перезаписана вручную ({len(content)} символов)", flush=True)
        self._json(200, {"ok": True, "content": data["content"], "sections": data["sections"]})

    def _profile_get(self, params: dict) -> None:
        pid = (params.get("id") or [""])[0]
        if not SLUG_RE.match(pid):
            self._json(400, {"error": "id профиля — слэг из букв, цифр, - и _."})
            return
        prof = read_profile(pid)
        if prof is None:
            self._json(404, {"error": f"Профиль «{pid}» не найден."})
            return
        self._json(200, {"id": pid, "name": prof["name"], "content": prof["content"]})

    def _profile_put(self, body: dict) -> None:
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            self._json(400, {"error": "Поле content должно быть непустой строкой (markdown профиля)."})
            return
        if len(content) > PROFILE_MAX_BODY:
            self._json(400, {"error": f"Файл профиля длиннее {PROFILE_MAX_BODY} символов."})
            return
        name = body.get("name")
        if name is not None and (not isinstance(name, str) or len(name) > PROFILE_MAX_NAME):
            self._json(400, {"error": f"name — строка до {PROFILE_MAX_NAME} символов."})
            return
        pid = body.get("id")
        if pid is not None:
            if not isinstance(pid, str) or not SLUG_RE.match(pid):
                self._json(400, {"error": "id профиля — слэг из букв, цифр, - и _ (до 80 символов)."})
                return
        else:
            if not isinstance(name, str) or not name.strip():
                self._json(400, {"error": "Для нового профиля нужно имя (name) или готовый id."})
                return
            pid = slugify(name)
            if name.strip() and not re.search(r"^#\s", content, re.MULTILINE):
                content = f"# {name.strip()}\n\n" + content
        try:
            result = write_profile(pid, content)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        print(f"   профиль {result['id']} «{result['name']}» сохранён", flush=True)
        self._json(200, {"ok": True, **result})

    def _profile_delete(self, body: dict) -> None:
        pid = body.get("id")
        if not isinstance(pid, str) or not SLUG_RE.match(pid):
            self._json(400, {"error": "id профиля — слэг из букв, цифр, - и _ (до 80 символов)."})
            return
        existed = delete_profile(pid)
        if existed:
            print(f"   профиль {pid} удалён; привязанные чаты продолжат без профиля", flush=True)
        self._json(200, {"ok": True, "deleted": existed})


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Day12Handler)
    print(
        f"День 12, персонализация ассистента (профили + память): "
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
