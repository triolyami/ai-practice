# Design

## Context

`day18/` forks `day17/` unchanged except the additions below — same
Agent with the tool-calling loop, session registry, `ChatStore`
(snapshot `load`/`save`, WAL SQLite), `MCPHub` (daemon thread owns an
asyncio loop; `call_tool` is a sync facade over
`run_coroutine_threadsafe`), `MCP_SERVERS` registry, NDJSON chat, React
UI with a client-side chat list. Day 17 ends at request/response: the
model can call tools, but nothing reaches the user unprompted. Day 18
adds the missing direction — scheduled work inside an MCP server, and a
delivery path back into a chat. See proposal.md for the task text and
the three user-settled scope calls (in-process ticker; one jobs table
for both task branches; watcher → «сводка» chat for reporting).

## Goals / Non-Goals

**Goals:**
- An MCP tool set that schedules work, persists it in SQLite, executes
  it on time, and returns aggregated results — the graded core.
- Periodic output the user can *see arrive*: scheduler events become
  assistant messages in a dedicated «сводка» chat with an unread badge.
- Everything verifiable offline: ticker, due-job execution, event drain,
  and injection all testable with fake clocks / fake hub calls.
- Day 17 surfaces (tool-calling, tools panel, tracker demo) untouched
  in the copy.

**Non-Goals:**
- No system cron/systemd integration — rejected during exploration.
- No model-generated summaries on a timer (a real agent turn per tick
  spends tokens for no extra demonstrable behavior); summary text is
  deterministic formatting over stored data.
- No SSE/WebSocket push channel — the existing `GET /api/agent` poll is
  enough for the demo cadence.
- No remote/auth'd scheduler, no job results richer than text events,
  no retro-changes to earlier days.

## Decisions

### 1. The clock is a ticker thread inside the scheduler MCP process

`scheduler_server.py` (stdio MCP) owns `day18/data/scheduler.db` and a
daemon thread that wakes every `TICK_S` (~30s), runs due jobs, and
loops — the exact lifecycle pattern day 17 established for
`tracker_api.py` inside `tracker_server.py`: the hub spawns the process
anyway, and the scheduler dies with its parent — no orphans, no external
setup.

- Rejected: **system cron** (`*/2` + collector script). The daemon is
  running on this machine and would work, but on WSL cron dies with the
  distro anyway — same real uptime as the app — while adding an external
  install/cleanup step and making "the MCP tool executes on schedule"
  only indirectly true (the tool would just read what cron wrote).
- Rejected: **ticker in `server.py`**. The schedule then lives in the
  host, not the tool — again weakening the task's premise — and it could
  not be exercised by `mcp_probe.py` standalone.

### 2. One `jobs` table covers both task branches

```sql
jobs(id, kind TEXT,            -- 'once' | 'interval'
     label TEXT,               -- reminder text or metric/job name
     next_run REAL,            -- epoch of next execution
     interval_s REAL,          -- NULL for 'once'
     status TEXT,              -- 'pending' | 'fired' | 'cancelled'
     fired_at REAL)            -- last execution time
datapoints(id, ts REAL, metric TEXT, value REAL)
events(id, ts REAL, kind TEXT, text TEXT, delivered INTEGER)
```

A reminder is a `once`-job; the periodic collector is an `interval`-job
whose execution appends to `datapoints`. One ticker loop serves both —
no second mechanism. On process start, overdue `once`-jobs fire
immediately: restart catch-up is what makes persistence observable
instead of just claimed.

Collector content: snapshot the tracker (`SELECT status, COUNT(*) FROM
issues` on `day18/data/tracker.db` → one datapoint row per status) —
thematic for the day17 base, and the numbers visibly move when the user
creates issues in chat. Fallback when `tracker.db` is absent/unreadable:
`/proc/loadavg` load1 — always real, zero coupling either way.

### 3. Delivery is pull-through-MCP, injection is host-side

Execution stays in the MCP process; presentation stays in the host:

- The scheduler appends every job firing to `events` (`delivered=0`) —
  a persistent queue. `pop_events()` returns pending events in order and
  marks them delivered. Notification data crosses the MCP boundary like
  any tool result — the host never opens `scheduler.db`.
- A watcher daemon thread in `server.py` calls
  `HUB.call_tool("scheduler", "pop_events")` every `WATCHER_POLL_S`
  (~15s), formats each event into a Russian one-line text, and appends
  it as `{role:"assistant", meta:{kind:"scheduler"}}` to session id
  `summary` («сводка») via `ChatStore.load → append → save`, created
  with default fields on first event.

Why a dedicated session: it is a normal row in `sessions`/`messages`, so
the whole existing stack (transcript, persistence, restore) works
unchanged, and the «сводка» chat doubles as the historical record —
"the agent periodically outputs a summary" is literally visible as a
message timeline.

Rejected alternatives (all demoed on the same events if wanted later):
- **UI toast** — ephemeral, no record; weaker demo.
- **Real agent turn per event** — the model calling `summary` and
  writing prose is the most literal reading of «агент выдаёт сводку»,
  but each tick costs a paid model call and must contend for `BUSY`;
  deterministic formatting carries the same information for free.
- **SSE/WebSocket push** — real-time, but a whole new channel for a
  ~15s-latency demo requirement.

### 4. Injection is serialized on the existing busy lock

`ChatStore.save` rewrites a session's whole history (delete +
re-insert), so the watcher takes `BUSY_LOCK` around its
load→append→save. If a user turn is in flight, injection waits one
poll — events are a persistent queue, so nothing is lost by retrying.
A user chatting *inside* «сводка» at the moment of injection is the only
residual race; it is a view-mostly session and the window is
sub-second — accepted.

### 5. Aggregation is computed on read

`summary(window_min=10)` computes per-metric count/min/max/avg + fired
reminders in the window from `datapoints`/`jobs` at call time — no
separate summaries table, no scheduled write of aggregates. The
periodic "выдача" is covered by the collector's per-tick event →
«сводка» message path (decision 3); the tool answer is the on-demand
form of the same data.

### 6. Frontend: pin + poll + badge, zero new endpoints

The chat list is client-side (localStorage), and `GET /api/agent?id=`
already returns a transcript. The frontend pins «сводка» at the top of
`ChatList` (fixed id `summary`), polls `/api/agent?id=summary` every
`SUMMARY_POLL_S` (~15s), and marks the entry unread when the transcript
grows past the last-opened message count; opening the chat clears it.
No new HTTP endpoints, no storage change.

### Timing constants (one place, demo cadence)

`TICK_S=30`, collector `interval_s=120` (the task-demo "every ~2 min"),
`WATCHER_POLL_S=15`, `SUMMARY_POLL_S=15`. All module-level constants.

## Risks / Trade-offs

- **`pop_events` marks delivered on read** → a watcher crash between
  drain and `save` drops that batch. Window is sub-second and events are
  informational → accepted over a two-phase ack tool.
- **Ticker granularity** → jobs can fire up to `TICK_S` late; irrelevant
  at minute-scale schedules, stated in README.
- **«сводка» grows unboundedly** (30 msgs/hour at the demo cadence) →
  fine for the exercise; a message-cap is a one-constant follow-up if a
  long run is wanted.
- **Scheduler tool calls inside chat compete with the collector** → none
  in practice: `remind`/`job_list`/`summary` are read/write on the same
  SQLite, serialized by a lock inside the server process.
- **Tracker.db read by a second process** → WAL readers are safe; the
  collector degrades to loadavg if the file is missing/locked.
- **"24/7" scope** → honest framing: while `server.py` runs; restart
  catch-up fires overdue reminders and drains pending events.
