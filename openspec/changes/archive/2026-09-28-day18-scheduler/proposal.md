# Proposal

## Why

Day 18 task (verbatim):

> День 18. Планировщик и фоновые задачи
>
> Сделайте MCP-инструмент с отложенным или периодическим выполнением.
>
> Пример:
>
> 👉 reminder
> 👉 периодический сбор данных
> 👉 регулярный summary
>
> Инструмент должен:
>
> 👉 сохранять данные (JSON / SQLite)
> 👉 выполняться по расписанию
> 👉 возвращать агрегированный результат
>
> Результат:
>
> Агент, который работает 24/7 и периодически выдаёт сводку

Day 17 already built everything except the "by schedule" part: an agent
that calls MCP tools inside a turn, a hub that owns stdio MCP servers,
SQLite persistence, and a chat UI. Day 18's delta is a fourth MCP server
whose tools manage delayed/periodic jobs, plus the one mechanism day 17
lacks: a way for background results to *reach* the user without being
asked (task's «агент периодически выдаёт сводку»).

Decisions taken with the user during exploration:

- The clock lives **inside the scheduler MCP server process** (a ticker
  thread — the same pattern as `tracker_api` inside `tracker_server.py`:
  the hub spawns the process anyway, so the scheduler needs no separate
  lifecycle and leaves no orphans). Chosen over a real `cron` entry:
  the cron daemon runs on this machine, but cron buys nothing for "24/7"
  on WSL (it dies with the distro anyway), adds external install/cleanup,
  and makes "the MCP tool executes on schedule" only indirectly true.
- Both task branches («отложенное» and «периодическое») are covered by
  one mechanism: a `jobs` table where a reminder is a `once`-job and the
  data collector is an `interval`-job.
- Fired jobs reach the user via a **watcher thread in `server.py`** that
  polls the scheduler through the hub (`pop_events` — the notification
  data flows through MCP itself) and appends assistant messages into a
  dedicated «сводка» chat; the frontend polls the existing
  `GET /api/agent` endpoint for that session and shows an unread badge.
  Chosen over: a transient UI toast (no record), a real agent turn per
  tick (spends tokens every interval, collides with the busy lock), and
  pure pull (task asks the agent to *выдавать* the summary).

## What Changes

- New `day18/` app forked from `day17/` — same chat skeleton (Agent with
  tool-calling, session registry, `ChatStore`, busy-lock, MCP hub,
  py-tools/ts-tools/tracker servers, React UI). Delta is additive.
- **New capability: `scheduler`** — `scheduler_server.py` (stdio, mcp
  v2), a job store + ticker thread + tools:
  - SQLite `day18/data/scheduler.db` (WAL): `jobs` (`once` | `interval`,
    `next_run`, `interval_s`, `fired_at`), `datapoints` (collector
    samples), `pending_events` (fired-but-undelivered items).
  - Ticker thread wakes periodically, runs due jobs — a `once`-job marks
    itself fired + enqueues an event; an `interval`-job writes a
    datapoint + event and reschedules. On server start, overdue
    `once`-jobs fire immediately (restart catch-up — this is what makes
    «сохранять данные» observable).
  - One `interval` job is auto-seeded on first boot: a collector that
    snapshots real data every ~2 min (tracker issue counts from
    `day18/data/tracker.db` — demo-visible since chat tool calls move
    the numbers; loadavg as the fallback metric).
  - Tools: `remind(text, in_minutes)`, `job_list()`, `job_cancel(id)`,
    `summary(window_min?)` (aggregated result — per-metric
    count/avg/min/max + fired reminders), `pop_events()` (drains the
    delivery queue; used by the watcher).
- **New capability: `proactive-summary`** — delivery of scheduler events
  to the user without a prompt:
  - `server.py` gains a watcher daemon thread: every ~15s
    `HUB.call_tool("scheduler", "pop_events")`; each event is appended
    as an assistant message (`meta.kind="scheduler"`) to the fixed
    session id `summary` («сводка»), created on first event. Writes go
    through `ChatStore.load → append → save` under `BUSY_LOCK` so an
    in-flight user turn is never clobbered.
  - Frontend pins «сводка» at the top of the chat list, polls
    `GET /api/agent?id=summary` on an interval, shows an unread badge
    when the transcript grows, and refreshes the open transcript.
- **Modified capability: `mcp-tools`** — `MCP_SERVERS` ships a fourth
  stdio entry (`scheduler`).
- **Built-in comparison axis** (repo convention, inside the task): one
  table covers «отложенное» vs «периодическое»; the «сводка» chat makes
  push-vs-pull observable — the same summary is also available on demand
  via the `summary` tool.

## Capabilities

### New Capabilities

- `scheduler`: a persistent job store (delayed `once` jobs + `interval`
  collector jobs) inside a stdio MCP server; a ticker executes due jobs
  on schedule; MCP tools create/list/cancel jobs and return aggregated
  summaries; due-job events are queued for delivery and survive restarts.
- `proactive-summary`: a server-side watcher delivers scheduler events
  into a dedicated «сводка» chat session as assistant messages, and the
  UI polls for them and flags unread activity — the agent "periodically
  outputs a summary" without a user prompt.

### Modified Capabilities

- `mcp-tools`: the registry's out-of-the-box server set grows to four
  (py-tools, ts-tools, tracker, scheduler).

## Impact

- New folder `day18/` (server **7875**, Vite dev **5187**, committed
  `frontend/dist/`, localStorage `day18-*-v1`); DB files under
  `day18/data/` gitignored (chat history + tracker + scheduler).
- New file: `scheduler_server.py`. Modified in the copy: `config.py`
  (registry entry), `server.py` (watcher thread + `BUSY_LOCK` use),
  `frontend/` (chat-list pin, poll, unread badge), `offline_check.py`
  (ticker/due-job/event/injection scenarios), `README.md` (rewrite).
- No new dependencies — ticker/watcher are stdlib threads; the MCP
  server uses the already-pinned `mcp>=2.2,<3`.
- Timing constants (`TICK_S` ~30s, collector interval 120s, watcher poll
  ~15s) are module constants — a demo cadence, tunable in one place.
- "24/7" is honestly scoped: the scheduler runs while `server.py` runs
  (same practical uptime as cron on WSL); jobs/events persist in SQLite
  across restarts, overdue `once`-jobs fire on boot.
- Existing days untouched; day17 keeps working as-is.
