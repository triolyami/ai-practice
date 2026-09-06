import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS, MODELS, complete, thinking_label
from defaults import DEFAULT_PROMPT

DAY4_DIR = Path(__file__).parent
DIST_DIR = DAY4_DIR / "frontend" / "dist"
RESULTS_PATH = DAY4_DIR / "results.json"
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".map": "application/json",
    ".woff2": "font/woff2",
}
PORT = 7863
MAX_BODY = 20_000
MAX_PROMPT = 4000
MAX_TEMPERATURE = 2.0
RUN_DEADLINE_S = 180


class ClientGone(Exception):
    pass


def compute_metrics(content: str) -> dict:
    text = content.strip()
    return {"chars": len(text), "words": len(text.split())}


def parse_run(body: dict) -> tuple:
    prompt = body.get("prompt", DEFAULT_PROMPT)
    if not isinstance(prompt, str) or not prompt.strip():
        return None, "Поле prompt должно быть непустой строкой."
    prompt = prompt.strip()
    if len(prompt) > MAX_PROMPT:
        return None, f"Промпт длиннее {MAX_PROMPT} символов."
    model = body.get("model")
    if model not in MODELS:
        model = DEFAULT_MODEL
    temperature = body.get("temperature", 0)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        return None, "Поле temperature должно быть числом."
    temperature = float(temperature)
    if not 0 <= temperature <= MAX_TEMPERATURE:
        return None, f"temperature должна быть в диапазоне 0–{MAX_TEMPERATURE}."
    effort = body.get("effort")
    if effort not in EFFORTS:
        effort = DEFAULT_EFFORT
    return {"prompt": prompt, "model": model, "temperature": temperature, "effort": effort}, None


class Day4Handler(BaseHTTPRequestHandler):
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
            body = "Фронтенд не собран. Выполните: cd day4/frontend && npm install && npm run build"
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

    def _read_body(self, limit: int):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= limit:
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

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/run":
            body = self._read_body(MAX_BODY)
            if body is None:
                return
            req, err = parse_run(body)
            if err:
                self._json(400, {"error": err})
                return
            self._stream_run(req)
        else:
            self._json(404, {"error": "Нет такого адреса"})

    def _line(self, payload: dict) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            raise ClientGone()

    def _stream_run(self, req: dict) -> None:
        prompt, model = req["prompt"], req["model"]
        temperature, effort = req["temperature"], req["effort"]
        print(f"-> запуск {model}, temperature={temperature}, {thinking_label(model)}, промпт {len(prompt)} симв.", flush=True)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

        try:
            messages = [{"role": "user", "content": prompt}]
            params = {"temperature": temperature}
            try:
                stream = complete(messages, model=model, stream=True, effort=effort, **params)
            except Exception as exc:
                self._line({"event": "error", "message": f"Модель не приняла запрос: {str(exc)[:400]}"})
                return

            started = time.perf_counter()
            parts = []
            finish_reason = None
            usage = None
            try:
                self._line({
                    "event": "start",
                    "meta": {"model": model, "temperature": temperature, "thinking": thinking_label(model, effort)},
                    "request": {"prompt": prompt, "params": {**params, "effort": effort}},
                })
                deadline = time.monotonic() + RUN_DEADLINE_S
                for chunk in stream:
                    if time.monotonic() > deadline:
                        self._line({"event": "error", "message": "Истек лимит времени ответа"})
                        return
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
                        self._line({"event": "delta", "text": delta})

                content = "".join(parts)
                self._line({
                    "event": "done",
                    "content": content,
                    "metrics": compute_metrics(content),
                    "meta": {
                        "model": model,
                        "temperature": temperature,
                        "finish_reason": finish_reason,
                        "effort": effort if MODELS[model]["thinking"] == "effort" else None,
                        "prompt_tokens": usage.prompt_tokens if usage else None,
                        "completion_tokens": usage.completion_tokens if usage else None,
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    },
                })
                print(f"   готово: {model} t={temperature}, слов {compute_metrics(content)['words']}", flush=True)
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
        except ClientGone:
            print("   клиент отключился — генерация прервана", flush=True)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Day4Handler)
    print(f"День 4: http://127.0.0.1:{PORT} (или eth0-IP из WSL), Ctrl+C — остановка", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
