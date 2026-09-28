"""MCP-сервер «tracker» (stdio): инструменты — HTTP-вызовы в tracker API.

При старте поднимает tracker_api.py на 127.0.0.1:<эфемерный порт> в
daemon-потоке этого же процесса и печатает порт в stderr (stdout
зарезервирован под JSON-RPC). Каждый инструмент — urllib-запрос к REST:
«MCP вокруг API» буквально. Ошибки API (4xx/5xx) превращаются в
ToolError → клиент получает is_error с текстом, сессия живёт.
"""
import json
import sys
from pathlib import Path
from typing import Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from tracker_api import PRIORITIES, STATUSES, start_api  # noqa: E402

_httpd, API_PORT = start_api()
print(f"[tracker] REST API внутри процесса: http://127.0.0.1:{API_PORT}", file=sys.stderr, flush=True)

app = MCPServer(name="tracker", version="0.1.0")

STATUS_L = Literal["open", "in_progress", "done"]
PRIORITY_L = Literal["low", "normal", "high"]


def _api(method: str, path: str, payload: dict | None = None):
    url = f"http://127.0.0.1:{API_PORT}{path}"
    req = Request(url, method=method)
    if payload is not None:
        req.data = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode("utf-8")).get("error") or exc.reason
        except Exception:
            msg = exc.reason or str(exc)
        raise ToolError(f"API {exc.code}: {msg}")
    except URLError as exc:
        raise ToolError(f"tracker API недоступен: {exc.reason}")


def _fmt_issue(issue: dict) -> str:
    line = (
        f"#{issue['id']} [{issue['status']}/{issue['priority']}] {issue['title']}"
    )
    if issue.get("description"):
        line += f"\n    {issue['description']}"
    comments = issue.get("comments")
    if isinstance(comments, int):
        line += f"\n    комментариев: {comments}"
    elif isinstance(comments, list) and comments:
        lines = [f"    - {c['text']} ({c['created_at']})" for c in comments]
        line += "\n    комментарии:\n" + "\n".join(lines)
    return line


@app.tool(description="Список задач трекера; status — фильтр, пусто/не задано = все")
def issue_list(status: Optional[STATUS_L] = None) -> str:
    path = "/issues" + ("?" + urlencode({"status": status}) if status else "")
    issues = _api("GET", path)["issues"]
    if not issues:
        return "Задач нет" + (f" со статусом «{status}»" if status else "")
    return f"Задачи ({len(issues)}):\n" + "\n".join(_fmt_issue(i) for i in issues)


@app.tool(description="Одна задача по номеру: поля + комментарии")
def issue_get(id: int) -> str:
    return _fmt_issue(_api("GET", f"/issues/{id}"))


@app.tool(description="Создать задачу; priority: low|normal|high (по умолчанию normal)")
def issue_create(
    title: str,
    description: str = "",
    priority: PRIORITY_L = "normal",
) -> str:
    issue = _api("POST", "/issues", {
        "title": title, "description": description, "priority": priority,
    })
    return f"Создана задача #{issue['id']} [{issue['status']}/{issue['priority']}] {issue['title']}"


@app.tool(description="Сменить статус задачи; status: open|in_progress|done")
def issue_set_status(id: int, status: STATUS_L) -> str:
    issue = _api("PATCH", f"/issues/{id}", {"status": status})
    return f"Задача #{issue['id']}: статус → {issue['status']}"


@app.tool(description="Добавить комментарий к задаче")
def issue_comment(id: int, text: str) -> str:
    comment = _api("POST", f"/issues/{id}/comments", {"text": text})
    return f"Комментарий #{comment['id']} добавлен к задаче #{comment['issue_id']}"


if __name__ == "__main__":
    assert STATUSES == tuple(STATUS_L.__args__) and PRIORITIES == tuple(PRIORITY_L.__args__)
    app.run()  # transport="stdio"
