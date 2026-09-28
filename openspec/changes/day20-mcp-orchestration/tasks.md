# Tasks

## 1. Scaffold day20/ from day19

- [x] 1.1 Copy day19 → day20 (agent.py, mcp_hub.py, server.py, config.py, storage.py, tokens.py, offline_check.py, pipeline_server.py, corpus/, tool_probe.py, mcp_probe.py, frontend/ incl. dist/, excluding __pycache__/node_modules/server.log/data) and verify `python -c "import config"` works inside day20 (needs mcp + openai from the venv)
- [x] 1.2 Copy day18's tools_server.py, tracker_server.py, tracker_api.py, scheduler_server.py into day20/ unchanged and verify each compiles (`python -m py_compile`)
- [x] 1.3 In day20/config.py: DAY19_DIR→DAY20_DIR, MCP_SERVERS = pipeline + tracker + scheduler + py-tools (all stdio, sys.executable), and verify the registry lists 4 entries

## 2. Server edits

- [x] 2.1 day20/server.py: PORT 7876→7877, comments/log strings day19→day20; verify `python day20/server.py` starts and GET /api/mcp lists 4 servers with status ok (kill after check)
- [x] 2.2 day20/agent.py: MAX_TOOL_ROUNDS 5→10 (comment why); verify the constant is the only behavioral change
- [x] 2.3 Confirm tracker/scheduler create their DBs under day20/data/ on first start (delete any copied db files; start server, call tracker__issue_list via /api/mcp/call, expect empty-list reply not an error)

## 3. Flow scenario + checker

- [x] 3.1 Create day20/flow.py: SCENARIOS dict (id → prompt, expect subsequence with `server__tool`/`server__*` patterns, min_servers, forbid list) + pure check(trace, spec) → {ok, criteria:[{name, ok, detail}]}; verify `python -c "import flow"` and a hand-fed sample trace yields the expected verdict
- [x] 3.2 Extend day20/offline_check.py with check() tests on synthetic traces: pass case, out-of-order fail, distractor fail, too-few-servers fail; verify `python day20/offline_check.py` exits 0 without network
- [x] 3.3 Create day20/flow_run.py CLI: args = scenario id (+ optional model/session), POSTs /api/chat via urllib to 127.0.0.1:7877 with a fresh session id, collects NDJSON, prints ordered trace (server.tool, latency, hop badges) + verdict from flow.check; verify `python day20/flow_run.py --list` prints scenarios without needing the server

## 4. Frontend

- [x] 4.1 In day20/frontend: sed-level edits only — index.html title → день 20, constants/storage keys day19-*→day20-*, vite port 5188→5189 + proxy →7877; verify `npm install && npm run build` succeeds and dist/index.html has the new title

## 5. Live verification + docs

- [x] 5.1 Start server (env -u all_proxy -u ALL_PROXY .venv/bin/python day20/server.py), run `python day20/flow_run.py cross-server`; verify trace shows ≥4 calls across ≥3 servers in expected order and verdict ok=true (if model fumbles: record, retry once, document — per design)
- [x] 5.2 Verify distractor discipline in the same trace: py-tools__notes_add absent (verdict criterion), and check UI renders the tool phases with server names
- [x] 5.3 Write day20/README.md (Russian): task text, design summary, scenario, run/smoke commands, live-run findings incl. the verdict output
