# Spec Delta

## Purpose

Provides the day-17 "MCP around an API" deliverable: a mock issue
tracker (Яндекс.Трекер-style) backed by SQLite and exposed over HTTP,
adapted by an MCP stdio server into typed tools the agent can call.

## ADDED Requirements

### Requirement: A REST API manages issues with persistent state

The tracker API SHALL expose HTTP endpoints for listing issues
(optionally filtered by status), reading one issue, creating an issue
(`title`, optional `description`, `priority`), changing an issue's
status, and adding comments — persisted in a SQLite file under
`day17/data/`. On first run the API SHALL seed a small set of issues so
listing is non-empty. The API SHALL run on an ephemeral localhost port
inside the MCP server process and be directly reachable (e.g. via curl)
while that process lives.

#### Scenario: Create then list
- **WHEN** an issue is created via `POST /issues`
- **THEN** `GET /issues` contains it with the given title and default or
  given status/priority

#### Scenario: State survives a restart
- **WHEN** the app (and therefore the MCP server process) restarts
- **THEN** previously created issues are still listed

#### Scenario: First run is seeded
- **WHEN** the API starts against an empty database
- **THEN** `GET /issues` returns a non-empty seed set

### Requirement: An MCP stdio server exposes the API as typed tools

The registry SHALL gain a `tracker` entry whose tools are implemented as
HTTP calls into the tracker API (not direct DB access). The tool set
SHALL be: `issue_list` (optional `status` filter), `issue_get` (`id`),
`issue_create` (`title`, optional `description`, `priority`),
`issue_set_status` (`id`, `status`), `issue_comment` (`id`, `text`).
Input schemas SHALL declare types and enums (statuses, priorities) so
parameter descriptions are self-documenting. Tool results SHALL return
the API's data as text content the model can read.

#### Scenario: Discovery shows typed parameters
- **WHEN** `list_tools` runs on the tracker server
- **THEN** `issue_create` shows `title` as a required string and
  `priority` as an enum of the defined levels

#### Scenario: A tool call round-trips through HTTP
- **WHEN** `issue_create` is invoked via MCP
- **THEN** the tracker API receives the corresponding HTTP request and
  the created issue is queryable over REST

### Requirement: API errors surface as honest tool errors

Calls hitting API validation errors (unknown issue id, invalid status or
priority value, missing required field) SHALL return `is_error: true`
with a readable message — the MCP session stays alive.

#### Scenario: Unknown issue id
- **WHEN** `issue_set_status` is called for a non-existent id
- **THEN** the result is `is_error: true` with a "not found" message and
  subsequent calls still succeed

#### Scenario: Invalid enum value rejected
- **WHEN** `issue_create` is called with a priority outside the enum
- **THEN** the result is `is_error: true` naming the allowed values
