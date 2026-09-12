import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    default_prompt INTEGER NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT,
    PRIMARY KEY (session_id, idx)
);
"""


class ChatStore:
    def __init__(self, path: Path):
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=5)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def save(self, session_id: str, snapshot: dict) -> None:
        rows = []
        for idx, message in enumerate(snapshot["history"]):
            meta = message.get("meta")
            rows.append((
                session_id,
                idx,
                message["role"],
                message["content"],
                json.dumps(meta, ensure_ascii=False) if meta is not None else None,
            ))
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions"
                " (session_id, name, model, system_prompt, default_prompt, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    snapshot["name"],
                    snapshot["model"],
                    snapshot["system_prompt"],
                    int(snapshot["default_prompt"]),
                    time.time(),
                ),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.executemany(
                "INSERT INTO messages (session_id, idx, role, content, meta) VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def load(self, session_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT name, model, system_prompt, default_prompt"
                " FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            raw_messages = conn.execute(
                "SELECT role, content, meta FROM messages WHERE session_id = ? ORDER BY idx",
                (session_id,),
            ).fetchall()
        history = []
        for role, content, meta in raw_messages:
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            entry = {"role": role, "content": content}
            if meta:
                try:
                    entry["meta"] = json.loads(meta)
                except json.JSONDecodeError:
                    pass
            history.append(entry)
        return {
            "name": row[0],
            "model": row[1],
            "system_prompt": row[2],
            "default_prompt": bool(row[3]),
            "history": history,
        }

    def delete(self, session_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
