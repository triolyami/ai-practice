import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import MODELS, complete

LAB_DIR = Path(__file__).parent
DAY2_INDEX = LAB_DIR.parent / "day2" / "index.html"
DIST_DIR = LAB_DIR / "frontend" / "dist"
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".map": "application/json",
    ".woff2": "font/woff2",
}
PORT = 7861
MAX_BODY = 400_000
CHAT_DEADLINE_S = 240
MAX_MESSAGES = 40
MAX_CONTENT = 8000

VIAS = ("off", "prompt", "api")
FORMAT_KINDS = ("json", "markdown")
FORMAT_INSTRUCTIONS = {
    "json": "Ответь строго валидным JSON без markdown-ограждений и пояснений.",
    "markdown": "Оформи ответ в Markdown: заголовки, списки, выделение и блоки кода — где уместно.",
}
STOP_TEMPLATE = "Заверши ответ непосредственно перед последовательностью «{s}» и не включай её в ответ."

ESCAPES = (("\\r", "\r"), ("\\n", "\n"), ("\\t", "\t"))
PLAIN = (("\r", "\\r"), ("\n", "\\n"), ("\t", "\\t"))


def plural(n: int, forms: tuple) -> str:
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return forms[0]
    if 2 <= m10 <= 4 and (m100 < 10 or m100 >= 20):
        return forms[1]
    return forms[2]


def unescape_seq(s: str) -> str:
    for raw, real in ESCAPES:
        s = s.replace(raw, real)
    return s


def escape_seq(s: str) -> str:
    for real, raw in PLAIN:
        s = s.replace(real, raw)
    return s


def parse_settings(raw) -> tuple:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return None, "Настройки сообщения должны быть объектом."

    fmt = raw.get("format") or {}
    if not isinstance(fmt, dict):
        return None, "Настройки формата должны быть объектом."
    fmt_via = fmt.get("via", "off")
    if fmt_via not in VIAS:
        return None, f"Неизвестный режим формата: {fmt_via}."
    fmt_kind = fmt.get("kind", "json")
    if fmt_kind not in FORMAT_KINDS:
        return None, f"Неизвестный формат: {fmt_kind}."
    if fmt_via == "api" and fmt_kind != "json":
        return None, "response_format на API умеет только JSON — для Markdown выберите режим «промпт»."

    length = raw.get("length") or {}
    if not isinstance(length, dict):
        return None, "Настройки длины должны быть объектом."
    len_via = length.get("via", "off")
    if len_via not in VIAS:
        return None, f"Неизвестный режим длины: {len_via}."
    try:
        words = int(length.get("words", 30))
        max_tokens = int(length.get("max_tokens", 60))
    except (TypeError, ValueError):
        return None, "Лимиты длины должны быть целыми числами."
    if not 1 <= words <= 1000:
        return None, "Лимит слов — целое от 1 до 1000."
    if not 1 <= max_tokens <= 8192:
        return None, "max_tokens — целое от 1 до 8192."

    stop = raw.get("stop") or {}
    if not isinstance(stop, dict):
        return None, "Настройки завершения должны быть объектом."
    stop_via = stop.get("via", "off")
    if stop_via not in VIAS:
        return None, f"Неизвестный режим завершения: {stop_via}."
    stop_seq = unescape_seq(str(stop.get("sequence") or ""))
    if stop_via != "off" and not (0 < len(stop_seq) <= 200):
        return None, "stop-последовательность пустая или длиннее 200 символов."

    settings = {
        "format": {"via": fmt_via, "kind": fmt_kind},
        "length": {"via": len_via, "words": words, "max_tokens": max_tokens},
        "stop": {"via": stop_via, "sequence": stop_seq},
    }
    return settings, None


def parse_chat(body: dict) -> tuple:
    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return None, "Поле messages должно быть непустым списком."
    if len(raw_messages) > MAX_MESSAGES:
        return None, f"Слишком длинный диалог: максимум {MAX_MESSAGES} сообщений."

    model = body.get("model", "glm-4.6")
    if model not in MODELS:
        return None, f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}."

    try:
        temperature = float(body.get("temperature", 0))
    except (TypeError, ValueError):
        return None, "temperature должна быть числом от 0 до 1."
    temperature = max(0.0, min(1.0, temperature))

    messages = []
    for i, raw in enumerate(raw_messages):
        if not isinstance(raw, dict):
            return None, f"Сообщение №{i + 1} — не объект."
        role = raw.get("role")
        content = raw.get("content")
        if role not in ("user", "assistant"):
            return None, f"Сообщение №{i + 1}: роль должна быть user или assistant."
        if not isinstance(content, str) or not content.strip():
            return None, f"Сообщение №{i + 1} пустое."
        if len(content) > MAX_CONTENT:
            return None, f"Сообщение №{i + 1} длиннее {MAX_CONTENT} символов."
        settings = None
        if role == "user":
            settings, err = parse_settings(raw.get("settings"))
            if err:
                return None, f"Сообщение №{i + 1}: {err}"
        messages.append({"role": role, "content": content.strip(), "settings": settings})

    if messages[-1]["role"] != "user":
        return None, "Последнее сообщение должно быть от пользователя."

    req = {
        "model": model,
        "temperature": round(temperature, 2),
        "messages": messages,
    }
    return req, None


def prompt_additions(s: dict) -> list:
    parts = []
    if s["format"]["via"] == "prompt":
        parts.append(FORMAT_INSTRUCTIONS[s["format"]["kind"]])
    if s["length"]["via"] == "prompt":
        n = s["length"]["words"]
        parts.append(f"Ответь не более чем {n} {plural(n, ('словом', 'словами', 'словами'))}.")
    if s["stop"]["via"] == "prompt":
        parts.append(STOP_TEMPLATE.format(s=escape_seq(s["stop"]["sequence"])))
    return parts


def augment(content: str, s: dict) -> str:
    additions = prompt_additions(s)
    return content if not additions else content + " " + " ".join(additions)


def api_params(s: dict) -> dict:
    params = {}
    if s["format"]["via"] == "api":
        params["response_format"] = {"type": "json_object"}
    if s["length"]["via"] == "api":
        params["max_tokens"] = s["length"]["max_tokens"]
    if s["stop"]["via"] == "api":
        params["stop"] = [s["stop"]["sequence"]]
    return params


def compute_metrics(content: str) -> dict:
    text = content.strip()
    metrics = {
        "chars": len(text),
        "words": len(text.split()),
        "paragraphs": text.count("\n\n") + 1 if text else 0,
        "markdown_fence": text.startswith("```"),
        "ends_mid_sentence": bool(text) and text[-1] not in ".!?…»\"",
    }
    try:
        json.loads(text)
        metrics["valid_json"] = True
    except (json.JSONDecodeError, ValueError):
        metrics["valid_json"] = False
    return metrics


class ClientGone(Exception):
    pass


class LabHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    chat_lock = threading.Lock()

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
        elif path == "/day2":
            self._file(DAY2_INDEX, "text/html; charset=utf-8")
        elif path.startswith("/assets/"):
            self._asset(path)
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._json(404, {"error": "Нет такого адреса"})

    def _dist_index(self):
        index = DIST_DIR / "index.html"
        if not index.exists():
            body = "Фронтенд не собран. Выполните: cd lab/frontend && npm install && npm run build"
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
        if path != "/api/chat":
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
        req, err = parse_chat(body)
        if err:
            self._json(400, {"error": err})
            return
        if not self.chat_lock.acquire(blocking=False):
            self._json(409, {"error": "Модель ещё отвечает на предыдущий запрос — подождите."})
            return
        try:
            self._stream_chat(req)
        finally:
            self.chat_lock.release()

    def _line(self, payload: dict) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            raise ClientGone()

    def _stream_chat(self, req: dict) -> None:
        model = req["model"]
        last = req["messages"][-1]
        params = api_params(last["settings"])
        sent = [
            {"role": m["role"], "content": augment(m["content"], m["settings"]) if m["role"] == "user" else m["content"]}
            for m in req["messages"]
        ]

        print(
            f"-> чат: модель {model}, temperature {req['temperature']}, "
            f"сообщений {len(sent)}, параметры API: {params or 'нет'}",
            flush=True,
        )

        try:
            stream = complete(sent, model=model, stream=True, temperature=req["temperature"], **params)
        except Exception as exc:
            self._json(502, {"error": f"Модель не приняла запрос: {str(exc)[:400]}"})
            return

        started = time.perf_counter()
        parts = []
        finish_reason = None
        usage = None
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._line({
                "event": "start",
                "meta": {
                    "model": model,
                    "temperature": req["temperature"],
                    "thinking": "disabled" if model == "glm-4.6" else "effort: low",
                    "params": params,
                },
                "request": {"content": sent[-1]["content"], "params": params},
            })

            deadline = time.monotonic() + CHAT_DEADLINE_S
            for chunk in stream:
                if time.monotonic() > deadline:
                    self._line({"event": "error", "message": "Истек лимит времени ответа"})
                    break
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
                "model": model,
                "finish_reason": finish_reason,
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "metrics": compute_metrics(content),
                "request": {"content": sent[-1]["content"], "params": params},
            })
            status = f"finish={finish_reason}, слов {compute_metrics(content)['words']}"
            print(f"   ответ готов: {status}", flush=True)
        except ClientGone:
            print("   клиент отключился — генерация прервана", flush=True)
        finally:
            try:
                stream.close()
            except Exception:
                pass


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), LabHandler)
    print(f"Лаборатория: http://127.0.0.1:{PORT} (или eth0-IP из WSL), Ctrl+C — остановка", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
