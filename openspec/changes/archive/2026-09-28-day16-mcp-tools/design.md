# Design

## Context

`day16/` is forked from `day14/` with all invariant machinery removed —
the remaining skeleton is the repo's clean agent: `Agent` (history +
streaming + token meta), SQLite persistence, `tokens.py`, React chat UI.
Onto that base we add an MCP client capability. Hard constraints: the
Python `mcp` SDK is async-only, while `server.py` is a synchronous
`ThreadingHTTPServer`; and the task only asks to connect + list tools —
no LLM tool-calling. See proposal.md for the task text and scope.

## Goals / Non-Goals

**Goals:**
- One long-lived MCP session per registry entry, established at server
  startup; tool discovery and manual calls on top of it.
- The comparison the task hosts: identical tool-list shape from a
  Python and a TypeScript server — server language is invisible to the
  client.
- `mcp_probe.py` as the literal deliverable (connect → print tools)
  independent of the web app.
- Failure isolation: a dead/misconfigured MCP server is a status row,
  never a chat outage.

**Non-Goals:**
- No `tools`/`tool_calls` in LLM requests — the model does not use MCP
  tools (next task's scope). No tool schemas in the context, so token
  accounting is untouched.
- No MCP resources/prompts/sampling — tools only.
- No auth/OAuth, no remote public servers — local variant only.
- No reconnect/retry machinery beyond startup — a dead server stays an
  error row until restart (acceptable for a demo fixture).

## Decisions

### 1. Client SDK: `mcp` v2 pinned `>=2.2,<3`

`pip install mcp` now resolves to **2.2.0** — the v2 line is the current
stable (reworked for the 2026-07-28 spec, py3.14 supported). API:
`from mcp import Client`, `Client(url | StdioServerParameters |
MCPServer-instance | transport)`, `await client.list_tools()`,
`await client.call_tool(name, args)`; server side is
`mcp.server.MCPServer` + `@mcp.tool()`.

- Rejected: pinning v1 (`mcp<2`) — stale API, only critical fixes, and
  all its `FastMCP`/`ClientSession` tutorials are now misleading.
- Rejected: hand-rolled JSON-RPC over stdio — the task says to install
  the SDK; also reimplementing initialize-notifications/tool-call
  plumbing buys nothing.
- Pin `<3`: v2 is young and still moving; v1→v2 was a breaking rework.

### 2. Async→sync bridge: one daemon thread owns the event loop

`server.py` stays sync stdlib. `mcp_hub.py` starts a daemon thread at
import/startup running `asyncio` with an `AsyncExitStack` holding one
`Client` per registry entry; HTTP handlers call sync wrappers built on
`asyncio.run_coroutine_threadsafe`.

- Rejected: `asyncio.run()` per call — would respawn the stdio
  subprocess and redo the handshake on every request; also defeats the
  task's "the connection is established" premise.
- Rejected: rewriting server.py on starlette/uvicorn — abandons the
  repo's stdlib convention for no task-related gain.
- Consequence: all MCP traffic funnels through one loop thread. Calls
  are serialized per server — fine for a demo; noted as a limit.

### 3. Two own servers, both over stdio

- `day16/tools_server.py` — Python `MCPServer`, spawned by the hub with
  `StdioServerParameters(command=sys.executable, args=[…/tools_server.py])`.
  `sys.executable` guarantees the subprocess gets the venv interpreter
  (where `mcp` is installed), not system python.
- `day16/ts-tools/` — TypeScript server on
  `@modelcontextprotocol/sdk` pinned **1.30.0** (1.30.1 is 4 days old —
  inside the repo's 7-day freshness rule), run via `tsx` (devDep; more
  reliable than Node 22.14's `--experimental-strip-types`), spawned as a
  stdio subprocess. Its `package.json`/`node_modules` live inside
  `day16/ts-tools/` and are gitignored.
- Rejected: `npx @modelcontextprotocol/server-everything` as the
  shipped entry — needs a runtime npm fetch for what is only a demo
  fixture; the registry can host it as an extra entry for anyone who
  wants third-party interop.
- Rejected: TS-only (the user's question was "isn't TS best?") — the
  protocol makes server language invisible; keeping the Python entry
  gives the comparison AND a zero-npm fallback if `npm install` flakes.

### 4. stdio as the shipped transport; HTTP supported in the hub

stdio = zero extra ports/processes, the classic local MCP pattern, and
the child dies with the parent. The hub's transport layer also accepts
`{transport: "http", url}` entries via `streamable_http_client` — e.g.
the same `tools_server.py` run with `mcp run … --transport
streamable-http` on :7874 becomes a third registry row comparing
transports without new code. Default registry ships stdio only (no
dangling port).

### 5. Demo tools: small, deterministic, and schema-varied

Each server exposes ~4 tools chosen to exercise argument types:
`server_time` (no args → string), `add` (two numbers), `echo`
(string arg), `notes_list`/`notes_add` (tiny in-memory store — makes
is_error and repeated calls visible). The TS server mirrors the same
spirit so the two tool lists look comparable. Russian descriptions —
user-facing strings convention.

### 6. Failure isolation and honest degradation

The hub connects entries independently at startup (per-entry try/catch →
status row with error text), validates server/tool names on
`/api/mcp/call` (unknown → 400/404), and converts tool-level failures to
`is_error: true` content — per spec. Missing TS `node_modules`/node →
that row is an error, everything else works.

### 7. In-process client for offline checks

`Client(MCPServer_instance)` connects in-process — `offline_check.py`
builds the hub against a fixture server with no subprocess, no node, no
network, matching the repo's fake-client testing convention.

### 8. Ports/keys convention

Server **7873**, Vite dev **5185**, localStorage `day16-*-v1`, DB
`day16/data/chat_history.db` — continuing the day11→7870/5182 …
day14→7872/5184 sequence. (No day15 exists; numbering follows the
homework number per user instruction.)

## Risks / Trade-offs

- **mcp v2 is young** (2.2.0, Sept 2026) → pin `<3`, keep usage to the
  documented `Client` surface, wrap construction defensively so API drift
  surfaces as a readable error row, not a boot crash.
- **Proxy env vars** (`all_proxy=socks5h://…`) break httpx-based HTTP
  transport → same `env -u all_proxy -u ALL_PROXY` launch note as other
  days; stdio is unaffected (pipes), so the default path is safe.
- **Stdio channel discipline**: anything the MCP server prints to stdout
  corrupts JSON-RPC → servers log to stderr only; noted in code layout.
- **npm at demo time** → the TS entry is the graceful-degradation proof
  (error row) while the Python server carries the deliverable; README
  documents `npm install` for `day16/ts-tools/`.
- **One loop thread serializes MCP calls** → irrelevant at homework
  scale; a manual call latency is dominated by the tool anyway.

## Migration Plan

None — new self-contained folder. `requirements.txt` gains `mcp>=2.2,<3`;
`day16/ts-tools/` needs one `npm install` (documented, optional for the
Python-only path).
