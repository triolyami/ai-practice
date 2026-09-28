# Spec Delta

## MODIFIED Requirements

### Requirement: MCP servers are configured via a registry

The app SHALL read a `MCP_SERVERS` registry (config) describing each
server as `{id, transport, ...}` where transport is `stdio` (spawned
subprocess command + args + env) or `http` (Streamable HTTP URL). The
registry SHALL ship with four own servers out of the box: a Python
`MCPServer` over stdio, a TypeScript server over stdio (the
language-agnostic interop pair), the tracker server adapting the
mock issue-tracker REST API (see `tracker-api`), and the scheduler
server for delayed/periodic jobs (see `scheduler`). A registry entry
with an unknown transport SHALL appear as an error-status row, not
crash the app.

#### Scenario: Two servers in one registry
- **WHEN** the app starts with the default registry
- **THEN** both the Python and the TypeScript server are listed, each
  attributed by its own id and transport

#### Scenario: API-backed server joins the registry
- **WHEN** the app starts with the default registry
- **THEN** the tracker server is listed alongside the demo pair, and its
  tools (`issue_list`, `issue_create`, …) appear under its own id

#### Scenario: Scheduler server joins the registry
- **WHEN** the app starts with the default registry
- **THEN** the scheduler server is listed alongside the others, and its
  tools (`remind`, `summary`, …) appear under its own id

#### Scenario: Unknown transport degrades to a row
- **WHEN** a registry entry uses an unsupported transport value
- **THEN** that server's row shows an error status and the rest of the
  registry still connects
