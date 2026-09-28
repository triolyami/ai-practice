# Proposal

## Why

Day 16 task (verbatim):

> Установите MCP SDK / клиент (или поднимите MCP-сервер, если используете
> локальный вариант). Сделайте минимальный код, который: устанавливает
> MCP-соединение; получает от MCP список доступных инструментов.
> Проверьте: соединение устанавливается; список инструментов корректно
> возвращается. Результат: код, который подключается к MCP и выводит
> список доступных инструментов.

The graded core is deliberately small — connect, list tools, print them.
Per the course trajectory (agent → memory → personalization → invariants)
MCP is the foundation for tool-using agents; we build it inside the
established day-N playground so the connection and its tool list are
visible and verifiable, not just asserted in a script. The comparison
axis for this task (repo convention): **server language/transport is a
don't-care for the client** — the same `Client.list_tools()` returns
identical shapes from a Python server and a TypeScript server, so both
are wired into one registry to prove it.

## What Changes

- New `day16/` app, forked from `day14/` skeleton: `Agent` + registry +
  SQLite persistence + busy-lock + `tokens.py` + `config.py` + React
  frontend. **Removes**: invariants entirely (`invariants.py`,
  `invariants/`, `/api/invariant*`, `config.invariant`/`config.enforce`,
  the lint/retry/`violation` loop, invariant UI: composer chip, right
  panel, badges, context-diagram segment, `sessions.invariant_id`/
  `enforce` columns). What remains is the clean agent the task needs:
  chat + token tracking (`totals`, `token_log`, `cost_usd`,
  `context_preview`, `est_error_pct`).
- **MCP server registry** in `config.py`: `MCP_SERVERS` list of
  `{id, transport: stdio|http, command|url}` entries — the extensible
  point for future servers.
- **`mcp_hub.py`** — sync facade over the async `mcp` v2 `Client`:
  dedicated daemon thread owns an asyncio loop and one `Client` per
  registry entry (`asyncio.run_coroutine_threadsafe` bridge). Connects at
  server startup, caches server info/capabilities/tool lists, exposes
  `servers()`, `tools()`, `call_tool()`. Per-server failure degrades to a
  status row — it never breaks the chat.
- **Two own MCP servers** (the comparison):
  - `day16/tools_server.py` — Python `MCPServer` (mcp v2), stdio,
    spawned by the hub via `StdioServerParameters` + `sys.executable`.
  - `day16/ts-tools/` — TypeScript server on
    `@modelcontextprotocol/sdk` (pinned 1.30.0; 1.30.1 is <7 days old),
    stdio, spawned via `node`/`tsx`.
  - Both expose a small set of deterministic demo tools (e.g. time,
    arithmetic, note store). Identical tool-list shape from both =
    the interop demonstration.
- **`mcp_probe.py`** — standalone CLI, the literal deliverable:
  connects to the registry servers, prints server info + tool table
  (name / description / schema). Runs without the web app.
- **API**: `GET /api/mcp` → per-server status, `server_info`,
  `protocol_version`, tools with JSON schemas; `POST /api/mcp/call`
  `{server, tool, arguments}` → result content + `is_error` — powers the
  manual «вызвать» button (verification that the list is real, not
  rendered).
- **Frontend**: `day14/` frontend minus invariant UI, plus right-sidebar
  `ToolsPanel` — per-server status dot/name/transport/protocol, tool list
  (name, description, expandable input schema), per-tool «вызвать» with a
  generated arguments form and result block.
- **Non-goal**: the LLM never sees or calls tools — no `tools` param, no
  `tool_calls` loop, nothing injected into the request. That is the next
  task's scope; token tracking therefore stays exactly day8-shaped.

## Capabilities

### New Capabilities

- `mcp-tools`: MCP client connections managed per configured server
  (stdio and streamable-HTTP transports), tool discovery and manual tool
  invocation exposed via API/UI/CLI, with per-server status that degrades
  independently of the chat.

### Modified Capabilities

(none — day16 is a self-contained app; `assistant-invariants` etc. stay
untouched)

## Impact

- New dependency: `mcp` (Python SDK **v2**, pinned `>=2.2,<3`) in
  `requirements.txt`; pulls ~5 small transitive deps (mcp-types,
  jsonschema, pyjwt, sse-starlette, opentelemetry-api). Node deps for the
  TS server are local to `day16/ts-tools/` (`node_modules` gitignored).
- New folder `day16/` (Python stdlib server on port **7873**, Vite dev on
  **5185**, committed `frontend/dist/`); SQLite DB `day16/data/`
  (gitignored); localStorage keys `day16-*-v1`.
- New API surface: `GET /api/mcp`, `POST /api/mcp/call`.
- No changes to existing days; `lab/` untouched.
