# Proposal

## Why

Day 17 task (verbatim):

> День 17. Первый инструмент MCP
>
> Реализуйте свой MCP-сервер вокруг любого API (например: Яндекс.Трекер,
> Git, CRM, mock API)
>
> Сделайте:
>
> 👉 регистрацию инструмента
> 👉 описание входных параметров
> 👉 возврат результата
>
> Подключите инструмент к своему агенту и:
>
> 👉 вызовите его из приложения
> 👉 получите и используйте результат
>
> Результат:
>
> Агент делает вызов к MCP-инструменту и получает результат

Day 16 already built the MCP host side (registry, hub, two demo servers,
tool discovery, manual calls) but as an explicit non-goal: the model never
sees tools, and the demo tools wrap nothing external. Day 17 closes both
gaps: a new MCP server that adapts a real API boundary, and an agent that
actually calls MCP tools and uses the results in its answers.

Decisions taken with the user during exploration: the wrapped API is a
**mock issue tracker** (REST + SQLite, matching the task's Яндекс.Трекер/
CRM examples — chosen over git-over-CLI and live open-meteo); the agent
sees **all** connected registry servers, not just the new one; the
tool-call exchange persists **meta-only** (trace on the assistant message,
not tool-role history rows).

## What Changes

- New `day17/` app forked from `day16/` — same chat skeleton (Agent,
  session registry, SQLite, busy-lock, tokens.py, React UI, MCP hub,
  py-tools/ts-tools demo servers). Nothing removed; the delta is additive.
- **New capability: `tracker-api`** — a mock issue tracker:
  - `tracker_api.py` — stdlib REST service (ThreadingHTTPServer on an
    ephemeral localhost port, SQLite file under `day17/data/`), CRUD +
    comments on issues, seed data on first run. Runs as a daemon thread
    *inside* the MCP server process, so "MCP around an API" is literally
    an HTTP boundary.
  - `tracker_server.py` — MCP server (stdio, mcp v2): five tools
    (`issue_list`, `issue_get`, `issue_create`, `issue_set_status`,
    `issue_comment`) with typed input schemas (enums for status/priority),
    each implemented as an HTTP call into the tracker API.
  - `MCP_SERVERS` gains a `tracker` stdio entry; py-tools and ts-tools
    stay.
- **New capability: `agent-tool-calling`** — the agent loop:
  - `Agent` gains `tools` (OpenAI-format specs built once at server start
    from every ok registry server, namespaced `srv__tool`) and an injected
    `tool_call` callable; `config.tools` toggles per chat (default on).
  - Streaming requests carry `tools=`; `delta.tool_calls` fragments are
    accumulated by index, args JSON parsed at `finish_reason ==
    "tool_calls"`, executed via `HUB.call_tool`, and `assistant.tool_calls`
    + `tool` messages are appended for the next hop. `MAX_TOOL_ROUNDS`
    caps the loop; exhaustion forces a final tool-less call.
  - Tool errors (`is_error`, bad args JSON, unknown tool) go back to the
    model as tool-message text — the turn never dies on a tool failure.
  - NDJSON gains `tool_call`/`tool_result` events; the tool trace lands in
    `meta.tool_calls` of the assistant message (persists through the
    existing meta-in-history mechanism — no storage schema change for
    messages).
  - Frontend renders calls as expandable phases on the answer card
    (day12-pipeline style), shows «N вызовов» in meta, adds an
    «инструменты» toggle in settings.
- **`tool_probe.py`** — standalone probe: for each configured model, a
  trivial tool + a forcing prompt, streamed and not; prints whether real
  `tool_calls` arrive. Establishes which models get the feature.
- **Modified capability: `mcp-tools`** — the day-16 requirement "MCP tools
  stay out of the model request" is inverted: tool exposure is now a
  per-chat controlled behavior.
- **Built-in comparison axis** (repo convention, inside the task): the
  tools toggle gives an A/B on one question — off → the model guesses
  tracker contents; on → calls the tool and answers with real data.

## Capabilities

### New Capabilities

- `agent-tool-calling`: the LLM request carries discovered MCP tools as
  OpenAI function specs; streamed `tool_calls` are executed through the
  hub in a bounded loop; the exchange streams to the UI and persists as a
  per-answer meta trace; tool failures surface to the model as data.
- `tracker-api`: a mock issue-tracker REST API (SQLite persistence) plus
  an MCP stdio server exposing it as typed tools — the "MCP around an API"
  deliverable.

### Modified Capabilities

- `mcp-tools`: the requirement forbidding tools in the model request
  changes — exposure is now conditional on a per-chat toggle; the registry
  also grows an API-backed server entry.

## Impact

- New folder `day17/` (server **7874**, Vite dev **5186**, committed
  `frontend/dist/`, localStorage `day17-*-v1`); DB files under
  `day17/data/` gitignored (chat history + tracker).
- New files: `tracker_api.py`, `tracker_server.py`, `tool_probe.py`;
  `agent.py`, `server.py`, `config.py`, `storage.py`, frontend
  (`useChat`, `Chat`, `SettingsPanel`, `ToolsPanel`, `MetaLine`) extended;
  `offline_check.py` gains tool-call scenarios.
- Storage: `sessions` gains a `tools` flag column (message table
  unchanged — tool trace rides in `meta`).
- No new dependencies — REST server, HTTP client, and MCP server are all
  stdlib/`mcp`-SDK already present. `mcp>=2.2,<3` unchanged.
- Model risk: tool-call support per provider/model is unverified — the
  probe is the first task; unsupported models keep the toggle but degrade
  to plain chat (or an honest error), documented in README.
- Existing days untouched; day16 keeps working as-is.
