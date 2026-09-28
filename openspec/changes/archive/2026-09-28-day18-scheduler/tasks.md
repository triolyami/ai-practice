# Tasks

## 1. Day18 skeleton

- [x] 1.1 Copy `day17/` → `day18/` (excluding `data/`, `server.log`,
  `__pycache__`, `frontend/node_modules`; keep committed `dist/` as
  starting point), bump ports to server **7875** / dev **5187**,
  localStorage keys `day18-*-v1`, rename day17→day18 strings; verify:
  `env -u all_proxy -u ALL_PROXY .venv/bin/python day18/server.py`
  starts, the registry line shows the three day17 servers ok, and
  `day18/offline_check.py` passes unchanged.
- [x] 1.2 In `frontend/vite.config.js` point dev proxy at 7875 and set
  port 5187; verify `npm run build` still succeeds (fresh dist).

## 2. Scheduler MCP server

- [x] 2.1 `day18/scheduler_server.py`: stdio `MCPServer` owning
  `day18/data/scheduler.db` (WAL, parent auto-created) with tables
  `jobs`/`datapoints`/`events` per design.md §2; writes serialized by a
  process-local lock. Verify: module imports standalone; tables appear
  on first run.
- [x] 2.2 Ticker daemon thread: wake every `TICK_S=30`, run due
  `pending` jobs — `once` → status `fired` + `fired_at` + event row;
  `interval` → collect datapoint(s) + event row + `next_run +=
  interval_s`; on server start run one immediate pass so overdue
  `once`-jobs catch up. Seed one `interval` job (`interval_s=120`,
  tracker status counts, loadavg fallback) when `jobs` is empty.
  Verify: unit-snippet with `TICK_S` tiny — a `once` job due in the past
  fires on boot pass; interval job writes datapoint rows repeatedly.
- [x] 2.3 Tools: `remind(text, in_minutes)` → creates `once`-job,
  returns id + due time; `job_list()` → jobs with status/next_run;
  `job_cancel(id)` → pending→cancelled (404-ish ToolError on unknown);
  `summary(window_min=10)` → per-metric count/min/max/avg + fired
  reminders in window, computed from stored rows; `pop_events()` →
  pending events in order, marked delivered. Verify: in-process
  `Client` calls round-trip each tool; `pop_events` second call returns
  empty; unknown id surfaces `is_error` text.
- [x] 2.4 Register `{"id": "scheduler", "transport": "stdio", ...}` in
  `config.py` `MCP_SERVERS`. Verify: `day18/mcp_probe.py` lists
  `scheduler` with its tools; `POST /api/mcp/call`
  `scheduler/summary` returns an aggregate over the seeded datapoints;
  `GET /api/mcp` shows four servers.

## 3. Watcher + «сводка» injection

- [x] 3.1 `server.py`: watcher daemon thread — every
  `WATCHER_POLL_S=15`s `HUB.call_tool("scheduler","pop_events")`; for
  each event format a Russian one-line message and append
  `{role:"assistant", meta:{kind:"scheduler"}}` to session `summary`
  («сводка») via `ChatStore.load → append → save`, creating the session
  with defaults on first event; whole inject under `BUSY_LOCK`; hub
  errors → log + retry next poll (never kill the thread). Verify: with
  the server running, a `remind` due in ~1 min produces a «сводка»
  assistant message without any user request; restarting mid-way loses
  no pending events.
- [x] 3.2 `offline_check.py` additions: fake ticker/due-jobs —
  `once` fires once and completes, `interval` reschedules and writes
  datapoints, boot pass fires overdue `once`-jobs, `pop_events` drains
  once, `job_cancel` prevents firing; watcher with a fake `call_tool`
  injects into the store and a second poll adds nothing. Verify:
  `day18/offline_check.py` green.

## 4. Frontend

- [x] 4.1 Pin «сводка» (id `summary`) at the top of `ChatList`; poll
  `GET /api/agent?id=summary` every `SUMMARY_POLL_S=15`s; unread badge
  on the entry when its message count exceeds the last-opened count
  (tracked in localStorage); opening the chat clears the badge; an open
  «сводка» transcript refreshes on poll. Verify: live UI — fire a
  reminder, badge appears within ~15s while in another chat, clears on
  open, message visible in transcript; `npm run build` → committed
  dist.

## 5. Docs + final verification

- [x] 5.1 `day18/README.md`: task text, architecture diagram
  (ticker-in-MCP + watcher → «сводка»), tools table, timing constants,
  demo script («напомни через 2 минуты…» → message appears; «что
  собралось?» → `summary` via the model), decisions section (in-process
  ticker vs cron, pull-through-MCP delivery, deterministic summaries vs
  per-tick agent turns), honest "24/7" scoping. Verify: doc matches
  behavior.
- [x] 5.2 Full pass: `offline_check.py` green; live smoke on a
  probe-verified model — `scheduler__remind` call from chat, event
  lands in «сводка», collector datapoints accumulate across ≥2 ticks,
  `scheduler__summary` aggregates them, restart → overdue catch-up +
  no lost events; Browser Use UI check of the pinned chat + badge;
  confirm day17 app still runs untouched.
