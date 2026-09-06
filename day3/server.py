import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import DEFAULT_MODEL, MODELS, complete
from puzzle import TASK

DAY3_DIR = Path(__file__).parent
DIST_DIR = DAY3_DIR / "frontend" / "dist"
RESULTS_PATH = DAY3_DIR / "results.json"
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".map": "application/json",
    ".woff2": "font/woff2",
}
PORT = 7862
MAX_BODY = 60_000
MAX_TASK = 4000
STEP_DEADLINE_S = 240


def compute_metrics(content: str) -> dict:
    text = content.strip()
    return {
        "chars": len(text),
        "words": len(text.split()),
    }


class ClientGone(Exception):
    pass


class Day3Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    solve_lock = threading.Lock()

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

    def _file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            self._json(404, {"error": "Файл не найден"})
            return
        self._send(200, path.read_bytes(), ctype)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._dist_index()
        elif path.startswith("/assets/"):
            self._asset(path)
        elif path == "/results.json":
            self._file(RESULTS_PATH, "application/json; charset=utf-8")
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._json(404, {"error": "Нет такого адреса"})

    def _dist_index(self):
        index = DIST_DIR / "index.html"
        if not index.exists():
            body = "Фронтенд не собран. Выполните: cd day3/frontend && npm install && npm run build"
            self._send(503, body.encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._file(index, "text/html; charset=utf-8")

    def _asset(self, path: str) -> None:
        assets = (DIST_DIR / "assets").resolve()
        target = (assets / path[len("/assets/"):]).resolve()
        if not target.is_relative_to(assets) or not target.is_file():
            self._json(404, {"error": "Нет такого адреса"})
            return
        self._send(200, target.read_bytes(), ASSET_TYPES.get(target.suffix, "application/octet-stream"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/solve":
            self._json(404, {"error": "Нет такого адреса"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= MAX_BODY:
            self._json(400, {"error": "Некорректное тело запроса"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "Тело запроса — не JSON"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "Тело запроса — не JSON-объект"})
            return
        task, content, model, err = parse_solve(body)
        if err:
            self._json(400, {"error": err})
            return
        if not self.solve_lock.acquire(blocking=False):
            self._json(409, {"error": "Модель ещё отвечает на предыдущий запрос — подождите."})
            return
        try:
            self._stream_solve(task, content, model)
        finally:
            self.solve_lock.release()

    def _line(self, payload: dict) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            raise ClientGone()

    def _stream_solve(self, task: str, content: str, model: str) -> None:
        print(f"-> агент {model}, задача {len(task)} симв.", flush=True)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

        try:
            phase = self._run_step("solve", content, model)
            if phase is None:
                return
            self._line({
                "event": "done",
                "content": phase["content"],
                "metrics": compute_metrics(phase["content"]),
                "steps": [phase],
            })
            print(f"   готово: {model}, слов {compute_metrics(phase['content'])['words']}", flush=True)
        except ClientGone:
            print("   клиент отключился — генерация прервана", flush=True)

    def _run_step(self, name: str, content: str, model: str) -> dict | None:
        messages = [{"role": "user", "content": content}]
        params = {}
        print(f"   шаг {name}: модель {model}", flush=True)
        try:
            stream = complete(messages, model=model, stream=True, temperature=0, **params)
        except Exception as exc:
            self._line({"event": "error", "step": name, "message": f"Модель не приняла запрос: {str(exc)[:400]}"})
            return None

        started = time.perf_counter()
        parts = []
        finish_reason = None
        usage = None
        try:
            self._line({
                "event": "start",
                "step": name,
                "meta": {"model": model, "thinking": "disabled" if model == "glm-4.6" else "effort: low"},
                "request": {"content": content, "params": params},
            })
            deadline = time.monotonic() + STEP_DEADLINE_S
            for chunk in stream:
                if time.monotonic() > deadline:
                    self._line({"event": "error", "step": name, "message": "Истек лимит времени ответа"})
                    return None
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
                    self._line({"event": "delta", "step": name, "text": delta})

            return {
                "name": name,
                "content": "".join(parts),
                "meta": {
                    "model": model,
                    "finish_reason": finish_reason,
                    "prompt_tokens": usage.prompt_tokens if usage else None,
                    "completion_tokens": usage.completion_tokens if usage else None,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                },
                "request": {"content": content, "params": params},
            }
        except ClientGone:
            raise
        finally:
            try:
                stream.close()
            except Exception:
                pass


def parse_solve(body: dict) -> tuple:
    task = body.get("task", TASK)
    if not isinstance(task, str) or not task.strip():
        return None, None, None, "Поле task должно быть непустой строкой."
    task = task.strip()
    if len(task) > MAX_TASK:
        return None, None, None, f"Задача длиннее {MAX_TASK} символов."
    agent = body.get("agent")
    if agent is None:
        agent = {}
    if not isinstance(agent, dict):
        return None, None, None, "Поле agent должно быть JSON-объектом."
    model = agent.get("model")
    if model not in MODELS:
        model = DEFAULT_MODEL
    instruction = agent.get("instruction", "")
    if not isinstance(instruction, str):
        instruction = ""
    instruction = instruction.strip()
    content = f"{instruction}\n\nЗадача:\n{task}" if instruction else task
    return task, content, model, None


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Day3Handler)
    print(f"День 3: http://127.0.0.1:{PORT} (или eth0-IP из WSL), Ctrl+C — остановка", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
