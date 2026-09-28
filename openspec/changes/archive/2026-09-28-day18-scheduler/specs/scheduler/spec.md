# Spec Delta

## Purpose

Gives the agent an MCP tool for delayed and periodic work: a persistent
job store inside a stdio MCP server where a ticker executes due jobs —
one-shot reminders and an interval data collector — and where MCP tools
return aggregated results over the collected data.

## ADDED Requirements

### Requirement: Jobs persist in SQLite and execute on schedule

The scheduler server SHALL keep jobs in a SQLite database with a
`next_run` timestamp and a kind — `once` (delayed one-shot, e.g. a
reminder) or `interval` (repeating, e.g. data collection). A background
ticker SHALL execute jobs when they come due: a `once`-job records its
firing and completes; an `interval`-job performs its collection, stores
the datapoint, and reschedules itself. All state SHALL live in the
database file so jobs survive process restarts.

#### Scenario: Reminder fires at its due time
- **WHEN** a `once`-job's `next_run` passes while the server is running
- **THEN** the ticker marks it fired and records an event describing it

#### Scenario: Interval job keeps rescheduling
- **WHEN** an `interval`-job's `next_run` passes
- **THEN** it stores a new datapoint and its `next_run` advances by its
  interval instead of completing

#### Scenario: Overdue jobs catch up on boot
- **WHEN** the scheduler process starts and a `once`-job's `next_run` is
  already in the past
- **THEN** the job fires immediately rather than being dropped

### Requirement: An interval collector is seeded out of the box

On first boot with an empty job store the scheduler SHALL register one
default `interval` job that periodically stores a real datapoint (metric
name + numeric value + timestamp) into the database, so periodic
collection demonstrably runs without any user action.

#### Scenario: Datapoints accumulate while idle
- **WHEN** the app has been running longer than the collector interval
  with no user interaction
- **THEN** the database contains multiple timestamped datapoints from
  the seeded collector

### Requirement: MCP tools manage jobs and return aggregates

The scheduler SHALL expose MCP tools to: create a delayed reminder
(with a text and a delay), list jobs with their status (pending/fired/
interval), cancel a pending job, and return an aggregated summary over
a time window (per-metric count/min/max/avg plus reminders fired in the
window). The summary SHALL be computed from stored data, not fabricated.

#### Scenario: Model schedules a reminder through the agent
- **WHEN** a user asks the chat for a reminder at a future delay and
  tools are enabled
- **THEN** the model calls the reminder tool and a `once`-job with that
  text and due time exists in the store

#### Scenario: Summary aggregates stored datapoints
- **WHEN** the summary tool is called after the collector has stored
  several datapoints
- **THEN** the result reports their count and aggregate statistics over
  the requested window, matching what is stored

#### Scenario: Cancel prevents firing
- **WHEN** a pending job is cancelled before its `next_run`
- **THEN** the ticker never executes it and listings show it as cancelled

### Requirement: Fired jobs produce a drainable event queue

When a job executes, the scheduler SHALL append an event describing the
outcome (reminder text, or a collected datapoint digest) to a persistent
queue. A dedicated MCP tool SHALL return all pending events and mark
them delivered, so a poller sees each event exactly once and events
survive a restart of either side.

#### Scenario: Events survive until drained
- **WHEN** jobs fire while nobody polls the queue
- **THEN** the next drain returns every undelivered event in order and a
  second drain returns none

#### Scenario: Pending events survive a scheduler restart
- **WHEN** the scheduler process restarts between a job firing and the
  next drain
- **THEN** the event is still delivered afterwards
