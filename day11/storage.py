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
    workspace_id TEXT NOT NULL DEFAULT '',
    layers TEXT,
    stats TEXT,
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
CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    state TEXT,
    covered TEXT,
    updated_at REAL NOT NULL
);
"""


def _loads(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


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
        totals = snapshot.get("totals")
        token_log = snapshot.get("token_log")
        layers = snapshot.get("layers")
        workspace_id = snapshot.get("workspace_id") or session_id
        stats = (
            json.dumps({"totals": totals, "token_log": token_log}, ensure_ascii=False)
            if totals is not None or token_log is not None
            else None
        )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions"
                " (session_id, name, model, system_prompt, default_prompt,"
                "  workspace_id, layers, stats, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    snapshot["name"],
                    snapshot["model"],
                    snapshot["system_prompt"],
                    int(snapshot["default_prompt"]),
                    workspace_id,
                    json.dumps(layers, ensure_ascii=False) if layers is not None else None,
                    stats,
                    time.time(),
                ),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.executemany(
                "INSERT INTO messages (session_id, idx, role, content, meta) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            # private workspace auto-provisioned on save
            conn.execute(
                "INSERT OR IGNORE INTO workspaces (workspace_id, name, state, covered, updated_at)"
                " VALUES (?, '', NULL, NULL, ?)",
                (workspace_id, time.time()),
            )

    def load(self, session_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT name, model, system_prompt, default_prompt,"
                " workspace_id, layers, stats"
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
                entry["meta"] = _loads(meta) or None
                if entry["meta"] is None:
                    entry.pop("meta")
            history.append(entry)

        stats = _loads(row[6]) or {}
        return {
            "name": row[0],
            "model": row[1],
            "system_prompt": row[2],
            "default_prompt": bool(row[3]),
            "workspace_id": row[4] or "",
            "layers": _loads(row[5]),
            "totals": stats.get("totals"),
            "token_log": stats.get("token_log"),
            "history": history,
        }

    def delete(self, session_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    def ensure_workspace(self, workspace_id: str, name: str = "") -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO workspaces (workspace_id, name, state, covered, updated_at)"
                " VALUES (?, ?, NULL, NULL, ?)",
                (workspace_id, name or "", time.time()),
            )
            if name:
                conn.execute(
                    "UPDATE workspaces SET name = ? WHERE workspace_id = ? AND name = ''",
                    (name, workspace_id),
                )

    def save_workspace(self, workspace_id: str, name: str, state, covered) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO workspaces (workspace_id, name, state, covered, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    workspace_id,
                    name or "",
                    json.dumps(state, ensure_ascii=False) if state is not None else None,
                    json.dumps(covered, ensure_ascii=False) if covered is not None else None,
                    time.time(),
                ),
            )

    def load_workspace(self, workspace_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT name, state, covered, updated_at FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        state = _loads(row[1])
        covered = _loads(row[2])
        if not isinstance(covered, dict):
            covered = {}
        covered = {
            str(k): v for k, v in covered.items()
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0
        }
        return {
            "workspace_id": workspace_id,
            "name": row[0] or "",
            "state": state if isinstance(state, dict) else None,
            "covered": covered,
            "updated_at": row[3],
        }

    def list_workspaces(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT w.workspace_id, w.name, w.updated_at, COUNT(s.session_id)"
                " FROM workspaces w"
                " LEFT JOIN sessions s ON s.workspace_id = w.workspace_id"
                " WHERE w.name <> ''"
                " GROUP BY w.workspace_id"
                " ORDER BY w.updated_at DESC",
            ).fetchall()
        return [
            {"id": r[0], "name": r[1], "updated_at": r[2], "chats": r[3]}
            for r in rows
        ]

    def delete_workspace(self, workspace_id: str) -> list[str]:
        with closing(self._connect()) as conn, conn:
            sids = [
                r[0]
                for r in conn.execute(
                    "SELECT session_id FROM sessions WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchall()
            ]
            conn.execute("DELETE FROM workspaces WHERE workspace_id = ?", (workspace_id,))
            conn.execute(
                "UPDATE sessions SET workspace_id = session_id WHERE workspace_id = ?",
                (workspace_id,),
            )
        return sids

    def set_session_workspace(self, session_id: str, workspace_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE sessions SET workspace_id = ? WHERE session_id = ?",
                (workspace_id, session_id),
            )

    def drop_covered(self, workspace_id: str, session_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT covered FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            if row is None:
                return
            covered = _loads(row[0])
            if not isinstance(covered, dict) or session_id not in covered:
                return
            covered.pop(session_id, None)
            conn.execute(
                "UPDATE workspaces SET covered = ?, updated_at = ? WHERE workspace_id = ?",
                (json.dumps(covered, ensure_ascii=False), time.time(), workspace_id),
            )
