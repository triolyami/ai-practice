# Tasks

## 1. Base: day14 minus invariants

- [x] 1.1 Copy `day14/` → `day16/` (agent.py, config.py, server.py,
  storage.py, tokens.py, offline_check.py, frontend/) and verify the copy
  boots on the old port before changes
- [x] 1.2 Strip invariants from the backend: delete `invariants.py` +
  `invariants/`, remove `invariant`/`enforce` from Agent
  (`configure`, `_request`, `send_stream`, `_run_single` lint/retry loop,
  `snapshot`/`from_snapshot`, `describe`, `context_preview`, `_meta`,
  `_log_turn`), remove `/api/invariant*` endpoints and `config.invariant`/
  `enforce` parsing (keep a `config.invariant → 400` hint like day14 kept
  `config.profile`), drop `sessions.invariant_id`/`enforce` columns.
  Verify: `offline_check.py` passes on the stripped agent (update its
  scenarios — no lint paths remain)
- [x] 1.3 Revert `tokens.py` `breakdown()` to the day8 shape
  (system/history/request) and verify context preview/diagram segments
  carry no `invariants` key
- [x] 1.4 Strip invariant UI from the frontend: composer chip, enforce
  seg in SettingsPanel, InvariantsPanel, badges (отказ/нарушение/
  заблокировано/проверено), blocked-attempts blocks, conflict probes,
  diagram segment. Verify: `npm run build` compiles clean
- [x] 1.5 Renumber conventions: server PORT 7873, dev port 5185, proxy
  target 7873, localStorage `day16-*-v1`, DB `day16/data/`,
  `DAY16_DIR`, titles/labels. Verify: server starts on 7873 and serves
  the rebuilt dist

## 2. MCP SDK + hub

- [x] 2.1 Add `mcp>=2.2,<3` to `requirements.txt`, install into `.venv`,
  verify `from mcp import Client` imports on Python 3.14
- [x] 2.2 `day16/mcp_hub.py`: daemon thread with asyncio loop +
  AsyncExitStack; `MCP_SERVERS` registry in config.py
  (`{id, transport, command|args|env | url}`); connect each entry at
  startup (per-entry try/catch → status), sync facade
  `servers()`/`tools()`/`call_tool(server, name, args)` via
  `run_coroutine_threadsafe`; stderr-only logging. Verify: a scratch
  script against an in-process `Client(MCPServer)` returns
  server_info + tool list

## 3. The two MCP servers

- [x] 3.1 `day16/tools_server.py` — Python `MCPServer` with ~4 demo
  tools (`server_time`, `add`, `echo`, `notes_list`/`notes_add`),
  Russian descriptions, stdio transport, stdout kept clean for
  JSON-RPC. Verify: spawn it and complete a handshake via the hub in a
  scratch check
- [x] 3.2 `day16/ts-tools/` — `package.json` with
  `@modelcontextprotocol/sdk@1.30.0` + `tsx`, `server.ts` mirroring the
  same ~4 tools, registry entry spawning `tsx server.ts`; add
  `day16/ts-tools/node_modules` to gitignore. Verify: `npm install`
  succeeds and the hub lists its tools (if npm unavailable, entry must
  degrade to an error row — verify that instead)

## 4. Server wiring + CLI probe

- [x] 4.1 `GET /api/mcp` returning per-server `{id, transport, status,
  server_info, protocol_version, error, tools[]}`; startup log prints
  per-entry connect result. Verify: curl shows both servers with tools
- [x] 4.2 `POST /api/mcp/call {server, tool, arguments}` → content +
  `is_error`; unknown server → 404, unknown tool → 400, tool failure →
  `is_error: true`. Verify: curl calls `add` on each server and one bad
  call returns the error shape
- [x] 4.3 `day16/mcp_probe.py` — CLI that connects to all registry
  entries and prints server info + tool table. Verify: running it
  standalone prints both servers' tools

## 5. Frontend tools panel

- [x] 5.1 `ToolsPanel` in the right sidebar: per-server row (status dot,
  name/id, transport, protocol version, error text), tool list grouped
  by server with name + description + expandable `input_schema`.
  Verify: panel renders live data from `/api/mcp`
- [x] 5.2 Per-tool «вызвать» — arguments form generated from
  `input_schema` (string/number/boolean inputs), submit →
  `/api/mcp/call`, result/error block under the tool. Verify: call a
  tool in the UI and see its result; call with bad args and see the
  error
- [x] 5.3 `npm run build` → committed `dist/`; verify the app served on
  7873 shows chat + token panel + tools panel together

## 6. Verification

- [x] 6.1 `day16/offline_check.py`: in-process `Client(MCPServer)`
  fixture — hub connect/list/call roundtrip, unknown-server/tool error
  paths, stripped agent keeps token meta + persistence. Verify: all
  scenarios pass without network or node
- [x] 6.2 Live smoke: start server (`env -u all_proxy -u ALL_PROXY`),
  check startup log handshake lines, curl `/api/mcp` + a real call, one
  chat turn confirms token meta unaffected. Verify each step's output
- [x] 6.3 `day16/README.md` — task text, architecture (hub/thread,
  registry, two servers), run instructions incl. `npm install` for
  ts-tools and the Python-only fallback. Verify: instructions reproduce
  the smoke on a fresh checkout path
