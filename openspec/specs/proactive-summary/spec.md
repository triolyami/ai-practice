# proactive-summary

## Purpose

Delivers scheduler results to the user without a prompt: a server-side
watcher turns fired-job events into assistant messages in a dedicated
«сводка» chat, so the agent periodically outputs a summary on its own.

## Requirements

### Requirement: Scheduler events land in a dedicated chat

The app SHALL run a watcher that periodically drains the scheduler's
event queue through the MCP hub (not by reading the scheduler's storage
directly) and appends each event as an assistant message to a fixed,
known session («сводка»). The session SHALL be created automatically on
the first delivered event. Event-to-message formatting SHALL produce
human-readable Russian text.

#### Scenario: Fired reminder appears as a chat message
- **WHEN** a reminder job fires while the app is running
- **THEN** within one watcher poll interval the «сводка» session
  contains an assistant message describing the fired reminder

#### Scenario: Collector ticks produce periodic summaries
- **WHEN** the seeded collector has run for several intervals
- **THEN** the «сводка» session shows a sequence of summary messages,
  one per collection, without any user input

### Requirement: Event injection never corrupts a live chat turn

The watcher SHALL NOT modify a session while a user turn is in flight;
injections SHALL be serialized against the chat's busy mechanism so a
user message and an injected message can never interleave destructively.
An injection into a session with an open turn SHALL wait or retry rather
than overwrite partial state.

#### Scenario: Injection waits out a busy turn
- **WHEN** an event is due for delivery while the user is mid-conversation
- **THEN** the message lands after the turn completes, intact and ordered

### Requirement: The UI surfaces unread scheduler activity

The frontend SHALL pin the «сводка» session at the top of the chat list,
poll its transcript on an interval, and show an unread indicator when
new scheduler messages have arrived since the user last opened it. When
the «сводка» chat is open, new messages SHALL appear without a manual
refresh.

#### Scenario: Badge appears without interaction
- **WHEN** a scheduler event is delivered while the user sits in another
  chat
- **THEN** the «сводка» entry in the chat list shows an unread indicator
  within one poll interval

#### Scenario: Opening the chat clears the indicator
- **WHEN** the user opens the «сводка» chat
- **THEN** the unread indicator clears and new messages stream in on the
  next polls
