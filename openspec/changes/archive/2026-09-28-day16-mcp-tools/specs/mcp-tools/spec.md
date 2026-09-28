# Spec Delta

## Purpose

Lets the day16 app act as an MCP host: connect to configured MCP servers
(stdio and Streamable HTTP), keep those sessions alive, expose the
discovered tool list and manual tool calls through API, web UI, and a
standalone CLI — with each server's failure isolated from the chat.

## ADDED Requirements

### Requirement: MCP servers are configured via a registry

The app SHALL read a `MCP_SERVERS` registry (config) describing each
server as `{id, transport, ...}` where transport is `stdio` (spawned
subprocess command + args + env) or `http` (Streamable HTTP URL). The
registry SHALL ship with two own servers out of the box: a Python
`MCPServer` over stdio and a TypeScript server over stdio, so the tool
list demonstrates language-agnostic interop. A registry entry with an
unknown transport SHALL appear as an error-status row, not crash the app.

#### Scenario: Two servers in one registry

- **WHEN** the app starts with the default registry
- **THEN** both the Python and the TypeScript server are listed, each
  attributed by its own id and transport

#### Scenario: Unknown transport degrades to a row

- **WHEN** a registry entry uses an unsupported transport value
- **THEN** that server's row shows an error status and the rest of the
  registry still connects

### Requirement: Connections open at startup and stay alive

The app SHALL establish the MCP session (initialize handshake) for each
registry entry when the server starts, reuse that session for listing
and calls, and report each server's negotiated `protocol_version` and
`server_info`. The handshake result SHALL be observable in the startup
log and via `GET /api/mcp`.

#### Scenario: Startup log proves the connection

- **WHEN** `server.py` starts with a reachable registry entry
- **THEN** the log shows the server id, negotiated protocol version, and
  discovered tool count

#### Scenario: Restart reconnects

- **WHEN** the app server is restarted
- **THEN** MCP sessions are re-established and `GET /api/mcp` reports the
  same tool list again

### Requirement: Tool discovery is exposed via API, UI, and CLI

`GET /api/mcp` SHALL return per-server `{id, transport, status,
server_info, protocol_version, error?, tools[]}` where each tool carries
`name`, optional `title`, `description`, and `input_schema`. The web UI
SHALL render a tools panel grouping tools by server with status and
expandable schemas. A standalone CLI (`mcp_probe.py`) SHALL connect to
the registry servers and print the tool list without needing the web
app running.

#### Scenario: CLI prints the tool list

- **WHEN** `mcp_probe.py` runs against the default registry
- **THEN** it prints each server's name, protocol version, and every
  tool's name and description

#### Scenario: Identical shape across languages

- **WHEN** `GET /api/mcp` returns tools from both the Python and the
  TypeScript server
- **THEN** both lists present the same fields (name/description/
  input_schema) with the server id as the only provenance difference

### Requirement: Manual tool calls round-trip through MCP

`POST /api/mcp/call` with `{server, tool, arguments}` SHALL invoke the
tool on the named server and return the result content blocks plus the
`is_error` flag. The tools panel SHALL offer a per-tool «вызвать» form
built from the tool's `input_schema` and show the returned result (or
error). An unknown server or tool SHALL produce a 400/404, not a crash.

#### Scenario: Call returns real output

- **WHEN** a tool is invoked from the UI (or API) with valid arguments
- **THEN** the response shows the tool's returned content and
  `is_error: false`

#### Scenario: Tool-level error surfaces honestly

- **WHEN** a call fails inside the tool (e.g. bad arguments, tool raises)
- **THEN** the API returns the error content / `is_error: true` and the
  panel displays it, without breaking the server session

### Requirement: MCP failures are isolated from the chat

A registry entry that fails to connect, dies mid-session, or is missing
its runtime (e.g. no `node`) SHALL be reported as an error-status row in
API and UI; the chat and all other servers SHALL keep working. Chat
requests SHALL NOT be blocked or delayed by MCP connection state.

#### Scenario: Dead server does not kill the chat

- **WHEN** one registry entry's process dies or its command is missing
- **THEN** `GET /api/mcp` shows that server in error status, the other
  server still lists and calls tools, and `/api/chat` answers normally

#### Scenario: Missing npm install degrades to a hint

- **WHEN** the TypeScript server entry is configured but its
  `node_modules` were never installed
- **THEN** that server shows a readable error status while the Python
  server and the chat remain fully functional

### Requirement: MCP tools stay out of the model request

Tool definitions SHALL NOT be injected into the LLM request and the
model SHALL NOT be able to emit tool calls; the token accounting
(breakdown/totals/context preview) SHALL remain exactly as in the base
agent. The only MCP surface is the tools panel, `/api/mcp*` endpoints,
and the CLI probe.

#### Scenario: Request composition unchanged

- **WHEN** a chat message is sent while MCP servers are connected
- **THEN** the request contains only system + history + user message —
  no tools list, schemas, or tool instructions

#### Scenario: Tool output never enters history

- **WHEN** a tool is called manually from the panel
- **THEN** nothing is appended to the chat history or token log
