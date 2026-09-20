# Tasks

**Parallelization:** Phase 1 is sequential (everything depends on it). After
Phase 1, **Stream A (backend) ∥ Stream B (frontend)** are independent — they
can run in separate sessions/subagents against the API contract fixed in
`design.md` D6. Phase 4 runs last.

## 1. Foundation — sequential, blocks all streams

- [x] 1.1 Create `day11/` by copying `day10/` (backend *.py, `frontend/` incl.
  `package-lock.json`; copy `node_modules/` on disk for the build, it stays
  gitignored). Bump ports: server `PORT=7870`, Vite dev `5181→5182` proxy
  →7870; localStorage keys `day10-*-v1` → `day11-*-v1`; DB path
  `day11/data/chat_history.db`; TopBar label «день 11 · память агента»; add
  `day11/data/` to `.gitignore`. Verify: `.venv/bin/python day11/server.py`
  boots on 7870 and serves the (stale, day10-branded) dist.
- [ ] 1.2 Strip inherited machinery: delete `day10`-era `facts.py`, the
  strategy switcher (`strategy`, `window_size`, `STRATEGY_MODES`,
  `facts_state`), `fork()`/`POST /api/fork`/`parent_id`/`fork_len`, and their
  UI twins (strategy seg, window input, fork button, BranchBanner,
  FactsPanel). `Agent._request` sends `system + full history + user`.
  Verify: `send_stream` round-trip works on a fake client; no `facts`/`fork`
  references remain (`grep -rn "fork\|strategy\|facts" day11/` clean except
  memory-related naming).

## 2. Stream A — backend memory (sequential within stream)

- [x] 2.1 Create `day11/memory.py`: extractor `update_memory(working,
  longterm_items, messages, model, client)` → `{goal, plan, facts,
  longterm_pairs}` parsed tolerantly from a plain-text sectioned reply
  (ЦЕЛЬ/ПЛАН/ФАКТЫ/ДОЛГОСРОЧНОЕ, ≤15 facts, ≤200 chars/value, ≤4000 total,
  ≤30 long-term bullets); `render_working_message(state)` /
  `render_longterm_message(text)` → system messages; `read_longterm(path)` /
  `write_longterm(path, sections→lines)` with per-key dedup and a global file
  lock; `EMPTY_WORKING = {"goal":"", "plan":[], "facts":[]}`. Verify: parser
  handles bullets/colons/junk/missing sections (checked in 4.1).
- [x] 2.2 `day11/storage.py`: add `workspaces(workspace_id PK, name, state
  JSON, covered JSON {session_id:int}, updated_at)` table + `sessions.
  workspace_id` column; `save_workspace`/`load_workspace`/`list_workspaces`/
  `delete_workspace`; snapshot round-trips `workspace_id`. Verify: sqlite
  roundtrip via `.venv/bin/python` one-liner or offline_check.
- [x] 2.3 `day11/agent.py`: `_request` = `[persona] + [longterm block] +
  [working block] + full history + [user]`, each block gated by
  `self.layers{short,working,longterm}` (default all on; `short` off → no
  history); `configure` accepts `layers` + `workspace` (name → resolve/create,
  covered[sid]=0 on reassign); post-`done` `_update_memory()` generator —
  per-session `covered` inside the workspace row, 12-msg chunks, `memory`
  event on success, `notice` on failure/retry; `promote(key)`; snapshot/
  from_snapshot carry workspace+layers; `meta` gains `layers`, `workspace`,
  `tokens.longterm/working`; `totals` = `{chat, memory_calls}`; `reset`/
  `forget` clear the chat's `covered` entry only.
  Verify: offline_check scenarios pass (4.1).
- [x] 2.4 `day11/server.py`: `parse_config` accepts `workspace` (str ≤120) +
  `layers` (3 bools), drops strategy/window; replace per-session `BUSY` with
  a global busy flag → 409 while any generation runs; one `MEMORY_LOCK`
  guarding all workspace/file writes (extraction + PUT/promote); new
  endpoints `GET/PUT /api/longterm`, `GET /api/workspaces`, `PUT
  /api/working`, `POST /api/promote`, `POST /api/workspace/delete`; `memory`/
  `notice` events pass through; workspace row saved alongside session after
  `done`. Verify: curl each endpoint shape per design D6; 400/404/409 paths.

## 3. Stream B — frontend (parallel with A; contract = design D6)

- [ ] 3.1 `lib/constants.js` + `lib/storage.js`: `LAYERS` labels
  (краткосрочная/рабочая/долговременная), `DEFAULT_AGENT {workspace:"",
  layers:{short:true,working:true,longterm:true}}`, `snapshot()` wire format
  `{name,system_prompt,model,workspace,layers}`; keys renamed `day11-*-v1`.
  Verify: `npm run build` compiles.
- [ ] 3.2 `MemoryPanel.jsx` (replaces FactsPanel): three sections —
  долговременная (rendered file + edit textarea → `PUT /api/longterm`),
  рабочая (workspace name, goal/plan/facts editable → `PUT /api/working`,
  per-fact «→ в долговременную» → `POST /api/promote`), краткосрочная
  (message count + «живёт только в этом чате»). Verify: edits persist and
  survive reload (visible in `/api/agent` + `/api/longterm`).
- [ ] 3.3 `ChatList.jsx`: group chats under workspace headers; «+» on a
  workspace header creates a chat already assigned to it. Verify: two chats
  in one workspace render grouped.
- [ ] 3.4 `SettingsPanel.jsx`: workspace name input with datalist of
  `GET /api/workspaces` names; three layer checkboxes; strategy/window
  controls removed. Verify: toggles reach the request (`meta.layers`).
- [ ] 3.5 `ContextDiagram.jsx` 5 segments (system/longterm/working/history/
  request) + `TokenPanel` rows (чат / обновление памяти) + `MetaLine`
  (layers · workspace · контекст% · $). Verify: diagram shows longterm +
  working segments after extraction.
- [ ] 3.6 `App.jsx`/`useChat.js`: handle `memory` event (patch agentInfo
  silently), workspace assign via config, welcome examples re-themed to
  memory. Verify: full send→extract→panel-update flow in dev server.
- [ ] 3.7 `npm run build` → commit `dist/`. Verify: server on 7870 serves the
  new UI with no Node running.

## 4. Verification & docs — last

- [x] 4.1 `day11/offline_check.py` (FakeClient pattern from day10): extractor
  classification lands in correct stores; covered per-session map; layer
  toggles exclude blocks; promote writes longterm.md; reset/forget clear
  chat-only state; two agents share workspace memory; restart roundtrip;
  corrupt snapshot/file tolerance. Verify: `.venv/bin/python
  day11/offline_check.py` → all pass.
- [ ] 4.2 Live smoke (minimal real calls, user balance-sensitive): 2 chats →
  same workspace → fact from chat A appears in chat B's request; long-term
  toggle on/off changes the answer; `longterm.md` gains a bullet; restart
  server → state intact. Verify: manual/curl, recorded in README.
- [ ] 4.3 `day11/README.md` (Russian): task text, layer model diagram, demo
  scenario for «как влияет на ответы» (profile→«напиши сервис авторизации»
  with/without long-term), run instructions.
- [ ] 4.4 Append `### Day 11` section to `AGENTS.md` (local file): ports,
  storage layout, extractor design, gotchas discovered.
