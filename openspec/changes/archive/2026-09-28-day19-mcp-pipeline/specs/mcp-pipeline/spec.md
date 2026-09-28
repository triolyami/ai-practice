# Spec Delta

## Purpose

Composes several isolated MCP tools into an automatic `search →
summarize → save_to_file` pipeline. Composition is host-side: the model
can drive the chain inside a chat turn, or deterministic app code can
drive it over real MCP calls — with a per-run check that data passed
between tools intact, plus a composite meta-tool as a control that shows
what is NOT composition.

## ADDED Requirements

### Requirement: Fetch/process/save stages are exposed as isolated MCP tools

A `pipeline` MCP server SHALL expose at least `search`, `summarize`, and
`save_to_file` as independent tools with typed input schemas, each
callable standalone through the hub (and therefore through
`POST /api/mcp/call` and the tools panel). `search` SHALL return matched
text chunks from a committed local corpus — deterministic, no network.
`save_to_file` SHALL write its `text` argument to a file under the app's
output directory, sanitize the requested file name, and return the
written path and byte count.

#### Scenario: Search returns real corpus hits
- **WHEN** `search` is called with a query present in the corpus
- **THEN** it returns text containing the matching chunks, not a stub

#### Scenario: Save writes and reports honestly
- **WHEN** `save_to_file` is called with `{name, text}`
- **THEN** a file with that text exists under the output directory and
  the result reports the actual path and byte count

#### Scenario: Hostile file name is contained
- **WHEN** `save_to_file` receives a `name` containing path separators or
  parent-directory traversal
- **THEN** the name is sanitized so the write stays inside the output
  directory

### Requirement: Summarize works with or without an LLM key

`summarize` SHALL reduce its `text` argument to a shorter digest. When an
LLM key is configured it SHALL produce the digest via the model — an MCP
tool that internally calls an LLM. When no key is configured it SHALL
fall back to a deterministic extractive summary (e.g. leading
sentences), so the pipeline still runs fully offline.

#### Scenario: Offline fallback keeps the pipeline alive
- **WHEN** `summarize` is called while no LLM key is configured
- **THEN** it returns a deterministic extract of the input instead of an
  error, and the rest of the pipeline can proceed

#### Scenario: Model mode is distinguishable
- **WHEN** `summarize` runs with a configured key
- **THEN** its output reflects the model's digest of the input rather
  than a verbatim prefix

### Requirement: A composite tool runs the whole chain inside one call

The same server SHALL expose a `run_pipeline` tool that performs
search → summarize → save internally in a single tool call and returns
the final artifact plus a per-stage digest. From the client's view the
call SHALL contain no inter-tool data hops — this is the control lane
showing what does NOT count as MCP composition.

#### Scenario: One call, no visible hops
- **WHEN** `run_pipeline` is invoked via `POST /api/mcp/call`
- **THEN** exactly one tool call occurs, the file is written, and the
  result carries a digest of each internal stage

### Requirement: App code can orchestrate the chain over real MCP calls

`POST /api/pipeline {query, name?}` SHALL execute
search → summarize → save_to_file as three sequential hub calls,
streaming one NDJSON `stage` event per hop carrying that stage's tool,
input, and output, followed by a `done` event with the overall verdict.
Each stage's arguments SHALL be built from the previous stage's returned
output verbatim — no model participates in the orchestration.

#### Scenario: One request runs the whole chain
- **WHEN** `POST /api/pipeline` is called with a query
- **THEN** three `stage` events stream in order, the file is written by
  the last stage, and `done` reports success

#### Scenario: A failing stage stops the chain honestly
- **WHEN** a stage's tool call returns an error
- **THEN** no later stage runs, its `stage` event carries the error, and
  `done` reports failure at that stage

#### Scenario: Dead server surfaces as a stage error
- **WHEN** the pipeline MCP server is down
- **THEN** the first `stage` event carries the failure and `done`
  reports it instead of hanging or fabricating output

### Requirement: The model can drive the same chain inside a chat turn

With the session's tools toggle on, a single pipeline-phrased user
message SHALL be sufficient for the model to emit sequential tool calls
for the three pipeline tools within the existing tool-call round cap —
no per-step user hand-holding. The turn's persisted `meta.tool_calls`
trace SHALL contain the ordered calls so the chain can be inspected
after the fact.

#### Scenario: Prompt triggers the full chain
- **WHEN** the user sends a message asking to search, summarize and save
  a topic and tools are enabled
- **THEN** the trace records the three tool calls in order and the
  answer confirms the saved file

#### Scenario: Tools off means no chain
- **WHEN** the same message is sent with tools disabled
- **THEN** no tool calls occur and the answer does not claim a file was
  saved

### Requirement: Data-passing fidelity is measured and reported per run

For every pipeline run the app SHALL compare, at each hop, the hash of
what the previous stage emitted with the hash of what the next stage
actually received, and SHALL surface a per-run verdict: `exact`,
`differs`, or `not-applicable`. The code-orchestrated lane SHALL always
produce `exact`; the model-orchestrated lane's verdict SHALL be computed
from the persisted call trace (recorded arguments vs recorded result
hash); the composite lane SHALL report `not-applicable` since no data
crosses a tool boundary. The UI SHALL render the verdict as a badge on
the run.

#### Scenario: Code lane is byte-exact
- **WHEN** a `POST /api/pipeline` run completes
- **THEN** its verdict is `exact` — each next-stage input hashed
  identically to the previous stage's output

#### Scenario: Model lane verdict reflects reality
- **WHEN** a chat-driven chain completes
- **THEN** the verdict compares the trace's recorded `summarize`/`save`
  arguments against the previous stages' recorded result hashes and
  reports `exact` or `differs` accordingly

#### Scenario: Composite lane is a control
- **WHEN** the composite `run_pipeline` runs
- **THEN** its verdict is `not-applicable` and the UI explains that no
  inter-tool hops exist to check
