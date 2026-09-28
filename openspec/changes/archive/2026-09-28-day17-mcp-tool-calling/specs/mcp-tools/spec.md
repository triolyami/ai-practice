# Spec Delta

## MODIFIED Requirements

### Requirement: MCP servers are configured via a registry

The app SHALL read a `MCP_SERVERS` registry (config) describing each
server as `{id, transport, ...}` where transport is `stdio` (spawned
subprocess command + args + env) or `http` (Streamable HTTP URL). The
registry SHALL ship with three own servers out of the box: a Python
`MCPServer` over stdio, a TypeScript server over stdio (the
language-agnostic interop pair), and the tracker server adapting the
mock issue-tracker REST API (see `tracker-api`). A registry entry with an
unknown transport SHALL appear as an error-status row, not crash the app.

#### Scenario: Two servers in one registry
- **WHEN** the app starts with the default registry
- **THEN** both the Python and the TypeScript server are listed, each
  attributed by its own id and transport

#### Scenario: API-backed server joins the registry
- **WHEN** the app starts with the default registry
- **THEN** the tracker server is listed alongside the demo pair, and its
  tools (`issue_list`, `issue_create`, …) appear under its own id

#### Scenario: Unknown transport degrades to a row
- **WHEN** a registry entry uses an unsupported transport value
- **THEN** that server's row shows an error status and the rest of the
  registry still connects

## REMOVED Requirements

### Requirement: MCP tools stay out of the model request

**Reason**: Day 17 is precisely about the model calling MCP tools —
keeping this requirement would forbid the deliverable.

**Migration**: Superseded by the new per-chat toggle requirement below
and by the `agent-tool-calling` capability. With the toggle off the
day-16 behavior (no tools in the request) is preserved verbatim.

## ADDED Requirements

### Requirement: Tool exposure to the model is a per-chat toggle

Tool definitions SHALL be injected into the LLM request as function specs
(see `agent-tool-calling`) only while the session's tools toggle is on —
the day-17 default. With the toggle off the request SHALL contain no
tools and the model SHALL NOT be able to emit tool calls, exactly as in
day16. The toggle SHALL persist per session. Regardless of the toggle,
the tools panel, `/api/mcp*` endpoints, and the CLI probe SHALL keep
working, and token accounting SHALL keep reporting real usage (tool
specs now legitimately count toward the prompt when enabled).

#### Scenario: Toggle decides exposure
- **WHEN** two chats send the same tool-relevant question, one with the
  toggle on and one off
- **THEN** only the enabled chat's request carries function specs and can
  produce tool calls

#### Scenario: Toggle survives restart
- **WHEN** a session with tools disabled is reloaded after a server
  restart
- **THEN** its next request still carries no tools

#### Scenario: Panel unaffected by toggle
- **WHEN** tools are disabled for a chat
- **THEN** `GET /api/mcp` and manual `POST /api/mcp/call` still list and
  invoke tools normally
