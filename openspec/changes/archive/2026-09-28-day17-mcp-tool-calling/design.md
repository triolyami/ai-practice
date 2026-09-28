# Design

## Context

`day17/` forks `day16/` unchanged except the additions below — same Agent
(history + streaming + meta/tokens), session registry, `ChatStore`,
`MCPHub` (daemon thread owns an asyncio loop; `call_tool` is a sync
facade over `run_coroutine_threadsafe`), `MCP_SERVERS` registry, NDJSON
chat, React UI. Day16 deliberately kept tools out of the LLM request;
day17 flips exactly that bit. Constraints inherited: Python stdlib-first
servers, `mcp` v2 SDK, OpenAI-compatible providers (Z.ai glm-*,
DeepSeek), `Agent(client=...)` injection pattern for offline checks.
See proposal.md for the task text and the two user-settled scope calls
(all registry servers visible to the agent; meta-only trace).

## Goals / Non-Goals

**Goals:**
- The model can call MCP tools and the answer visibly uses the result —
  the graded core.
- The wrapped API is a real boundary: the MCP server is an HTTP client of
  a REST service, not functions with storage.
- Everything verifiable offline (fake client + fake tool runtime) plus a
  live probe script for provider behavior.
- Day16 surfaces (tools panel, `/api/mcp*`, `mcp_probe.py`) keep working.

**Non-Goals:**
- No `tool`-role rows in stored history — the trace is meta-only.
- No parallel/multi-server fan-out beyond what a single response's
  `tool_calls` list already contains; no MCP resources/prompts/sampling.
- No auth on the tracker API, no reconnect machinery, no remote MCP
  servers.
- No retro-changes to earlier days.

## Decisions

### 1. Tracker API lives inside the MCP server process

`tracker_server.py` (stdio MCP) starts `tracker_api.py`'s
`ThreadingHTTPServer` on `127.0.0.1:0` (OS-assigned port — zero collision
management) in a daemon thread, prints the port to stderr, and implements
each tool as a `urllib` call to `http://127.0.0.1:<port>`. The API owns a
SQLite file (`day17/data/tracker.db`, WAL) and seeds a handful of issues
when empty.

- Why inside the child: the hub spawns the MCP server anyway, so the API
  needs no separate lifecycle; when the stdio parent dies the child (and
  its API thread) dies with it — no orphans. `mcp_probe.py` gets a fully
  working tracker for free.
- Rejected: standalone long-running REST service (who starts it? another
  port to document; breaks probe-only usage); tools touching SQLite
  directly (then nothing is "around an API" — the HTTP hop is what makes
  the task's premise literally true, for ~60 lines of stdlib).

### 2. OpenAI tool specs are built once, from the hub cache, namespaced

At server start (after `HUB.start()`), `server.py` builds
`OPENAI_TOOLS`: for each `ok` registry entry and each of its cached
tools → `{"type": "function", "function": {"name": f"{srv}__{tool}",
"description": ..., "parameters": sanitized(input_schema)}}`.
`srv__tool` uses `__` as separator: OpenAI function names match
`^[a-zA-Z0-9_-]+$` — `-` inside server ids is legal, `__` splits
unambiguously (`tracker__issue_create` vs `py-tools__add`).

- `sanitized()` keeps an allowlist (type/properties/required/items/enum/
  description/default/additionalProperties/numeric+string bounds) and
  drops `$schema`, `title`, and friends — GLM-side parsers have rejected
  non-minimal schema baggage before (day2 `json_schema` lesson).
- Built once, not per request: registry entries connect once at startup
  and only degrade afterward; a server that dies mid-session keeps its
  spec but its calls fail — the failure reaches the model as tool-result
  text (decision 6), which is more informative than silently dropping
  the tool.
- Rejected: exposing only the tracker server (user chose all servers —
  and `py-tools__add`/`ts-tools__add` duplicates are a feature: they show
  namespacing works).

### 3. The agent gets an injected tool runtime, not the hub

`Agent(tools=OPENAI_TOOLS or None, tool_call=callable)` where
`tool_call(qualified_name, args_dict) -> (text, is_error)`. The adapter
in `server.py` splits on the first `__`, calls `HUB.call_tool`, joins the
result's text blocks (falling back to `structured_content` JSON), and
prefixes «Ошибка: » when `is_error`. `tools_enabled` flag (ctor +
`configure`) gates whether `tools=` is passed at all.

- Matches the established `client=` injection: `offline_check.py` gives
  the agent a scripted fake stream emitting `tool_calls` chunks plus a
  fake `tool_call`, with zero MCP/async code in the loop under test.
- Rejected: agent importing `mcp_hub` — couples a sync generator to an
  async facade and makes the fake harness heavy.

### 4. Streaming accumulation, bounded rounds, forced landing

Requests stay streamed (every day since 6 streams). `_call_stream`
additionally accumulates `choice.delta.tool_calls` by `index` — `id`,
`function.name`, `function.arguments` all arrive fragmented across
chunks — and returns them alongside reply/finish/usage. When
`finish_reason == "tool_calls"` the agent yields `tool_call` events,
executes each call via the injected runtime (all calls in one response
run in the same round), yields `tool_result` events, appends
`{role: assistant, content, tool_calls}` + `{role: tool, tool_call_id,
content}` to the working message list, and loops — max
`MAX_TOOL_ROUNDS = 5`. On exhaustion it runs one last request with no
`tools` so the model must produce text.

- Rejected: non-streaming first hop then streaming final answer — the
  deciding call produces zero deltas while thinking (deepseek native
  reasoning), which reads as a hung UI; streaming keeps the kill-switch
  (disconnect → gen.close()) uniform.
- Rejected: unbounded loop — cost/runaway guard; 5 rounds covers any
  realistic demo chain.

### 5. Trace is meta-only; history stays user/assistant

Within a turn the working messages carry the full OpenAI protocol
(assistant `tool_calls` + `tool` messages — required for the next hop).
After `done`, `_commit_turn` stores only `{user, assistant(final text)}`
and the assistant entry's `meta.tool_calls` gets the trace
`[{server, tool, arguments, ok, preview, latency_ms}]`. It persists via
the existing meta-in-history mechanism (day6), so snapshot/storage/
transcript-restore need no message-table changes; `sessions` only gains
a `tools` flag column next to `layers`.

- Rejected: persisting `tool`-role rows — a restored `tool` message is
  protocol-invalid without its preceding `assistant.tool_calls`, so
  `_request`/`from_snapshot`/storage/token-est all grow special cases
  (~3× plumbing) for little demo value; the answer text already carries
  whatever the model used.

### 6. Tool failures are data, not turn failures

`is_error` results, unknown qualified names, malformed argument JSON,
and dead-server exceptions all become the `tool` message's text
(«Ошибка: …»). The model then recovers or apologizes — consistent with
day16's "error row, not exception" philosophy. Only client disconnect
aborts the turn (unchanged).

### 7. Toggle: `config.tools`, default on, persisted

`parse_config` accepts `tools` (bool) → `agent.tools_enabled`; stored in
a new `sessions.tools` column like `layers`. Default **on** — the day's
point is a working call; flipping off gives the built-in A/B («какие
задачи открыты?» guess vs real list) without extra machinery.

### 8. UI surfaces the trace like day12 pipeline steps

`useChat` collects `tool_call`/`tool_result` into the in-flight
message's `toolCalls[]`; `Chat.jsx` renders them as expandable phases
(name + args + result preview, day12 `<details>` style) both live and
from restored `meta.tool_calls`; `MetaLine` adds «инструментов: N»;
`SettingsPanel` gets the «инструменты» checkbox; `ToolsPanel` gains a
line «модель видит N инструментов» tying the day16 panel to the new
feature.

### 9. Probe before plumbing

`tool_probe.py` (standalone, like `mcp_probe.py`) runs first: each model
in `MODELS` × stream/non-stream × one trivial tool with a forcing prompt
→ prints whether `tool_calls` actually arrive. deepseek-v4-flash is a
native-thinking model and reasoning lines historically restrict tools;
glm-4.6 is known-good; the probe decides if any model needs a warning
note (or the toggle hidden) before UI work lands.

## Risks / Trade-offs

- **deepseek-v4-flash may not emit `tool_calls`** (thinking models and
  function calling have a rocky history on DeepSeek) → probe first; if a
  model can't tool-call, its `note` says so and the toggle warns in UI;
  the request still succeeds (just never emits calls) or surfaces the
  provider's 400 honestly.
- **Tool schemas inflate the real prompt** while `breakdown()` estimates
  text only → `est_error_pct` grows on tool-enabled turns; accepted and
  documented (a rough schema-size estimate is a stretch goal).
- **Provider schema strictness** (GLM rejected `json_schema` in day2) →
  sanitization allowlist + probe coverage.
- **A model may call the "wrong" duplicate** (`py-tools__add` vs
  `ts-tools__add`) → harmless; both are equivalent demos.
- **Multi-call responses** → handled natively (all calls of one round
  run before the next hop); no extra work.
- **Tracker API thread crashes** → tools return `is_error` text; MCP
  entry may degrade to error on next restart; chat unaffected (day16
  isolation already proven).

## Migration Plan

New `day17/` folder; no changes to shipped days. `sessions.tools` column
is additive to a fresh DB file (`day17/data/chat_history.db`) — no data
migration. Rollback = don't run day17.

## Open Questions

- Exact per-model tool-call reliability (probe answers it; affects only
  UI hints/README wording, not the design).
- Whether to show raw REST traffic in the UI (nice-to-have; a stderr log
  line per API hit may suffice for the demo).
