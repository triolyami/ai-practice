# Tasks

## 0. Precondition

- [x] 0.1 Commit the pending day11 worktree changes (`git status` clean for `day11/`) so the fork starts from a clean base; verify `git status --short day11/` prints nothing.

## 1. Fork and strip

- [x] 1.1 Copy `day11/` → `day12/` (excluding `node_modules`, `dist`, `data/`, `__pycache__`, `server.log`); bump ports to 7871/5183, `DAY11_DIR`→`DAY12_DIR`, localStorage prefix to `day12-`, DB path to `day12/data/chat_history.db`; verify `day12/server.py` imports cleanly.
- [x] 1.2 Delete workspace/working machinery: `workspaces` table + `sessions.workspace_id` (→ `profile_id`), all `*_workspace*` store methods, `_assign_workspace`, `promote()`, `config.workspace`, endpoints `/api/working`, `/api/workspaces`, `/api/promote`, `/api/workspace/delete`, workspace datalist/grouping in frontend; verify `grep -ri workspace day12/` returns only comments/translations to update.
- [x] 1.3 Add `sessions.covered INTEGER NOT NULL DEFAULT 0` (per-session extraction cursor replacing the per-workspace map); verify `ChatStore` roundtrip keeps it via a quick sqlite check.

## 2. Profiles backend

- [x] 2.1 `day12/profiles.py`: profile file store — `list_profiles()`, `read_profile(slug)`, `write_profile(slug, content)`, `delete_profile(slug)`, `slugify(name)`; generalize the longterm parser (`## Секция` + `- ключ: значение`) with `## Пайплайн` → ordered steps; caps (≤30 bullets/section, ≤200 chars, ≤20 KB, ≤8 steps); verify with a unit smoke: write→read→parse→delete a temp profile file.
- [x] 2.2 `agent.py`: `profile_id` field + `configure(profile=...)`; `_request()` injects `[system: ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ «name» …]` after persona, gated by `layers.profile` and live-resolved from disk; `layers` = `{short, longterm, profile}`; verify `_request()` output shows/drops the block with the toggle (fake client or direct call).
- [x] 2.3 `tokens.py`: `breakdown()` segment `working` → `profile`; meta/context_preview carry `tokens.profile`, `profile`, `profile_missing`; verify describe() exposes them.
- [x] 2.4 `storage.py`/`snapshot()`: persist `profile_id` per session; verify restart-restore keeps the binding (snapshot roundtrip test).

## 3. Pipeline execution

- [x] 3.1 `agent.py` pipeline path: bound profile with `## Пайплайн` → sequential `complete()` calls per step (uniform prefix: persona + profile + longterm; step instruction as system; user message = original + prior outputs; short history on step 1 only); `step_start`/`delta`(tagged)/`step_done` events; verify fake client receives calls in declared order.
- [x] 3.2 History/commit semantics: append `user + final answer` only after the last step; mid-pipeline failure or disconnect appends nothing; verify offline_check case: step 2 of 3 raises → history unchanged.
- [x] 3.3 Meta: `pipeline: [step names]`, per-step usage summed into the turn meta; verify done event shows step list + totals.

## 4. Extractor slim + profile-awareness

- [x] 4.1 `memory.py`: extractor prompt reduced to `ДОЛГОСРОЧНОЕ` output only (ЦЕЛЬ/ПЛАН/ФАКТЫ removed); `covered` per session; verify a 2-turn fake-client run writes a longterm bullet and advances `sessions.covered`.
- [x] 4.2 Profile-aware dedup: extractor receives the active profile text + «заявленное в профиле не дублируй» rule + post-parse key filter; verify a repeated declared preference leaves `longterm.md` unchanged.

## 5. Server API

- [x] 5.1 `parse_config`: accept `profile` (slug/empty) + `layers {short,longterm,profile}`, reject `workspace`; verify 400s on bad values via curl.
- [x] 5.2 Profile endpoints: `GET /api/profiles`, `GET /api/profile?id=`, `PUT /api/profile {id?,name,content}`, `POST /api/profile/delete`; verify CRUD roundtrip via curl against the dev server.
- [x] 5.3 NDJSON: `start.meta.profile`, `step_start`/`step_done` on pipeline runs, `memory` event minus working fields; verify a pipeline chat over curl emits ordered step events.

## 6. Frontend

- [x] 6.1 Composer profile chip + dropdown (profiles + «без профиля») sending `config.profile`; chat-list profile badge; meta line shows applied profile/`profile_missing`; verify in IAB: bind profile, send message, meta names it.
- [x] 6.2 `ProfilesPanel` section in the right sidebar: list, raw-markdown editor, «вставить шаблон», create, delete; working section removed; `ContextDiagram` segment `working`→`profile`; `ChatList` flat; verify panels render and edit→next-request uses new content.
- [x] 6.3 Pipeline phases: expandable per-step blocks (name/content/tokens) above the final answer; verify a pipeline profile run renders 3 phases in order.

## 7. Seeds, housekeeping

- [x] 7.1 Commit 3 seed profiles: `lakonichny.md`, `mentor.md`, `reviewer.md` (with `## Пайплайн`); commit `memory/longterm.md` skeleton; `.gitignore` covers `day12/data/`; verify fresh clone-equivalent state lists profiles in the UI.
- [x] 7.2 Update `README.md` (day12 line) and `AGENTS.md` day-12 section per repo conventions; verify no `.env` staged (`git diff --cached --name-only`).

## 8. Verification

- [x] 8.1 `day12/offline_check.py` (fake client): profile parse/inject, layer toggle, pipeline order + rollback, extractor dedup vs profile, covered advance, snapshot roundtrip — all pass.
- [x] 8.2 Live smoke on the default model: two chats with different profiles answer the same prompt differently; profile edit affects next turn; learned fact lands in longterm only when not declared; restart preserves binding + longterm.
