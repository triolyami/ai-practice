# Spec Delta

## MODIFIED Requirements

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
