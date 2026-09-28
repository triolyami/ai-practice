# Spec Delta

## Purpose

Runs long interaction flows where the agent picks tools across several
registered MCP servers in one turn, and checks — programmatically, from
the recorded tool trace — that the right tools were chosen in the right
order.

## ADDED Requirements

### Requirement: Several MCP servers with distinct domains are registered

The app SHALL register at least three stdio MCP servers covering
distinct domains (a document pipeline, an issue tracker, a scheduler)
plus at least one distractor server whose tools semantically overlap
the scenario's needs (e.g. a notes tool next to the issue tracker).
All tools SHALL reach the model under `server__tool` qualified names.

#### Scenario: Registry is up at startup
- **WHEN** the app starts with the default registry
- **THEN** at least four servers report status `ok` and their tools are
  offered to the agent, each prefixed by its server id

#### Scenario: One dead server does not block the rest
- **WHEN** one registry entry fails to connect
- **THEN** the remaining servers still expose their tools and the chat
  keeps working

### Requirement: One message drives a cross-server dependent chain

A canned scenario SHALL exist whose correct execution requires tools
from at least three different servers, where at least one call's
argument must be a previous call's result (data crosses a server
boundary through the model), so the calls cannot be reordered or
batched.

#### Scenario: Long flow completes
- **WHEN** the scenario prompt is sent to the chat with tools enabled
- **THEN** the resulting trace contains at least four successful tool
  calls spanning at least three distinct servers

#### Scenario: Dependent call carries real data
- **WHEN** the scenario chains a producer call to a consumer call that
  takes a `text` argument
- **THEN** the trace's per-call fidelity flag records whether the
  consumer received the producer's output verbatim

### Requirement: Tool-call loop covers long flows

The agent's tool-call loop SHALL allow at least 8 tool rounds per turn
so a dependent five-plus-call chain plus recovery retries completes
without hitting the round cap.

#### Scenario: Five-hop chain does not exhaust the loop
- **WHEN** the scenario needs five sequential dependent tool calls
- **THEN** all five execute and a final answer is still produced

### Requirement: Flow correctness is checked programmatically

The app SHALL provide a checker that evaluates a scenario's recorded
tool trace and reports a pass/fail verdict per criterion: expected
ordered subsequence of `server__tool` calls (order asserted only where
a data dependency forces it), unordered required calls, minimum number
of distinct servers used, and absence of forbidden distractor tools.
The checker SHALL be runnable both offline on a saved trace and against
a live run.

#### Scenario: Correct trace passes
- **WHEN** the checker runs on a trace matching the scenario spec
- **THEN** it reports the scenario as passed with per-criterion detail

#### Scenario: Wrong order or distractor use fails
- **WHEN** the checker runs on a trace where calls are out of order or
  a forbidden distractor tool was used
- **THEN** it reports failure naming the violated criterion
