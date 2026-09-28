# agent-tool-calling

## Purpose

Lets the chat agent invoke discovered MCP tools mid-turn: the model emits
tool calls, the app executes them through the MCP hub and feeds results
back in a bounded loop, so answers can use real tool output — with the
exchange streamed to the UI and persisted as per-answer metadata.

## Requirements

### Requirement: Discovered MCP tools are offered to the model as function specs

While a session's tools toggle is on, every chat request SHALL carry a
`tools` list built from all registry servers currently in `ok` status.
Each tool SHALL be exposed as an OpenAI function spec whose name is
`{server_id}__{tool_name}` (separator avoids collisions like
`py-tools`/`ts-tools` both exposing `add`), whose description comes from
the MCP tool, and whose `parameters` is the tool's `input_schema` with
non-standard keys (e.g. `$schema`, `title`) stripped. Servers in error
status SHALL contribute no tools. With the toggle off the request SHALL
carry no tools at all.

#### Scenario: Namespaced tools in the request
- **WHEN** a chat message is sent with tools enabled and py-tools,
  ts-tools and tracker are all connected
- **THEN** the model request contains function specs named
  `py-tools__add`, `ts-tools__add`, `tracker__issue_create`, etc.

#### Scenario: Dead server contributes nothing
- **WHEN** one registry entry is in error status
- **THEN** that server's tools are absent from the `tools` list while
  healthy servers' tools remain

#### Scenario: Toggle off sends a plain request
- **WHEN** a chat message is sent with tools disabled
- **THEN** the request contains no `tools` field and no tool-related
  instructions

### Requirement: Tool calls execute through the hub in a bounded loop

When a streamed model response ends with `finish_reason == "tool_calls"`,
the app SHALL parse each call's `id`, namespaced name and JSON arguments
(accumulated from `delta.tool_calls` fragments), execute each via the MCP
hub, append the assistant message with `tool_calls` plus one `tool`
message per call to the working messages, and re-request the model. The
loop SHALL stop at `MAX_TOOL_ROUNDS`; on exhaustion a final request
without `tools` SHALL force a plain-text answer. A turn that emits no
tool calls SHALL behave exactly like the base agent.

#### Scenario: Call → result → answer
- **WHEN** the model replies to «какие задачи открыты?» with a
  `tracker__issue_list` tool call
- **THEN** the tool result is fed back and the final answer reflects the
  real tracker contents

#### Scenario: Loop cap still produces an answer
- **WHEN** the model keeps requesting tool calls past `MAX_TOOL_ROUNDS`
- **THEN** a final tool-less request runs and the turn completes with a
  text answer instead of looping forever

### Requirement: Tool failures reach the model as data

A call that returns `is_error`, raises inside the tool, targets an
unknown tool name, has malformed argument JSON, or hits a dead server
SHALL produce a `tool` message containing a readable error text — not a
turn failure. The model SHALL be able to react (retry, apologize, answer
without the tool).

#### Scenario: Bad arguments become a tool message
- **WHEN** the model calls `tracker__issue_set_status` with an invalid
  status value
- **THEN** the tool message carries the validation error text and the
  model's next answer acknowledges or corrects it

#### Scenario: Dead server mid-turn
- **WHEN** a tool call targets a server that has died since connect
- **THEN** the tool message carries the failure text and the turn
  completes normally

### Requirement: Tool activity is streamed to the UI and rendered

The chat NDJSON stream SHALL emit `tool_call` (qualified name, parsed
arguments) and `tool_result` (ok flag, result preview) events ahead of
the answer deltas that follow them. The frontend SHALL render each call
as an expandable phase on the answer card showing name, arguments, and
result (or error), and the meta line SHALL report the number of tool
calls in the turn.

#### Scenario: Trace visible before the answer finishes
- **WHEN** the model performs two tool calls then answers
- **THEN** the UI shows both call phases as they happen, before `done`

#### Scenario: Manual panel calls still work
- **WHEN** a tool is invoked from the tools panel
- **THEN** `POST /api/mcp/call` behaves exactly as in day16 — independent
  of any chat turn

### Requirement: The tool trace persists as answer metadata only

The assistant message SHALL carry `meta.tool_calls` — a list of
`{name, server, tool, arguments, ok, preview, result_len,
result_sha256, hop_exact, latency_ms}` — persisted through the existing
meta-in-history mechanism and re-rendered on transcript restore.
`result_len`/`result_sha256` SHALL describe the call's full result text
(`preview` remains truncated); they let later checks compare a recorded
result with a later call's recorded arguments without storing the whole
output. `hop_exact` SHALL record, for calls carrying a string `text`
argument after an earlier call in the same turn, whether that argument
hash-matched the previous call's `result_sha256` (true/false, null when
not applicable). LLM-visible history SHALL keep user/assistant roles
only: `tool`-role messages exist only inside the active turn's working
messages and SHALL NOT be stored.

#### Scenario: Reload keeps the trace
- **WHEN** the page reloads after a turn that used tools
- **THEN** the restored answer still shows its tool-call phases from
  `meta.tool_calls`

#### Scenario: Next request stays clean
- **WHEN** the following user message is sent after a tool-using turn
- **THEN** the request's history contains only `user`/`assistant` roles —
  no `tool` messages and no `tool_calls` fields

#### Scenario: Result hash enables fidelity checks
- **WHEN** a turn chains a `search` call into a `summarize` call
- **THEN** hashing `summarize`'s recorded `arguments.text` can be
  compared against `search`'s recorded `result_sha256` to decide whether
  the data passed between the tools intact

### Requirement: Token accounting covers every hop

Each model request in a tool-using turn (initial plus every re-request)
SHALL contribute its usage to the turn's reported `prompt_tokens` /
`completion_tokens` and to cumulative `totals`. The meta SHALL expose the
number of rounds/calls so multi-hop cost is visible.

#### Scenario: Two-hop turn counts twice
- **WHEN** a turn performs one tool call before answering
- **THEN** reported token usage equals the sum of both requests, not only
  the last one
