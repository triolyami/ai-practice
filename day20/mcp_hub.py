"""MCP-хаб: по одному живому mcp.Client на запись реестра MCP_SERVERS.

mcp v2 — async-only SDK, а server.py — синхронный ThreadingHTTPServer.
Поэтому daemon-поток владеет asyncio-циклом, а AsyncExitStack внутри него
держит все подключения; синхронные вызовы уходят в цикл через
asyncio.run_coroutine_threadsafe. Сбой одного сервера — строка со статусом
error: ни чат, ни остальные серверы это не затрагивает.
"""
import asyncio
import threading
from contextlib import AsyncExitStack

from mcp import Client, StdioServerParameters

CONNECT_TIMEOUT = 20  # секунд на handshake + list_tools одного сервера
CALL_TIMEOUT = 30     # секунд на один вызов инструмента


def make_client(spec: dict) -> Client:
    """Client для записи реестра. Неизвестный транспорт — ValueError."""
    transport = spec.get("transport")
    if transport == "stdio":
        return Client(StdioServerParameters(
            command=str(spec["command"]),
            args=[str(a) for a in spec.get("args", [])],
            env=spec.get("env"),
            cwd=spec.get("cwd"),
        ))
    if transport == "http":
        return Client(str(spec["url"]))
    raise ValueError(f"неизвестный транспорт: {transport!r}")


def tool_public(tool) -> dict:
    return {
        "name": tool.name,
        "title": tool.title,
        "description": tool.description,
        "input_schema": tool.input_schema or {},
    }


def impl_public(info) -> dict | None:
    if info is None:
        return None
    return {"name": info.name, "version": info.version}


def call_result_public(result) -> dict:
    return {
        "content": [b.model_dump(mode="json", exclude_none=True) for b in result.content],
        "structured_content": result.structured_content,
        "is_error": bool(result.is_error),
    }


def short_error(exc: BaseException) -> str:
    """Читаемая однострочная ошибка; ExceptionGroup раскрывается до первой причины."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    text = str(exc).strip() or type(exc).__name__
    return f"{type(exc).__name__}: {text}"[:400]


class _Entry:
    def __init__(self, spec: dict):
        self.id = str(spec.get("id") or "?")
        self.transport = spec.get("transport")
        self.spec = spec
        self.status = "connecting"
        self.error: str | None = None
        self.server_info: dict | None = None
        self.protocol_version: str | None = None
        self.tools: list[dict] = []
        self.client: Client | None = None

    def public(self) -> dict:
        return {
            "id": self.id,
            "transport": self.transport,
            "status": self.status,
            "server_info": self.server_info,
            "protocol_version": self.protocol_version,
            "error": self.error,
            "tools": list(self.tools),
        }


class MCPHub:
    """Синхронный фасад над asyncio-циклом в daemon-потоке.

    client_factory — точка расширения для офлайн-проверок: туда можно
    передать фабрику, возвращающую in-process Client(MCPServer(...))
    без подпроцессов и сети.
    """

    def __init__(self, registry: list[dict], client_factory=make_client):
        self._factory = client_factory
        self._entries = [_Entry(spec) for spec in registry]
        self._by_id = {e.id: e for e in self._entries}
        self._loop = asyncio.new_event_loop()
        self._stack: AsyncExitStack | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._thread_main, name="mcp-hub", daemon=True)

    def start(self, timeout: float | None = None) -> list[dict]:
        """Запустить поток и дождаться исхода подключения всех записей."""
        self._thread.start()
        budget = timeout if timeout is not None else CONNECT_TIMEOUT * max(1, len(self._entries)) + 10
        self._ready.wait(budget)
        return self.servers()

    def _thread_main(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_all())
        finally:
            self._ready.set()
        self._loop.run_forever()

    async def _connect_all(self) -> None:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        for entry in self._entries:
            try:
                await self._connect_entry(entry)
            except Exception as exc:
                entry.status = "error"
                entry.error = short_error(exc)
            else:
                entry.status = "ok"

    async def _connect_entry(self, entry: _Entry) -> None:
        client = await asyncio.wait_for(
            self._stack.enter_async_context(self._factory(entry.spec)),
            timeout=CONNECT_TIMEOUT,
        )
        result = await asyncio.wait_for(client.list_tools(), timeout=CONNECT_TIMEOUT)
        entry.client = client
        entry.server_info = impl_public(client.server_info)
        entry.protocol_version = client.protocol_version
        entry.tools = [tool_public(t) for t in result.tools]

    # --- синхронный фасад для HTTP-обработчиков ---

    def servers(self) -> list[dict]:
        return [e.public() for e in self._entries]

    def tools(self, server_id: str) -> list[dict] | None:
        entry = self._by_id.get(server_id)
        return None if entry is None else list(entry.tools)

    def call_tool(self, server_id: str, name: str, arguments: dict | None = None) -> dict:
        entry = self._by_id.get(server_id)
        if entry is None:
            raise KeyError(server_id)
        if not any(t["name"] == name for t in entry.tools):
            raise LookupError(name)
        if entry.status != "ok" or entry.client is None:
            raise RuntimeError(f"сервер «{server_id}» не подключён: {entry.error or entry.status}")
        future = asyncio.run_coroutine_threadsafe(
            entry.client.call_tool(name, arguments or {}), self._loop)
        try:
            result = future.result(CALL_TIMEOUT)
        except Exception as exc:
            # сессия могла умереть — честно помечаем строку
            entry.status = "error"
            entry.error = short_error(exc)
            raise
        return call_result_public(result)
