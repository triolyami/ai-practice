import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import DEFAULT_MODEL, MODELS, complete

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
MAX_BODY = 100_000
RUN_DEADLINE_S = 300

GROUPS = {
    "format": {
        "name": "Формат ответа",
        "question": "Заставит ли модель отвечать структурированным JSON?",
    },
    "length": {
        "name": "Длина ответа",
        "question": "Сдержит ли модель длину ответа?",
    },
    "stop": {
        "name": "Условие завершения",
        "question": "Сможем ли остановить генерацию в нужной точке?",
    },
}

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


def parse_config(body: dict):
    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None, "Промпт пустой — введите текст запроса."
    if len(prompt) > 8000:
        return None, "Промпт слишком длинный: максимум 8000 символов."

    model = body.get("model", DEFAULT_MODEL)
    if model not in MODELS:
        return None, f"Неизвестная модель: {model}. Доступны: {', '.join(MODELS)}."

    try:
        temperature = float(body.get("temperature", 0))
    except (TypeError, ValueError):
        return None, "temperature должна быть числом от 0 до 1."
    temperature = max(0.0, min(1.0, temperature))

    controls = body.get("controls") or {}
    if not isinstance(controls, dict):
        return None, "Поле controls должно быть объектом."

    def control(name: str) -> dict:
        value = controls.get(name) or {}
        return value if isinstance(value, dict) else {}

    fmt = control("format")
    fmt_on = bool(fmt.get("enabled"))
    fmt_instruction = str(fmt.get("instruction") or "").strip()
    if fmt_on and not (0 < len(fmt_instruction) <= 2000):
        return None, "Инструкция формата пустая или длиннее 2000 символов."

    length = control("length")
    length_on = bool(length.get("enabled"))
    try:
        words = int(length.get("words", 30))
        max_tokens = int(length.get("max_tokens", 60))
    except (TypeError, ValueError):
        return None, "Лимиты длины должны быть целыми числами."
    if not 1 <= words <= 1000:
        return None, "Лимит слов — целое от 1 до 1000."
    if not 1 <= max_tokens <= 8192:
        return None, "max_tokens — целое от 1 до 8192."
    length_template = str(length.get("template") or "").strip()
    if length_on and not (0 < len(length_template) <= 2000):
        return None, "Шаблон инструкции длины пустой или длиннее 2000 символов."

    stop = control("stop")
    stop_on = bool(stop.get("enabled"))
    stop_seq = unescape_seq(str(stop.get("sequence") or ""))
    if stop_on and not (0 < len(stop_seq) <= 200):
        return None, "stop-последовательность пустая или длиннее 200 символов."
    stop_instruction = str(stop.get("instruction") or "").strip()
    if stop_on and not (0 < len(stop_instruction) <= 2000):
        return None, "Инструкция завершения пустая или длиннее 2000 символов."

    cfg = {
        "prompt": prompt.strip(),
        "model": model,
        "temperature": round(temperature, 2),
        "format": {"enabled": fmt_on, "instruction": fmt_instruction},
        "length": {
            "enabled": length_on,
            "words": words,
            "max_tokens": max_tokens,
            "template": length_template,
        },
        "stop": {
            "enabled": stop_on,
            "sequence": stop_seq,
            "instruction": stop_instruction,
        },
    }
    return cfg, None


def build_variants(cfg: dict) -> list:
    prompt = cfg["prompt"]
    variants = [
        {
            "id": "baseline",
            "group": None,
            "kind": "base",
            "title": "Без ограничений",
            "mechanism": "Эталонный запуск: только базовый промпт, без дополнительных инструкций и параметров.",
            "prompt": prompt,
            "params": {},
        }
    ]

    if cfg["format"]["enabled"]:
        instr = cfg["format"]["instruction"]
        suffixed = f"{prompt} {instr}"
        variants.append(
            {
                "id": "format-prompt",
                "group": "format",
                "kind": "prompt",
                "title": "Инструкция в промпте",
                "mechanism": "Формат описан словами прямо в запросе. Для модели это просьба: обычно она слушается, но без гарантий.",
                "prompt": suffixed,
                "params": {},
            }
        )
        variants.append(
            {
                "id": "format-api",
                "group": "format",
                "kind": "api",
                "title": "response_format: json_object",
                "mechanism": "Тот же промпт плюс API-параметр response_format. Сервер гарантирует парсируемый JSON, но схему всё равно описывает промпт.",
                "prompt": suffixed,
                "params": {"response_format": {"type": "json_object"}},
            }
        )

    if cfg["length"]["enabled"]:
        words = cfg["length"]["words"]
        max_tokens = cfg["length"]["max_tokens"]
        instr = cfg["length"]["template"].replace("{n}", str(words))
        variants.append(
            {
                "id": "length-prompt",
                "group": "length",
                "kind": "prompt",
                "title": "Инструкция в промпте",
                "mechanism": f"Просьба уложиться в {words} {plural(words, ('слово', 'слова', 'слов'))}. Выполнит ли модель её — как повезёт.",
                "prompt": f"{prompt} {instr}",
                "params": {},
            }
        )
        variants.append(
            {
                "id": "length-api",
                "group": "length",
                "kind": "api",
                "title": f"max_tokens = {max_tokens}",
                "mechanism": f"Базовый промпт плюс жёсткий лимит {max_tokens} выходных токенов на стороне API: генерация обрывается, finish_reason = length.",
                "prompt": prompt,
                "params": {"max_tokens": max_tokens},
            }
        )

    if cfg["stop"]["enabled"]:
        seq = cfg["stop"]["sequence"]
        shown = escape_seq(seq)
        variants.append(
            {
                "id": "stop-prompt",
                "group": "stop",
                "kind": "prompt",
                "title": "Инструкция в промпте",
                "mechanism": "Явная инструкция остановиться в заданном месте. Станет ли она границей текста — решает модель.",
                "prompt": f"{prompt} {cfg['stop']['instruction']}",
                "params": {},
            }
        )
        variants.append(
            {
                "id": "stop-api",
                "group": "stop",
                "kind": "api",
                "title": f'stop: ["{shown}"]',
                "mechanism": f"Базовый промпт плюс stop-последовательность «{shown}» на стороне API: генерация обрывается на первом вхождении, остаток ответа не существует.",
                "prompt": prompt,
                "params": {"stop": [seq]},
            }
        )

    return variants


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


def run_variant(cfg: dict, variant: dict) -> dict:
    started = time.perf_counter()
    response = complete(
        [{"role": "user", "content": variant["prompt"]}],
        model=cfg["model"],
        temperature=cfg["temperature"],
        **variant["params"],
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    choice = response.choices[0]
    content = choice.message.content or ""
    return {
        "id": variant["id"],
        "group": variant["group"],
        "kind": variant["kind"],
        "title": variant["title"],
        "mechanism": variant["mechanism"],
        "request": {"prompt": variant["prompt"], "params": variant["params"]},
        "content": content,
        "finish_reason": choice.finish_reason,
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "latency_ms": elapsed_ms,
        "metrics": compute_metrics(content),
    }


def error_run(variant: dict, exc: Exception) -> dict:
    return {
        "id": variant["id"],
        "group": variant["group"],
        "kind": variant["kind"],
        "title": variant["title"],
        "mechanism": variant["mechanism"],
        "request": {"prompt": variant["prompt"], "params": variant["params"]},
        "content": "",
        "error": str(exc)[:500],
        "finish_reason": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "latency_ms": None,
        "metrics": compute_metrics(""),
    }


class ClientGone(Exception):
    pass


class LabHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    run_lock = threading.Lock()

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
        if path != "/api/run":
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
        cfg, err = parse_config(body)
        if err:
            self._json(400, {"error": err})
            return
        if not self.run_lock.acquire(blocking=False):
            self._json(409, {"error": "Предыдущий запуск ещё выполняется — подождите."})
            return
        try:
            self._stream_run(cfg)
        finally:
            self.run_lock.release()

    def _line(self, payload: dict) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            raise ClientGone()

    def _stream_run(self, cfg: dict) -> None:
        variants = build_variants(cfg)
        total = len(variants)
        events: queue.Queue = queue.Queue()
        cancel = threading.Event()

        def worker(variant: dict):
            if cancel.is_set():
                return
            try:
                events.put(run_variant(cfg, variant))
            except Exception as exc:
                events.put(error_run(variant, exc))

        print(f"-> запуск: {total} {plural(total, ('прогон', 'прогона', 'прогонов'))}, "
              f"модель {cfg['model']}, temperature {cfg['temperature']}", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        started = time.perf_counter()
        try:
            self._line({
                "event": "start",
                "total": total,
                "meta": {
                    "model": cfg["model"],
                    "temperature": cfg["temperature"],
                    "thinking": "disabled" if cfg["model"] == "glm-4.6" else "effort: low",
                    "base_prompt": cfg["prompt"],
                },
                "groups": {k: GROUPS[k] for k in ("format", "length", "stop") if any(v["group"] == k for v in variants)},
                "variants": [
                    {k: v[k] for k in ("id", "group", "kind", "title", "mechanism")}
                    for v in variants
                ],
            })

            for variant in variants:
                threading.Thread(target=worker, args=(variant,), daemon=True).start()

            delivered = 0
            deadline = time.monotonic() + RUN_DEADLINE_S
            while delivered < total and time.monotonic() < deadline and not cancel.is_set():
                try:
                    run = events.get(timeout=2)
                except queue.Empty:
                    continue
                delivered += 1
                status = run.get("error") or f"finish={run['finish_reason']} words={run['metrics']['words']}"
                print(f"   [{delivered}/{total}] {run['id']}: {status}", flush=True)
                self._line({"event": "result", "run": run, "delivered": delivered})

            if delivered < total:
                self._line({"event": "error", "message": "Истек лимит времени прогона"})
            self._line({
                "event": "done",
                "delivered": delivered,
                "elapsed_s": round(time.perf_counter() - started, 1),
            })
            print(f"   готово: {delivered}/{total} за {round(time.perf_counter() - started, 1)} с", flush=True)
        except ClientGone:
            cancel.set()
            print("   клиент отключился — запуск отменён", flush=True)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), LabHandler)
    print(f"Лаборатория: http://127.0.0.1:{PORT} (или eth0-IP из WSL), Ctrl+C — остановка", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
