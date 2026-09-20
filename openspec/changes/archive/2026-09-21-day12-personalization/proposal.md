# Proposal

## Why

Day 12 task (verbatim):

> День 12. Персонализация ассистента. Добавьте персонализацию поверх модели
> памяти: создайте профиль пользователя, опишите предпочтения (стиль, формат,
> ограничения), подключите профиль к каждому запросу. Проверьте: ответы для
> разных профилей, что ассистент учитывает автоматически. Результат:
> персонализированный агент, адаптированный под пользователя.

Curator clarification (course chat): a profile is not a settings bundle —
it is the user's own layer ("обращайся ко мне так-то", "на запрос 'напиши
фичу' спавнятся такие-то агенты в таком порядке"); a user may have several
profiles for different tasks, split across files ("профиль = пайплайн из
скиллов… оркестрация скиллов").

Day 11 built layered memory (short / working / long-term). Day 12 replaces
the task-scoped layer with a user-scoped one: the working layer and the
whole workspace machinery are dropped, and a first-class **user profile**
is added on top of the remaining memory model (short-term transcript +
auto-learned long-term file). Result: three kinds of personalization —
declared (profile files), learned (long-term extractor), and behavioral
(optional per-profile pipeline that orchestrates answer generation).

## What Changes

- New `day12/` app, cloned from `day11/` skeleton: `Agent` + registry +
  SQLite persistence + global busy-lock + `tokens.py` + `config.py` +
  React frontend. **Removes**: working memory (goal/plan/facts), the
  `workspaces` table, `sessions.workspace_id`, workspace picker/grouping,
  `PUT /api/working`, `GET /api/workspaces`, `POST /api/promote`,
  `POST /api/workspace/delete`, and the covered-per-workspace catch-up map.
- **User profiles as files**: `day12/profiles/<slug>.md`, same section
  format as `longterm.md` (`## Профиль` / `## Стиль` / `## Формат` /
  `## Ограничения` as `- ключ: значение` bullets) plus an optional
  `## Пайплайн` section (`- имя: инструкция`, ordered steps). CRUD via UI
  and API; profiles resolve from disk on every request.
- **Profile bound per chat** (`sessions.profile_id`): picker in the
  composer («без профиля» option); each answer's meta records which
  profile was applied. Manual selection only — no auto-router.
- **Injection**: the bound profile renders as its own system block on
  every request; `layers` becomes `{short, longterm, profile}` — profile
  is a toggleable layer, same demo mechanism as day 11.
- **Pipeline execution**: when the bound profile has a `## Пайплайн`
  section, a request runs its steps sequentially (one LLM call per step,
  each step sees prior step outputs), streaming `step`-tagged events
  (day3 pattern); only `user + final answer` enter the transcript.
- **Slimmed extractor**: post-`done` extraction writes only the
  ДОЛГОСРОЧНОЕ block (ЦЕЛЬ/ПЛАН/ФАКТЫ gone); `covered` becomes a
  per-session cursor in `sessions`; the extractor receives the active
  profile and must not re-record preferences already declared there.
- Frontend: composer profile chip + per-chat profile badge; `MemoryPanel`
  loses the working section and gains a profiles section (list, raw-markdown
  editor, template insert, delete); `ContextDiagram` swaps the working
  segment for profile; pipeline answers render expandable step phases.
- Seed profiles committed (`day12/profiles/`): two preference-only
  profiles with opposing styles plus one pipeline profile — instant A/B
  material for «ответы для разных профилей».

## Capabilities

### New Capabilities

- `assistant-personalization`: user profiles as editable files bound per
  chat and injected into every request; optional profile pipelines that
  orchestrate multi-step answers; separation of declared preferences
  (profile) from learned ones (long-term memory, with dedup between them);
  observable per-answer record of which profile and steps were applied.

### Modified Capabilities

(none — day12 is a separate app; `agent-memory-layers` keeps describing
the untouched day11 folder)

## Impact

- **New code**: `day12/` (Python stdlib backend + Vite/React frontend,
  committed `dist/`). No changes to existing `dayN/` folders.
- **Storage**: `day12/data/chat_history.db` (gitignored) — `sessions`
  gains `profile_id` + `covered` columns, drops `workspace_id`; no
  `workspaces` table. `day12/memory/longterm.md` (skeleton committed) +
  `day12/profiles/*.md` (seed profiles committed).
- **API surface**: `/api/chat` config gains `profile`, drops `workspace`;
  `layers` keys become `{short, longterm, profile}`; NDJSON gains `step`
  events for pipeline runs; new `GET /api/profiles`, `GET/PUT
  /api/profile?id=`, `POST /api/profile/delete`; removed workspace-era
  endpoints listed above.
- **Ports/keys**: server 7871, Vite dev 5183, localStorage `day12-*-v1`.
- **Verification**: `day12/offline_check.py` (fake client, no network) +
  minimal live smoke; profile-comparison runs are the user's part of the
  task.
- **Precondition**: uncommitted day11 work in the worktree should be
  committed before forking, so the copy starts from a clean base.
