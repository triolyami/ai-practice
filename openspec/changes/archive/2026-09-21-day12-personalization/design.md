# Design

## Context

See proposal.md — Why. Base: `day11/` (latest lineage: `Agent` + SQLite
persistence + token accounting + right-sidebar panels + post-done
extractor + three memory layers). Day 12 keeps the substrate and swaps
the task-scoped layer for a user-scoped one: profiles.

Confirmed scope decisions (from the explore discussion):
- Working memory and the whole workspace mechanism are **removed**.
- Profiles are **files** (`profiles/*.md`), not DB rows.
- Profile selection is **manual per chat** — no auto-router.
- The extractor **stays**, slimmed to long-term-only output.
- The pipeline section is an **optional part of the profile file**, no
  separate skills library.

Existing seams this design reuses (verified in day11 code):
- `_request()` composes `[system] + [extra system blocks] + tail +
  [user]` — the profile block is one more extra block in that slot
- `parse_longterm`/`_split_pair`/`_SECTION_HEADER_RE` — the same
  sectioned-markdown parser generalizes to profile files
- `memory`/`notice`/`done` NDJSON events, `MEMORY_LOCK`, save-on-done,
  `Agent.from_snapshot` roundtrip, `FakeClient` offline harness
- day3's `step`-tagged NDJSON events + expandable phase rendering — the
  pipeline UI pattern is already proven in this repo

## Goals / Non-Goals

**Goals:**
- Profile = first-class editable file layer, bound per chat, injected
  into every request, toggleable like the other layers
- Optional `## Пайплайн` = honest orchestration (N ordered model calls),
  not a prompt trick — this is what separates «профиль» from «системный
  промпт» per the curator's clarification
- Declared vs learned: profile (user-authored) and long-term
  (agent-learned) both injected, with dedup so they don't double-record
- Observable effect: per-answer meta records the applied profile and
  steps; layer toggle gives the ±profile A/B in one chat

**Non-Goals:**
- Auto-router / profile auto-selection (rejected — manual binding only)
- Skills as separate files referenced by pipelines (profile steps are
  inline; a `skills/` library is future scope)
- Multi-user profiles / auth — single local user, many profiles
- Working memory, workspaces, promote — deleted, not replaced
- Model selection per profile (could be a profile field later; not now)

## Decisions

### D1 — Layer model: {short, longterm, profile}; working dies with workspaces

```
day11: short | working | longterm          day12: short | profile | longterm
       разговор | задача | пользователь            разговор | ЗАЯВЛЕНО | ВЫУЧЕНО
```

Everything workspace-shaped is deleted: `workspaces` table,
`sessions.workspace_id`, `_assign_workspace`/`ensure_workspace`/
`load_workspace`/`list_workspaces`/`delete_workspace`/`set_session_
workspace`/`drop_covered`, `config.workspace`, `PUT /api/working`,
`GET /api/workspaces`, `POST /api/promote`, `POST /api/workspace/delete`,
sidebar grouping, workspace datalist, `promote()`.

- Why delete, not keep-dormant: workspaces exist solely to share a task
  card between chats; without working memory they are a dead concept
  occupying half of `storage.py`, a sidebar grouping, and four endpoints.
- `covered` (the extraction cursor) survives as a plain per-session
  column `sessions.covered INTEGER DEFAULT 0` — the per-workspace map was
  only needed because several chats fed one store.
- *Rejected:* keeping working memory «for completeness» (day 11's task
  required ≥3 layers; day 12's doesn't — and the profile itself is the
  third layer, user-scoped instead of task-scoped).

### D2 — Profile store: `profiles/<slug>.md`, sectioned markdown

```markdown
# Код-ревьюер
## Профиль
- обращение: на «ты», зовут Толик
## Стиль
- тон: прямой, без комплиментов
## Формат
- ответ: вывод первой строкой, до 10 строк
## Ограничения
- не пиши код целиком — место и принцип
## Пайплайн            <- optional; presence turns the request into a chain
- разбор: проанализируй запрос и найди риски
- ответ: дай решение по разбору
- проверка: критически проверь свой ответ
```

- Same grammar as `longterm.md` — the parser is `parse_longterm`
  generalized (header `#` = display name, `## X` sections, `- k: v`
  bullets). `## Пайплайн` is special-cased: its bullets are ordered
  steps, everything else is the preference text.
- Resolved **from disk on every request** — no cache. Editing a file
  (UI or externally) affects the next turn; a deleted file degrades the
  binding to «no profile» with a meta marker.
- Caps mirror the long-term ones: ≤30 bullets/section, ≤200 chars/value,
  ≤20 KB file body, ≤8 pipeline steps.
- Why files: curator explicitly suggested «побить на файлы»; matches the
  `longterm.md` convention (visible, hand-editable, survives DB deletes);
  a directory listing IS the profile list — zero schema work.
- *Rejected:* SQLite `profiles` table (hides profiles inside the DB,
  breaks the file metaphor the course encourages); single global active
  profile (can't run two profiles side by side for the comparison).

### D3 — Binding and injection: per-chat, one dedicated system block

`sessions.profile_id` (slug string, `''` = none). `config.profile` in
`/api/chat` sets it; `configure(profile=...)` rebinds mid-chat.

```
[system] persona (agent's own system prompt)
[system] ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ «имя» — preference sections   if bound & layers.profile
[system] ДОЛГОСРОЧНАЯ ПАМЯТЬ — learned user facts           if layers.longterm
history (whole dialog)                                      if layers.short
[user] message
```

- `layers` becomes `{short, longterm, profile}` — the profile keeps the
  third toggle slot, preserving day 11's ±layer demo mechanism.
- Two controls, different jobs: binding picks WHICH profile; the toggle
  decides IF it is injected. «без профиля» + toggle-off both give the
  baseline — no redundancy in practice (toggle = quick A/B inside one
  bound chat).
- Meta per answer: `profile` (name or null), `profile_missing` flag,
  `layers`, `pipeline: [step names]` when ran, `tokens.profile` segment.
- *Rejected:* merging profile text into the persona system prompt (kills
  the toggle, the segment, and provenance — same argument as day11 D4);
  per-user global binding (chat = task context, so per-chat is the
  natural scope for «профиль под задачу»).

### D4 — Pipeline execution: sequential calls, uniform prefix, ephemeral steps

When the bound profile has `## Пайплайн` steps `[s1..sn]`, `send_stream`
runs n calls instead of one:

```
step i request:  [system persona] + [system profile prefs] + [system longterm?]
                 + [system «ШАГ i/n — <имя>: <инструкция>»]
                 + [user: <original message> + outputs of steps 1..i-1]
                 (+ short history on step 1 only — steps see the dialog
                    once, not N times)
events:          step_start{i,name} -> delta... -> step_done{i,meta}
final:           done (content = step n output) -> memory (extractor)
```

- **Uniform prefix**: every step gets persona + profile + long-term —
  «профиль подключён к каждому запросу» reads literally: a pipeline step
  IS a request. Style constraints apply to the final render; if a
  constraint harms an intermediate step that's a visible, debuggable
  behavior — the point of the demo.
- **History**: only `user + final answer` are appended (day3 precedent —
  phases are ephemeral). Intermediate outputs ride the NDJSON events and
  the run's meta, not the transcript.
- **Rollback**: history appends only after the last step completes —
  mid-pipeline failure/disconnect leaves no partial turn (day6
  semantics); the extractor then sees the usual pair.
- **Streaming**: all steps stream deltas tagged with the step id; the UI
  renders expandable phases (day3 pattern). Pipelines run inside the
  same global BUSY — a pipeline is one turn.
- *Rejected:* single call with «сначала X потом Y» prompt (that's prompt
  engineering, not orchestration — the rejected «профиль = настройки»
  reading); skills library (`skills/*.md` referenced by steps — nice but
  doubles the surface for no task-required gain); prefs only in the
  final step (special-casing for a theoretical benefit).

### D5 — Extractor: long-term only, profile-aware

The post-`done` extractor keeps its slot, prompt, and plumbing but
outputs only `ДОЛГОСРОЧНОЕ` (ЦЕЛЬ/ПЛАН/ФАКТЫ sections gone — their store
is gone). New input: the active profile's rendered text, with the rule
«already declared in the profile → do not record into long-term»
(same spirit as `drop_task_leaks`, enforced in-prompt plus a
post-parse filter against profile keys).

- `covered` per session column; backlog chunked at 12 msgs/turn;
  failure → `notice` + retry next turn — all unchanged mechanics.
- *Rejected:* dropping the extractor entirely (loses the «learned»
  personalization half and the «поверх модели памяти» premise); writing
  learned prefs INTO the profile file (declared vs learned must stay
  visibly separate — that separation is the demo).

### D6 — API surface

Kept: `GET /`, `/assets/*`, `/api/agent`, `POST /api/chat|reset|forget`,
`GET/PUT /api/longterm`. Removed: `/api/working`, `/api/workspaces`,
`/api/promote`, `/api/workspace/delete`; `config.workspace` gone.
New/changed:

- `config.profile` (slug or `""`), `config.layers {short,longterm,
  profile}` in `/api/chat`.
- `GET /api/profiles` → `[{id, name, sections, pipeline_steps}]`.
- `GET /api/profile?id=<slug>` → `{id, name, content}` (raw markdown).
- `PUT /api/profile {id?, name, content}` → create or overwrite; id
  derived by slugifying name when absent; returns the id.
- `POST /api/profile/delete {id}` → remove file; bound chats degrade to
  no-profile.
- NDJSON: `start.meta.profile`; `step_start`/`step_done` events for
  pipeline runs; `memory` event unchanged in shape minus `working`
  fields.

### D7 — Schema & file layout

```sql
sessions(session_id PK, name, model, system_prompt, default_prompt,
         profile_id TEXT NOT NULL DEFAULT '',   -- was workspace_id
         covered INTEGER NOT NULL DEFAULT 0,    -- was workspaces.covered map
         layers TEXT, stats TEXT, updated_at)
messages  -- unchanged
-- workspaces table: gone
```

`day12/profiles/` committed with seed profiles: `lakonichny.md`
(сухой стиль, списки, на «вы»), `mentor.md` (на «ты», наводящие вопросы,
развёрнуто), `reviewer.md` (код-ревью + `## Пайплайн` из 3 шагов).
`day12/memory/longterm.md` skeleton committed; `day12/data/` gitignored.

### D8 — Frontend

- Composer: profile chip «профиль: X ▾» → dropdown (профили + «без
  профиля»); chat-list rows show a profile badge; meta line shows
  profile name / «профиль не найден».
- `MemoryPanel` → three sections: **профили** (list + raw-markdown
  editor + «вставить шаблон» + delete + «новый профиль»), **долговременная**
  (unchanged), **краткосрочная** (count). Working section deleted.
- `ContextDiagram`: `working` segment → `profile` segment (same slot).
- `TokenPanel`: rows чат/память unchanged; `tokens.profile` replaces
  `tokens.working` in `breakdown()`.
- Pipeline answers: expandable phase blocks per step (step name,
  content, tokens) above the final answer — day3's phase rendering.
- `ChatList` back to a flat list (workspace grouping deleted).
- Ports: server **7871**, dev **5183**, localStorage `day12-*-v1`.

## Risks / Trade-offs

- Pipeline multiplies latency and cost per message (n calls + extractor)
  → profiles without the section are unaffected; step cap (≤8); the
  pipeline profile is opt-in by binding.
- Profile file deleted or renamed while bound → degrade to no-profile +
  `profile_missing` meta (honest signal, no silent fallback to another
  profile).
- Slug collision on rename (name → slug like day11 workspaces) → rename
  creates a new file; old one stays; documented behavior.
- Extractor may still double-record despite the dedup rule → same answer
  as day 11: visible panels + manual edit; the in-prompt rule + key
  filter makes it rare.
- Profile text competes with persona system prompt on conflicts (e.g.
  persona says «кратко», profile says «развёрнуто») → injection order
  puts profile AFTER persona (later instructions win in practice); the
  UI hint tells the user persona vs profile precedence.
- Long profile files inflate every request → caps + `tokens.profile`
  segment makes the cost visible.
- One global BUSY: a slow pipeline blocks other chats → accepted (single
  -user demo; same trade-off day 11 already took for shared stores).

## Migration Plan

None — new `day12/` folder; existing days untouched. Precondition before
forking: commit the pending day11 worktree changes so the copy starts
clean. Rollback = delete the folder + the change dir.
