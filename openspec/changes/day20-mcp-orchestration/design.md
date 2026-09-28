# Design

## Context

See proposal.md for the task. Current state that shapes the approach:

- `day19/` is the fullest stack: `Agent` with a bounded tool loop
  (`MAX_TOOL_ROUNDS = 5`, `tools` = OpenAI function specs built from the
  hub as `server__tool`), `MCPHub` (daemon thread, one `mcp.Client` per
  registry entry, per-server error isolation), a stdlib
  `ThreadingHTTPServer` (`/api/chat` NDJSON with `tool_call` /
  `tool_result` events; `done.meta.tool_calls` records
  `{name, server, tool, arguments, ok, preview, result_len,
  result_sha256, hop_exact, latency_ms}` in order), React frontend that
  renders tool phases, `offline_check.py` with in-process MCP checks.
- Day19's registry was deliberately trimmed to the single `pipeline`
  server. Day18's registry had four servers (`py-tools` Python stdio,
  `ts-tools` TypeScript stdio, `tracker`, `scheduler`); their server
  files still live in `day18/` and are self-contained (tracker spawns
  its REST API in-process on an ephemeral port; scheduler owns its
  SQLite db + ticker thread).
- Tool selection is model-side semantic routing: the model sees a flat
  `server__tool` list and chooses. Hub dispatch by prefix is mechanical
  and already proven.
- `hop_exact` already exists: for any call with a string `text`
  argument it compares sha256 against the previous call's full result —
  so cross-server data fidelity is verifiable with zero new machinery.
- `deepseek-v4-flash` is the verified tool-calling model; glm models
  are untested for tools (Z.ai balance). `DEEPSEEK_API_KEY` lives in
  root `.env`; config reads env at import → server restart after edits.

The conceptual frame continues day19's: MCP tools are isolated, and
routing/orchestration lives in the host — here, in the model + the
hub's dispatch. Day20 adds the checkable question: does the model pick
the right tools in the right order when a flow crosses servers?

## Goals / Non-Goals

**Goals:**
- One self-contained `day20/` app where the agent drives a long
  dependent chain across ≥3 servers from a single user message.
- A falsifiable verdict: `check(trace)` evaluates expected subsequence,
  distinct-server coverage, distractor rejection, and reports
  per-criterion pass/fail.
- Cheap: reuse everything; new code ≈ two small files (`flow.py`,
  `flow_run.py`) plus config edits.

**Non-Goals:**
- No planner/orchestrator code in the host for the main scenario —
  selection and ordering must come from the model (that IS the task).
- No `ts-tools` (node_modules weight; cross-language interop was proven
  in day17 and adds nothing to this task).
- No new frontend features: wholesale copy of day19's UI, sed-level
  edits only. The pipeline panel survives because `/api/pipeline` does.
- No new server endpoints: `flow_run.py` talks to the existing
  `/api/chat` over HTTP and evaluates the `done.meta.tool_calls` trace.
- No changes to day17/18/19 folders; `day20/` is self-contained.

## Decisions

- **Base = day19, servers added back.** Day19 has the better trace
  (`hop_exact`) and the pipeline server in-tree; day18 files
  (`tools_server.py`, `tracker_server.py` + `tracker_api.py`,
  `scheduler_server.py`) are copied in verbatim. Rejected: basing on
  day18 (older trace, no pipeline); referencing sibling-day files by
  path (breaks day self-containment).
- **Registry: pipeline + tracker + scheduler + py-tools.** Three
  real-domain servers make routing meaningful; `py-tools` is included
  as a deliberate distractor — `notes_add` semantically collides with
  tracker issues, so «выбор нужного инструмента» becomes falsifiable
  (a trace using `py-tools__notes_add` for the task step fails the
  `forbid` criterion). Rejected: only the 3 real servers (selection
  then can't visibly go wrong); adding `ts-tools` (weight, no value).
- **`MAX_TOOL_ROUNDS` 5 → 10.** Dependent calls cannot batch (each
  needs the previous result), so a 5-hop chain already spends 5 rounds;
  one retry would truncate the flow. 10 leaves headroom without
  inviting infinite loops.
- **Scenario spec lives in `flow.py`**, as data + a pure checker:
  `SCENARIOS = {id: {prompt, expect: [ordered server__tool patterns],
  require: [unordered patterns], min_servers, forbid: [names]}}` and
  `check(trace, spec) -> verdict`. Order is asserted only where data
  dependency forces it (search→summarize, create→comment);
  order-independent steps live in `require` — a strict total order
  fails correct traces (observed live: model fires `remind` before
  `issue_comment`, which is valid).
  Wildcard tool patterns (`tracker__issue_*`) keep the spec honest —
  the model may pick `issue_create`/`issue_comment` freely as long as
  order and coverage hold. Pure function → testable offline on
  synthetic traces.
- **Runner = CLI (`flow_run.py`), not an endpoint.** POSTs the scenario
  to `/api/chat` (fresh session id), collects the NDJSON stream, prints
  the ordered trace (server.tool, latency, hop flags) and the verdict.
  Rejected: `POST /api/flow` endpoint — same behavior but touches
  server.py and adds a surface nobody asked for; a curl-able demo can
  still use `/api/chat` directly.
- **Canned scenario prompt (natural, not a recipe):** roughly «найди в
  корпусе про композицию MCP, сожми в дайджест, заведи задачу в
  трекере, положи дайджест комментарием, поставь напоминание вернуться
  к ней» — expected subsequence `pipeline__search →
  pipeline__summarize → tracker__issue_* → scheduler__remind`, with the
  digest visibly crossing pipeline → tracker via `hop_exact`. Rejected:
  an explicit tool-order prompt — it would test instruction following,
  not selection.
- **No steering system prompt.** The default generic assistant prompt
  stays; tool descriptions alone must carry routing. If live runs show
  the model fumbling, the fallback is a `config.system_prompt` hint
  (documented), not code.
- **Frontend: copy wholesale, sed edits, rebuild once.** `dist/` is
  committed, so the UI works immediately; rebuilding after the
  mechanical renames (title, `day19-*` → `day20-*` storage keys, vite
  port 5189, proxy 7877) is one npm command. Rejected: CLI-only (breaks
  the repo's live-playground convention for ~zero savings) and editing
  the committed dist by hand (minified strings).

## Risks / Trade-offs

- [Model picks the distractor or wrong order despite descriptions] →
  that's a finding, not a bug: the checker reports it, README records
  it, and the recipe-prompt variant (optional second scenario) shows
  the contrast. Worst case, a one-line system prompt hint.
- [deepseek-v4-flash batches or skips dependent steps] → the trace and
  `hop_exact` make the skip visible; `expect` subsequence tolerates
  extra calls.
- [Cold DBs: tracker/scheduler create their schemas on first run] →
  `data/` is created by the servers themselves; scenario only needs
  `issue_create`, which works on an empty db.
- [Copy drift vs day18/19 originals] → deliberate: days are frozen
  snapshots; day20 owns its copies.
