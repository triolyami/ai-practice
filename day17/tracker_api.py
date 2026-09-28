"""REST API мок-трекера задач (Яндекс.Трекер-style): stdlib + SQLite.

HTTP-слой — единственная граница: MCP-сервер в tracker_server.py ходит
сюда urllib-запросами и не трогает базу напрямую. Процесс-хозяин —
MCP-сервер: `start_api()` поднимает ThreadingHTTPServer на 127.0.0.1:0
в daemon-потоке и возвращает фактический порт. База — day17/data/
tracker.db (WAL); при пустой базе сидится набор задач.

Самостоятельный запуск для проверки curl-ом:

    .venv/bin/python day17/tracker_api.py            # порт 0 -> печать реального
    .venv/bin/python day17/tracker_api.py 7890       # фиксированный порт
"""
import json
import sqlite3
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DAY17_DIR = Path(__file__).parent
DEFAULT_DB = DAY17_DIR / "data" / "tracker.db"
MAX_BODY = 100_000

STATUSES = ("open", "in_progress", "done")
PRIORITIES = ("low", "normal", "high")

SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

SEED = [
    (
        "Разобрать падение сборки на Windows",
        "CI красный третий день: pip не находит wheel для Python 3.14.",
        "in_progress",
        "high",
        ["Воспроизвёлось локально — нужен фолбэк на source-дистрибутив."],
    ),
    (
        "Сверстать страницу настроек агента",
        "Поля: имя, системный промпт, модель. Макет в фигме «agent-settings».",
        "open",
        "normal",
        [],
    ),
    (
        "Обновить MCP SDK до 2.x",
        "Сейчас pinned mcp>=2.2,<3 — проверить changelog на breaking changes.",
        "open",
        "low",
        [],
    ),
    (
        "Написать smoke-тесты на /api/chat",
        "Минимум: старт сессии, стрим NDJSON, сброс диалога.",
        "done",
        "normal",
        ["Покрыто offline_check.py — вопрос закрыт."],
    ),
    (
        "Спроектировать схему БД трекера",
        "issues + comments, статусы open/in_progress/done, приоритеты low/normal/high.",
        "open",
        "high",
        [],
    ),
]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        empty = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 0
        if empty:
            for title, desc, status, priority, comments in SEED:
                cur = conn.execute(
                    "INSERT INTO issues (title, description, status, priority, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (title, desc, status, priority, _now()),
                )
                for text in comments:
                    conn.execute(
                        "INSERT INTO comments (issue_id, text, created_at) VALUES (?, ?, ?)",
                        (cur.lastrowid, text, _now()),
                    )


def _issue_out(row: sqlite3.Row, comments=None) -> dict:
    out = {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "priority": row["priority"],
        "created_at": row["created_at"],
    }
    if comments is not None:
        out["comments"] = comments
    return out


def make_handler(db_path: Path):
    class TrackerHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt, *args):
            import sys
            print(
                f"[tracker {time.strftime('%H:%M:%S')}] {fmt % args}",
                file=sys.stderr,
                flush=True,
            )

        def _json(self, code: int, payload) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BODY:
                self._json(400, {"error": "нужен JSON-объект в теле запроса"})
                return None
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"error": "тело запроса — не JSON"})
                return None
            if not isinstance(body, dict):
                self._json(400, {"error": "тело запроса — не JSON-объект"})
                return None
            return body

        def _issue(self, issue_id: int):
            with closing(_connect(db_path)) as conn:
                return conn.execute(
                    "SELECT * FROM issues WHERE id = ?", (issue_id,)
                ).fetchone()

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/issues":
                params = parse_qs(parsed.query)
                status = (params.get("status") or [None])[0]
                if status is not None and status not in STATUSES:
                    self._json(400, {
                        "error": f"status должен быть одним из: {', '.join(STATUSES)}"
                    })
                    return
                with closing(_connect(db_path)) as conn:
                    if status:
                        rows = conn.execute(
                            "SELECT * FROM issues WHERE status = ? ORDER BY id", (status,)
                        ).fetchall()
                    else:
                        rows = conn.execute("SELECT * FROM issues ORDER BY id").fetchall()
                    issues = []
                    for row in rows:
                        cnt = conn.execute(
                            "SELECT COUNT(*) FROM comments WHERE issue_id = ?",
                            (row["id"],),
                        ).fetchone()[0]
                        issues.append(_issue_out(row, comments=cnt))
                self._json(200, {"issues": issues})
                return
            issue_id = self._match_id(path)
            if issue_id is not None:
                issue = self._issue(issue_id)
                if issue is None:
                    self._json(404, {"error": f"задача #{issue_id} не найдена"})
                    return
                with closing(_connect(db_path)) as conn:
                    comments = [
                        {"id": c["id"], "text": c["text"], "created_at": c["created_at"]}
                        for c in conn.execute(
                            "SELECT * FROM comments WHERE issue_id = ? ORDER BY id",
                            (issue["id"],),
                        )
                    ]
                self._json(200, _issue_out(issue, comments=comments))
                return
            self._json(404, {"error": "нет такого адреса"})

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/issues":
                body = self._body()
                if body is None:
                    return
                title = body.get("title")
                if not isinstance(title, str) or not title.strip():
                    self._json(400, {"error": "title — обязательная непустая строка"})
                    return
                description = body.get("description") or ""
                if not isinstance(description, str):
                    self._json(400, {"error": "description — строка"})
                    return
                priority = body.get("priority") or "normal"
                if priority not in PRIORITIES:
                    self._json(400, {
                        "error": f"priority должен быть одним из: {', '.join(PRIORITIES)}"
                    })
                    return
                with closing(_connect(db_path)) as conn, conn:
                    cur = conn.execute(
                        "INSERT INTO issues (title, description, status, priority, created_at)"
                        " VALUES (?, ?, 'open', ?, ?)",
                        (title.strip()[:200], description.strip(), priority, _now()),
                    )
                    row = conn.execute(
                        "SELECT * FROM issues WHERE id = ?", (cur.lastrowid,)
                    ).fetchone()
                self._json(201, _issue_out(row, comments=0))
                return
            issue_id = self._match_id(path, "/comments")
            if issue_id is not None:
                body = self._body()
                if body is None:
                    return
                text = body.get("text")
                if not isinstance(text, str) or not text.strip():
                    self._json(400, {"error": "text — обязательная непустая строка"})
                    return
                with closing(_connect(db_path)) as conn, conn:
                    if conn.execute(
                        "SELECT 1 FROM issues WHERE id = ?", (issue_id,)
                    ).fetchone() is None:
                        self._json(404, {"error": f"задача #{issue_id} не найдена"})
                        return
                    cur = conn.execute(
                        "INSERT INTO comments (issue_id, text, created_at) VALUES (?, ?, ?)",
                        (issue_id, text.strip(), _now()),
                    )
                    comment = conn.execute(
                        "SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)
                    ).fetchone()
                self._json(201, {"id": comment["id"], "issue_id": issue_id,
                                 "text": comment["text"], "created_at": comment["created_at"]})
                return
            self._json(404, {"error": "нет такого адреса"})

        def do_PATCH(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            issue_id = self._match_id(path)
            if issue_id is None:
                self._json(404, {"error": "нет такого адреса"})
                return
            body = self._body()
            if body is None:
                return
            status = body.get("status")
            if status not in STATUSES:
                self._json(400, {
                    "error": f"status должен быть одним из: {', '.join(STATUSES)}"
                })
                return
            with closing(_connect(db_path)) as conn, conn:
                if conn.execute(
                    "SELECT 1 FROM issues WHERE id = ?", (issue_id,)
                ).fetchone() is None:
                    self._json(404, {"error": f"задача #{issue_id} не найдена"})
                    return
                conn.execute(
                    "UPDATE issues SET status = ? WHERE id = ?", (status, issue_id)
                )
                row = conn.execute(
                    "SELECT * FROM issues WHERE id = ?", (issue_id,)
                ).fetchone()
            self._json(200, _issue_out(row))

        def _match_id(self, path: str, suffix: str = "") -> int | None:
            prefix, _, tail = path.partition("/issues/")
            if prefix or not tail:
                return None
            if suffix:
                if not tail.endswith(suffix):
                    return None
                tail = tail[: -len(suffix)]
            if not tail.isdigit():
                return None
            return int(tail)

    return TrackerHandler


def start_api(db_path: Path = DEFAULT_DB, host: str = "127.0.0.1", port: int = 0):
    """Поднять API в daemon-потоке; вернуть (httpd, фактический порт)."""
    init_db(db_path)
    httpd = ThreadingHTTPServer((host, port), make_handler(db_path))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="tracker-api", daemon=True).start()
    return httpd, httpd.server_address[1]


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    httpd, port = start_api(port=port)
    print(f"tracker API: http://127.0.0.1:{port} (db {DEFAULT_DB}), Ctrl+C — стоп")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        httpd.shutdown()
