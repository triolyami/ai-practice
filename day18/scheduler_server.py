"""MCP-сервер «scheduler» (stdio): отложенные и периодические задачи.

Хранилище — SQLite day18/data/scheduler.db (WAL). Daemon-поток «тикер»
просыпается каждые TICK_S секунд и исполняет должные задачи: once —
помечает fired и кладёт событие, interval — собирает метрики в
datapoints, кладёт событие и переносит next_run. При старте процесса
один проход сразу: просроченные once-задачи срабатывают — catch-up
после рестарта. События копятся в events с delivered=0, пока вотчер
server.py не заберёт их через pop_events: уведомления идут через сам
MCP, хост базу планировщика не открывает.

stdout зарезервирован под JSON-RPC — логи только в stderr.
"""
import json
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from tracker_api import STATUSES  # noqa: E402

DAY18_DIR = Path(__file__).resolve().parent
DB_PATH = DAY18_DIR / "data" / "scheduler.db"
TRACKER_DB = DAY18_DIR / "data" / "tracker.db"

TICK_S = 30                  # период тикера: задачи могут опоздать до TICK_S
COLLECTOR_INTERVAL_S = 120   # сид: сбор метрик каждые ~2 минуты

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- 'once' | 'interval'
    label TEXT NOT NULL,             -- текст напоминания / имя сбора
    next_run REAL NOT NULL,          -- epoch следующего исполнения
    interval_s REAL,                 -- NULL у once
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | fired | cancelled
    fired_at REAL
);
CREATE TABLE IF NOT EXISTS datapoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,              -- 'reminder' | 'collect'
    text TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0
);
"""


def _fmt_ts(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def collect_metrics(tracker_db: Path = TRACKER_DB) -> list[tuple[str, float]]:
    """Снимок метрик: количество задач трекера по статусам; если
    tracker.db нет или не читается — loadavg1 из /proc/loadavg."""
    try:
        if not tracker_db.exists():
            raise FileNotFoundError(tracker_db)
        # mode=ro: подключаемся не создавая файл и не мешая WAL-писателю
        with closing(sqlite3.connect(
            f"file:{tracker_db}?mode=ro", uri=True, timeout=2,
        )) as conn:
            rows = dict(conn.execute(
                "SELECT status, COUNT(*) FROM issues GROUP BY status"
            ).fetchall())
        return [(f"issues.{st}", float(rows.get(st, 0))) for st in STATUSES]
    except (sqlite3.Error, OSError):
        pass
    try:
        with open("/proc/loadavg", encoding="utf-8") as f:
            return [("sys.load1", float(f.read().split()[0]))]
    except (OSError, ValueError, IndexError):
        return [("sys.load1", 0.0)]


class Scheduler:
    """Хранилище задач + исполнение должных. Потоки не поднимает:
    тикер стартует явно через start(); tick() вызывается и вручную
    (офлайн-проверки гоняют его на временной базе)."""

    def __init__(self, db_path: Path, collect=collect_metrics):
        self._db_path = Path(db_path)
        self._collect = collect
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)
            # user_version — метка «сид уже посажен»: иначе отменённый
            # сборщик воскресал бы при каждом рестарте с пустым jobs
            if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                conn.execute("PRAGMA user_version = 1")
                conn.execute(
                    "INSERT INTO jobs (kind, label, next_run, interval_s, status)"
                    " VALUES ('interval', ?, ?, ?, 'pending')",
                    ("метрики трекера", time.time(), COLLECTOR_INTERVAL_S),
                )

    # --- задачи ---

    def add_reminder(self, text: str, in_minutes: float, now: float | None = None) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise ToolError("remind: text — непустая строка")
        if not isinstance(in_minutes, (int, float)) or isinstance(in_minutes, bool) \
                or in_minutes <= 0:
            raise ToolError("remind: in_minutes — положительное число минут")
        due = (now or time.time()) + float(in_minutes) * 60
        with self._lock, closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO jobs (kind, label, next_run, status) VALUES ('once', ?, ?, 'pending')",
                (text.strip()[:500], due),
            )
            job_id = cur.lastrowid
        return {"id": job_id, "next_run": due}

    def list_jobs(self) -> list[dict]:
        with self._lock, closing(self._connect()) as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id, kind, label, next_run, interval_s, status, fired_at"
                " FROM jobs ORDER BY id"
            ).fetchall()]

    def cancel_job(self, job_id: int) -> dict:
        with self._lock, closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                (job_id,),
            )
            if cur.rowcount == 0:
                raise ToolError(f"задача #{job_id} не найдена или уже завершена")
        return {"id": job_id}

    def summary(self, window_min: float, now: float | None = None) -> dict:
        now = now or time.time()
        since = now - float(window_min) * 60
        with self._lock, closing(self._connect()) as conn:
            metrics = [dict(r) for r in conn.execute(
                "SELECT metric, COUNT(*) AS n, MIN(value) AS lo,"
                " MAX(value) AS hi, AVG(value) AS avg"
                " FROM datapoints WHERE ts >= ? GROUP BY metric ORDER BY metric",
                (since,),
            ).fetchall()]
            reminders = [dict(r) for r in conn.execute(
                "SELECT id, label, fired_at FROM jobs"
                " WHERE kind = 'once' AND status = 'fired' AND fired_at >= ?"
                " ORDER BY fired_at",
                (since,),
            ).fetchall()]
        return {"window_min": window_min, "metrics": metrics, "reminders": reminders}

    def pop_events(self) -> list[dict]:
        """Недоставленные события по порядку; прочитанные помечаются delivered."""
        with self._lock, closing(self._connect()) as conn, conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, ts, kind, text FROM events"
                " WHERE delivered = 0 ORDER BY id"
            ).fetchall()]
            if rows:
                conn.execute(
                    f"UPDATE events SET delivered = 1 WHERE id IN"
                    f" ({','.join('?' * len(rows))})",
                    [r["id"] for r in rows],
                )
        return rows

    # --- исполнение ---

    def tick(self, now: float | None = None) -> int:
        """Один проход тикера: исполнить все должные pending-задачи.
        Возвращает число сработавших."""
        now = now or time.time()
        fired = 0
        with self._lock, closing(self._connect()) as conn, conn:
            due = conn.execute(
                "SELECT * FROM jobs WHERE status = 'pending' AND next_run <= ?"
                " ORDER BY next_run, id",
                (now,),
            ).fetchall()
            for job in due:
                fired += 1
                if job["kind"] == "once":
                    conn.execute(
                        "UPDATE jobs SET status = 'fired', fired_at = ? WHERE id = ?",
                        (now, job["id"]),
                    )
                    conn.execute(
                        "INSERT INTO events (ts, kind, text) VALUES (?, 'reminder', ?)",
                        (now, job["label"]),
                    )
                else:
                    # collect вне транзакции делать негде — чтение чужой
                    # базы read-only и быстрое, держим под локом
                    points = self._collect()
                    for metric, value in points:
                        conn.execute(
                            "INSERT INTO datapoints (ts, metric, value) VALUES (?, ?, ?)",
                            (now, metric, value),
                        )
                    digest = " · ".join(f"{m}={v:g}" for m, v in points) or "нет данных"
                    conn.execute(
                        "INSERT INTO events (ts, kind, text) VALUES (?, 'collect', ?)",
                        (now, f"{job['label']}: {digest}"),
                    )
                    # перенос на +interval; пропущенные за простой такты
                    # не догоняем — иначе рестарты дают всплеск старых точек
                    nxt = job["next_run"] + job["interval_s"]
                    while nxt <= now:
                        nxt += job["interval_s"]
                    conn.execute(
                        "UPDATE jobs SET next_run = ?, fired_at = ? WHERE id = ?",
                        (nxt, now, job["id"]),
                    )
        return fired

    def start(self, tick_s: float = TICK_S) -> threading.Thread:
        """Стартовый проход (catch-up просроченного) + daemon-тикер."""
        self.tick()
        thread = threading.Thread(
            target=self._ticker_main, args=(tick_s,),
            name="scheduler-ticker", daemon=True,
        )
        thread.start()
        return thread

    def _ticker_main(self, tick_s: float) -> None:
        while True:
            time.sleep(tick_s)
            try:
                self.tick()
            except Exception as exc:  # тикер живёт всегда — ошибку в stderr
                print(f"[scheduler] тик пропущен: {exc}", file=sys.stderr, flush=True)


SCHED = Scheduler(DB_PATH)

app = MCPServer(name="scheduler", version="0.1.0")


@app.tool(description="Поставить отложенное напоминание: text — что напомнить, in_minutes — через сколько минут сработать")
def remind(text: str, in_minutes: float) -> str:
    job = SCHED.add_reminder(text, in_minutes)
    return (
        f"Напоминание #{job['id']} поставлено: сработает в "
        f"{_fmt_ts(job['next_run'])} (через {in_minutes:g} мин)"
    )


@app.tool(description="Список задач планировщика: id, вид (once/interval), статус, время следующего запуска")
def job_list() -> str:
    jobs = SCHED.list_jobs()
    if not jobs:
        return "Задач нет"
    lines = []
    for j in jobs:
        if j["kind"] == "interval":
            tail = f"каждые {j['interval_s']:g} с, следующий в {_fmt_ts(j['next_run'])}"
        elif j["status"] == "pending":
            tail = f"сработает в {_fmt_ts(j['next_run'])}"
        elif j["status"] == "fired":
            tail = f"сработала в {_fmt_ts(j['fired_at'])}"
        else:
            tail = "отменена"
        lines.append(f"  #{j['id']} [{j['kind']}/{j['status']}] «{j['label']}» — {tail}")
    return f"Задачи планировщика ({len(jobs)}):\n" + "\n".join(lines)


@app.tool(description="Отменить ожидающую задачу планировщика по id")
def job_cancel(id: int) -> str:
    SCHED.cancel_job(int(id))
    return f"Задача #{id} отменена"


@app.tool(description="Сводка собранных данных за последние window_min минут: count/min/max/avg по каждой метрике + сработавшие напоминания")
def summary(window_min: float = 10) -> str:
    data = SCHED.summary(float(window_min))
    lines = [f"Сводка за последние {data['window_min']:g} мин:"]
    if data["metrics"]:
        for m in data["metrics"]:
            lines.append(
                f"  {m['metric']}: точек {m['n']}, min {m['lo']:g}, "
                f"max {m['hi']:g}, avg {m['avg']:.2f}"
            )
    else:
        lines.append("  метрик в окне нет — сборщик ещё не отработал")
    if data["reminders"]:
        lines.append(f"Напоминаний сработало: {len(data['reminders'])}")
        for r in data["reminders"]:
            lines.append(f"  - «{r['label']}» (в {_fmt_ts(r['fired_at'])})")
    else:
        lines.append("напоминаний в окне не было")
    return "\n".join(lines)


@app.tool(description="Системный слив очереди событий планировщика: возвращает недоставленные события и помечает их доставленными")
def pop_events() -> str:
    return json.dumps(SCHED.pop_events(), ensure_ascii=False)


if __name__ == "__main__":
    SCHED.start()
    print(
        f"[scheduler] база {DB_PATH}, тикер каждые {TICK_S} с",
        file=sys.stderr, flush=True,
    )
    app.run()  # transport="stdio"
