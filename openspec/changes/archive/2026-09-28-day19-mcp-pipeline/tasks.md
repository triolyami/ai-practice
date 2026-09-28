# Tasks

## 1. Scaffold day19

- [x] 1.1 Copy `day18/` → `day19/` (exclude `__pycache__`, `server.log`, `data/*.db`; keep `ts-tools` source) and bump ports: server **7876**, vite dev **5188** with proxy → 7876; rename storage db/`localStorage` prefixes to `day19-*` and `Day19Handler`. Verify: `env -u all_proxy -u ALL_PROXY .venv/bin/python day19/server.py` starts on 7876 and `GET /api/mcp` lists the four inherited servers.
- [x] 1.2 Create corpus (`day19/corpus/`, committed — `data/` is gitignored for SQLite): several UTF-8 `.txt` files with real prose on searchable topics (a few hundred+ chars each so retyping fidelity is meaningful); create gitignored `day19/out/`. Verify: files committed, `out/` ignored by `git status`.

## 2. Pipeline MCP server

- [x] 2.1 Write `day19/pipeline_server.py` — stdio `MCPServer` with `search(query, limit?)` (deterministic grep over `corpus/`, returns matched chunks), `save_to_file(name, text)` (sanitized basename → `out/`, returns path + byte count). Verify: via in-process `Client` (offline_check-style) — search returns real chunks, save writes the file, traversal name like `../x` stays inside `out/`.
- [x] 2.2 Add `summarize(text)` — lazy deepseek client (`DEEPSEEK_API_KEY`, built on first call, not import) producing a digest; without a key, deterministic extractive fallback (first-N sentences/budget). Verify: no-key env returns an extractive digest; with key it returns a non-prefix model digest.
- [x] 2.3 Add `run_pipeline(query)` composite — calls the three handlers internally in one tool call, returns final result + per-stage digest. Verify: single `POST /api/mcp/call` produces the file and a digest of all three stages.
- [x] 2.4 Register `pipeline` in `MCP_SERVERS`. Verify: startup log shows `mcp[pipeline]` with 4 tools and `GET /api/mcp` lists it `ok`.

## 3. Trace hashes + code-orchestrated lane

- [x] 3.1 In `agent.py`'s trace append, record `result_len` + `result_sha256` (sha256 of the full result text) alongside existing fields. Verify: after a manual tool turn, the assistant message `meta.tool_calls` entries carry both fields.
- [x] 3.2 Add `POST /api/pipeline {query, name?}` — three sequential `hub.call_tool` calls streaming NDJSON `stage` events (`{type:"stage", i, tool, input, output, sha256, hop_exact}`) then `done {ok, verdict, result?}`; first stage error → later stages skipped, `done.ok=false` with stage index. Verify with curl: one request produces 3 ordered stage events + file written; stopping the pipeline server yields a stage error, not a hang.

## 4. Frontend

- [x] 4.1 Add the «пайплайн» card: query input + «запустить пайплайн» (streams lane-2 stage boxes from `/api/pipeline`), «композитный» button (lane 3 → `/api/mcp/call` `run_pipeline`, single box + «нет хопов» badge), copyable suggested chat prompt for lane 1 («в чат» via onSuggest). Verify: both buttons render stage boxes with in/out previews.
- [x] 4.2 Fidelity badges: lane 2 shows `exact` from `done.verdict`; lane 3 shows `not-applicable`; lane 1 shows per-hop `hop_exact` badges computed server-side in `meta.tool_calls` (sha256 compare of `text` arg vs prev `result_sha256`). Verify: a lane-1 chat run shows the badge; a rewritten arg shows `модель переписала данные`.
- [x] 4.3 `npm run build`, commit `dist/`. Verify: server serves the built UI without node.

## 5. Verification + docs

- [x] 5.1 `day19/offline_check.py` — no network/node: in-process hub runs the chain end-to-end; code lane byte-exact; composite produces a single-call digest; fidelity (`hop_exact`/`result_sha256`) verified on fake traces; `summarize` fallback path; save sanitization. Verify: script exits 0 with all checks printed.
- [x] 5.2 Live run: start server, chat prompt drives the 3-call chain (deepseek model), `/api/pipeline` runs the code lane, composite via panel; record fidelity verdicts per lane. Verify: `results` visible in UI + a saved file under `out/` from each lane.
- [x] 5.3 Write `day19/README.md` (ru) — task text, three-lane diagram, fidelity findings, run instructions, decisions/rejected-alternatives section per repo convention.

## 6. Slim the registry to the task (post-implementation, user request)

- [x] 6.1 `MCP_SERVERS` keeps only `pipeline`; delete `tools_server.py`, `tracker_server.py`, `tracker_api.py`, `scheduler_server.py`, `ts-tools/` — the day-17/18 demo servers are not needed for the composition task.
- [x] 6.2 Remove the scheduler watcher (`summary_poll`, `_watcher_main`, `start_watcher`, `_pop_events`, `_format_event`, `_summary_snapshot`, WATCHER/SUMMARY constants) from `server.py` and the pinned «сводка» row + its poll/storage keys from the frontend; rebuild `dist/`.
- [x] 6.3 `offline_check.py`: drop scheduler/watcher/py-tools tests; hub test now runs on `pipeline_app`; fake trace names renamed to `pipeline__*`. Verify: script exits 0.
- [x] 6.4 Update docs for the single-server registry: proposal, design, README, chat welcome text and examples. The `mcp-tools` spec delta was dropped — the registry mechanism is unchanged and the shipped set is per-day content (OpenSpec refuses MODIFIED blocks that drop carried-over scenarios).
