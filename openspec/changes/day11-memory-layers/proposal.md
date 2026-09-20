# Proposal

## Why

Day 11 task (verbatim):

> День 11. Модель памяти агента. Опишите и реализуйте модель памяти для
> агента. Разделите информацию минимум на 3 типа: краткосрочная (текущий
> диалог), рабочая (данные текущей задачи), долговременная (профиль, решения,
> знания). Сделайте так, чтобы разные типы памяти хранились отдельно, вы явно
> выбирали, что и куда сохраняется. Проверьте: какие данные попадают в каждый
> слой, как это влияет на ответы агента. Результат: агент с явной моделью
> памяти (memory layers).

The course week is building toward a stateful agent (personalization → state
machine → invariants → integration). Day 11 is the foundation: an explicit,
layered memory model. Days 6–10 already built the substrate — `Agent` class,
SQLite persistence, token accounting, a post-turn LLM "memory editor"
(`day10/facts.py`) — but all memory so far is single-layer and session-scoped.
This change splits memory into three layers differentiated by scope
(chat / workspace / user) and makes every write explicit and visible.

## What Changes

- New `day11/` app, cloned from `day10/` skeleton: `Agent` + registry +
  per-session busy-lock + save-on-done + snapshot/restore + `tokens.py` +
  `config.py` + `storage.py` + React frontend. **Removes**: strategy switcher
  (window/facts/branches), `fork()`, `facts.py`. `facts.py` evolves into
  `memory.py` (extractor + renderers + parsers).
- **Three memory layers**, stored separately:
  - **short-term** = full current dialog → existing `messages` table, sent
    verbatim (no window — day10's `window_size` is dropped with strategies).
  - **working** = current-task data `{goal, plan, facts[]}` → new
    `workspaces` table; scope = a named *workspace* that groups chats.
  - **long-term** = profile / decisions / knowledge → `day11/memory/
    longterm.md` — a plain file outside the DB, shared by all chats, survives
    reset/forget/restart.
- **Workspaces** as first-class entities: new chats get a private workspace;
  a chat can be moved to an existing workspace (shared working memory);
  workspaces outlive their chats (can be reattached to a new chat).
- **Routing = explicit + automatic**: a post-`done` LLM extractor classifies
  new information into working (task-relevant) vs long-term (user-level);
  users can edit any layer and promote working items → long-term.
- **Per-request layer toggles** (short/working/long-term on/off) to
  demonstrate how each layer affects answers.
- Frontend: `MemoryPanel` (three sections, working + long-term editable),
  chats grouped by workspace in the sidebar, `ContextDiagram` gains
  long-term/working segments, per-layer `meta.tokens` fields.
- New API: `GET/PUT /api/longterm`, `PUT /api/working`, `GET /api/workspaces`,
  `POST /api/promote`; `config` gains `workspace` + `layers`.

## Capabilities

### New Capabilities

- `agent-memory-layers`: layered agent memory — three stores separated by
  scope (chat/workspace/user), an LLM extractor that classifies new
  information into working vs long-term with user override, per-request
  injection of each layer into the prompt, and UI/API to inspect and edit
  every layer.

### Modified Capabilities

(none — first spec in the repo; days 1–10 are finished snapshots, not
retro-specced)

## Impact

- **New code**: `day11/` (Python stdlib backend + Vite/React frontend,
  committed `dist/`). No changes to existing `dayN/` folders.
- **Storage**: `day11/data/chat_history.db` (gitignored) — `sessions`,
  `messages`, new `workspaces` table, `sessions.workspace_id` column;
  `day11/memory/longterm.md` (committed empty template or created on demand).
- **API surface**: extends day10's NDJSON chat API with memory events +
  memory CRUD endpoints (see above).
- **Ports/keys**: server 7870, Vite dev 5182, localStorage `day11-*-v1`.
- **Verification**: `day11/offline_check.py` (fake client, no network);
  real-API comparison runs are the user's part of the task.
