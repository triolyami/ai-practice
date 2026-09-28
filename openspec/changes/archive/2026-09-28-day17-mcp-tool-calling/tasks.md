# Tasks

## 1. Day17 skeleton

- [x] 1.1 Copy `day16/` → `day17/` (excluding `data/`, `server.log`,
  `__pycache__`, `frontend/node_modules`; keep committed `dist/` as
  starting point), bump ports to server **7874** / dev **5186**,
  localStorage keys `day17-*-v1`, rename handler/log strings; verify:
  `env -u all_proxy -u ALL_PROXY .venv/bin/python day17/server.py`
  starts, prints the three-registry line (still py-tools/ts-tools), and
  `day17/offline_check.py` passes unchanged.
- [x] 1.2 In `frontend/vite.config.js` point dev proxy at 7874 and set
  port 5186; verify `npm run build` still succeeds (fresh dist).

## 2. Tool-call capability probe (gates the rest)

- [x] 2.1 Write `day17/tool_probe.py`: for each model in `MODELS`, send
  one trivial tool spec + a forcing prompt («вызови инструмент…»),
  streamed and non-streamed; print a table — model, mode, got
  `tool_calls` y/n, finish_reason, error text. Verify: run it on all
  four models; record results (README gets the table later).
- [x] 2.2 If any model rejects `tools` or never emits calls, add a
  per-model `tools_ok` flag/note in `MODELS`; verify: probe output
  matches the flag for every model.

## 3. Tracker REST API + MCP server

- [x] 3.1 `day17/tracker_api.py`: stdlib `ThreadingHTTPServer` factory on
  `127.0.0.1:0`, SQLite at `day17/data/tracker.db` (WAL, parent dir
  auto-created), seed 4–5 issues when empty; endpoints
  `GET /issues?status=`, `GET /issues/{id}`, `POST /issues`,
  `PATCH /issues/{id}` (status), `POST /issues/{id}/comments`; validation
  errors → 4xx JSON. Verify: start it standalone in a snippet, curl
  list/create/patch/comment roundtrip, restart keeps rows.
- [x] 3.2 `day17/tracker_server.py`: `mcp.server.MCPServer` stdio; on
  start launches the API thread, prints port to stderr; tools
  `issue_list(status?)`, `issue_get(id)`, `issue_create(title,
  description?, priority?)`, `issue_set_status(id, status)`,
  `issue_comment(id, text)` — each a urllib call to the API; 4xx →
  is_error text. Verify: `.venv/bin/python day17/mcp_probe.py` lists
  `tracker` with 5 tools incl. enum schemas; manual call via in-process
  `Client` round-trips through HTTP.
- [x] 3.3 Register `{"id": "tracker", "transport": "stdio", ...}` in
  `config.py` `MCP_SERVERS`. Verify: server start log shows
  `mcp[tracker]` ok; `GET /api/mcp` lists three servers; `POST
  /api/mcp/call` `tracker/issue_list` returns seeded issues.

## 4. Agent tool-calling loop

- [x] 4.1 `agent.py`: `Agent(tools=None, tool_call=None,
  tools_enabled=True)`; `_call_stream` accumulates `delta.tool_calls`
  by index (id/name/arguments fragments); loop in `_run_single` —
  `finish_reason == "tool_calls"` → `tool_call`/`tool_result` events +
  assistant.tool_calls/tool messages → re-request; cap
  `MAX_TOOL_ROUNDS=5` → final tool-less hop; usage summed into meta +
  `meta.tool_calls` trace `[{server, tool, arguments, ok, preview,
  latency_ms}]`; `configure(tools_enabled=…)`. Verify: extended
  `offline_check.py` — fake stream emitting tool_calls chunks → two-hop
  flow, tool result text lands in the second request's `tool` message,
  error/bad-JSON/unknown-tool → error text not exception, cap forces
  answer, tools_enabled=False → single hop with no `tools` kwarg.
- [x] 4.2 History stays user/assistant + meta trace (assert in
  offline_check: after a tool turn, stored history has only those two
  roles and `meta.tool_calls` present on the assistant entry;
  snapshot/from_snapshot keeps the trace). Verify: roundtrip test
  passes.

## 5. Server wiring

- [x] 5.1 `server.py`: after `HUB.start()` build `OPENAI_TOOLS` from ok
  entries — `srv__tool` names, schema sanitizer allowlist; `tool_call`
  adapter (split `__`, `HUB.call_tool`, textify + «Ошибка: » prefix);
  pass into `Agent` ctor both on create and `from_snapshot` path;
  `parse_config` accepts `tools` bool → `configure`. NDJSON emits
  `tool_call`/`tool_result` passthrough. Verify: `curl /api/chat` with a
  tool-forcing message on a probe-verified model returns real tool
  events + answer; `tools:false` → plain single-hop stream.
- [x] 5.2 `storage.py`: `sessions` gains `tools INTEGER` column (default
  1) in SCHEMA + save/load; verify: toggle off → restart → stays off
  (load test in offline_check or curl).

## 6. Frontend

- [x] 6.1 `useChat.js` handles `tool_call`/`tool_result` →
  `msg.toolCalls[]`; `Chat.jsx` renders expandable phases (day12
  `<details>` style) live and from restored `meta.tool_calls`;
  `MetaLine` «инструментов: N». Verify: live UI turn shows phases;
  reload restores them.
- [x] 6.2 `SettingsPanel` «инструменты» checkbox bound to
  `settings.tools` (+ warn note on models flagged by the probe);
  `ToolsPanel` header line «модель видит N инструментов». Verify:
  toggle off → A/B on «какие задачи открыты?» — off guesses, on lists
  the seeded issues; `npm run build` → committed dist.

## 7. Docs + final verification

- [x] 7.1 `day17/README.md`: task text, architecture (REST-in-MCP
  diagram), probe results table per model, demo script («создай задачу»,
  «какие задачи открыты», «сколько 2+2» via py-tools), ports, decisions
  (meta-only trace, namespacing, cap). Verify: doc matches behavior.
- [x] 7.2 Full pass: `offline_check.py` green; live smoke on a
  probe-verified model — seed question answered via `tracker__issue_list`,
  write via `tracker__issue_create` visible in tracker.db; Browser Use
  UI check of the phases; confirm day16 app still runs untouched.
