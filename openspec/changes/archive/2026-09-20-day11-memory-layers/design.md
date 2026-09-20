# Design

## Context

See proposal.md — Why. Base: `day10/` (latest lineage: Agent + SQLite
persistence + token accounting + right-sidebar panels + `facts.py` extractor +
fork/strategies). Day 11 keeps the substrate and replaces the context-strategy
machinery with a layered memory model.

Existing seams this design reuses (verified in day9/day10 code):
- `history` + `messages` table = the verbatim transcript (never deleted)
- `facts.py` pattern: state dict → post-`done` updater generator → `notice` on
  failure → `*_calls` totals bucket → JSON column in `sessions` → snapshot
  roundtrip → panel fed by a post-done NDJSON event
- `_request()` composes `[system] + [extra system block] + tail + [user]`;
  the `extra` slot and `breakdown()`'s 4 segments generalize to N layers
- `AgentRegistry` LRU + per-session `BUSY` lock; `STORE.save` after `done`;
  `resolve_agent` restore path; `FakeClient` offline test harness

## Goals / Non-Goals

**Goals:**
- Three memory layers differentiated by **scope/lifetime**, stored in
  **separate stores**, each visible and editable in the UI
- Explicit routing: automatic LLM classification + user override/edit/promote
- Observable effect: per-request layer toggles + per-layer token segments
- Workspace as the "task" scope: one working store shared by several chats

**Non-Goals:**
- Context strategies (window/facts/branches) and fork — removed; the memory
  model replaces them (`window_size` dropped; short-term = whole dialog)
- Vector/embedding/semantic-search memory — plain structured stores only
- Tool-call / function-calling memory writes mid-generation — writes are a
  post-turn batch step (inspectable, provider-agnostic)
- Multi-user separation — single local user; long-term is one shared file
- Retro-spec'ing days 1–10, task state machine / invariants (later days)

## Decisions

### D1 — Layer model: three stores differing by scope, same KV-ish shape

| Layer | Scope / lifetime | Store | Writer | Injection |
|---|---|---|---|---|
| short-term | this chat | `messages` table | automatic (every msg) | verbatim history |
| working | the task (workspace) | `workspaces` row (JSON) | LLM extractor + user | system block |
| long-term | the user, forever | `memory/longterm.md` file | LLM extractor + user | system block |

Working = task card `{goal: str, plan: [str], facts: [[k,v]]}` + `covered`
map. Long-term = markdown file with fixed sections (`## Профиль`,
`## Решения`, `## Знания`) holding `- ключ: значение` bullets.

- Why separate stores, not one blob: the task literally requires it, and
  different lifetimes make different stores natural (file survives DB deletes).
- Why MD for long-term: lecture-faithful (profiles live in MD files, injected
  into system prompt), user-openable/editable outside the app, and it makes
  "this layer outlives everything" physically obvious.
  - *Rejected:* all-SQLite long-term (uniform but less demonstrable, hides the
    store boundary); all-files (breaks repo convention for messages/sessions).
- Why task-card + KV for working, not plain KV: foreshadows the week's
  state-machine days; `goal`/`plan` are the fields a task needs anyway.
  - *Rejected:* free-text scratchpad (weak demo), pure KV (less structure).

### D2 — Workspace entity carries working scope

A task ≠ a chat. `workspaces(workspace_id PK, name, state JSON, covered JSON,
updated_at)`; `sessions.workspace_id` (default = the session's own id ⇒
private working memory is the degenerate case, zero extra ceremony).

- New chat → private workspace auto-provisioned on save.
- Sharing = explicit: user sets a chat's workspace name in settings
  (`config.workspace`, resolved by slug, created if absent). On reassign the
  chat's `covered` entry resets to 0 → next turn folds its history into the
  shared store. This is a feature: "attach chat to task → task absorbs it".
- Workspaces persist independently of chats (a task outlives its dialogs;
  reattach a fresh chat later). Explicit `delete` clears a workspace and
  reverts its chats to private workspaces. `reset`/`forget` on a chat drop
  only that chat's `covered` entry — the shared working state is untouched.
- *Rejected:* per-chat working (doesn't cover "2 chats, 1 task" — the user's
  own scenario); single global working store (parallel tasks contaminate).

### D3 — Routing: post-done LLM extractor + explicit user gestures

After each `done` (inside `send_stream`, same slot day10 used for
`_update_facts`), one non-streaming `complete()` call at temperature 0 gets
`current working state` + `current long-term items` + newly uncovered
messages, and returns a structured plain-text reply:

```
ЦЕЛЬ: ...
ПЛАН:
- шаг
ФАКТЫ:
ключ: значение
ДОЛГОСРОЧНОЕ:
ключ: значение
```

Parsed tolerantly (day10 `parse_facts` lineage — bullets stripped,
colon-split, capped; no `response_format` — provider-agnostic by choice).
Classification rule in the prompt: task-relevant (цель, шаги, дедлайны,
ограничения задачи) → working; user-level (профиль, стек, предпочтения,
общие решения/знания) → long-term. Long-term writes dedupe by key
(replace same-key line) into the file under its section.

- `covered` is a **per-session map inside the workspace row**
  (`{session_id: int}`) — each chat folds its own uncovered messages into the
  shared store; chunk at 12 msgs/turn for backlog catch-up (day10 pattern).
- Failure → `notice` event, state untouched, retried next turn.
- User gestures (the "явно выбираешь" half): edit working goal/plan/facts,
  edit the long-term file, delete items, «→ в долговременную» promote button
  on each working fact.
- *Rejected:* user-only writes (less agentic); proposals-inbox (friction);
  mid-generation tool calls (hidden writes hurt visibility, provider
  variance).

### D4 — Injection: separate system blocks + per-request toggles

```
[system: persona]
[system: ДОЛГОСРОЧНАЯ ПАМЯТЬ — file content]     if layers.longterm
[system: РАБОЧАЯ ПАМЯТЬ — goal/plan/facts]       if layers.working
history (whole dialog, MAX_TURNS-bound)          if layers.short
[user message]
```

`layers` = `{short, working, longterm}` booleans in agent config (all default
on), sent per message like the rest of config. Toggling off short-term gives
a stateless agent — a free demo. Each block renders as its own system message
(provenance + togglability visible). `breakdown()`/ContextDiagram generalize
to 5 segments: `system/longterm/working/history/request`.

- *Rejected:* merge memory into the persona system prompt (kills toggles and
  segment visibility).

### D5 — Schema & file layout

```sql
sessions(…, workspace_id TEXT NOT NULL DEFAULT '')      -- +1 column
workspaces(workspace_id TEXT PRIMARY KEY, name TEXT NOT NULL,
           state TEXT,          -- JSON {goal, plan, facts}
           covered TEXT,        -- JSON {session_id: int}
           updated_at REAL NOT NULL)
messages  -- unchanged
```

`day11/memory/longterm.md` committed as a skeleton (three section headers) —
demonstrates the format; runtime writes append bullets. `day11/data/` +
`day11/memory/*.md` gitignore decision: `data/` ignored (day7+ convention);
`longterm.md` skeleton committed, accumulated content is demo data (user's
call at commit time).

### D6 — API surface

Existing kept: `GET /`, `GET /assets/*`, `GET /api/agent`, `POST /api/chat`,
`/api/reset`, `/api/forget`. Removed: `/api/fork`, strategy/window in
`parse_config`. New/changed:

- `config` in `/api/chat` gains `workspace` (name string) and `layers`
  ({short,working,longterm}); drops `strategy`/`window_size`.
- `GET /api/longterm` → `{content, sections}`; `PUT /api/longterm {content}`
  → rewrites file (global file lock).
- `GET /api/workspaces` → list for the picker (workspaces outlive chats).
- `PUT /api/working {session_id, goal?, plan?, facts?}` → patch workspace
  state of the chat's workspace.
- `POST /api/promote {session_id, key}` → move working fact → longterm.md.
- `POST /api/workspace/delete {workspace_id}` → clear store; member chats
  revert to private workspaces.
- NDJSON: `facts` event replaced by `memory` event `{workspace, working,
  longterm_added, covered, context_preview, totals}`; `notice`/`error` kept.

### D7 — No runtime concurrency: generations serialize globally

One generation at a time for the whole app: a global busy flag → 409 while
ANY turn (incl. its extraction step) is running — day6's model, replacing
day10's per-session lock. Rationale: the shared stores (workspace row,
`longterm.md`) make concurrent turns a real write race; serializing removes
it with less code than granular locks, and parallel generation is useless in
a single-user demo. One small `MEMORY_LOCK` still guards every write to the
workspace row / file so a user edit (PUT/promote) can't clobber a running
extraction — ~10 lines total.

NB: "parallel" in tasks.md refers to implementation streams (subagents), not
runtime behavior.

### D8 — Meta/totals/frontend

- `meta`: `layers` used, `workspace` name, `tokens.{system,longterm,working,
  history,request,…}` (replaces `extra`), working item count, longterm chars.
- `totals`: `{chat: bucket, memory_calls: bucket}` — per-strategy buckets die.
- `ContextDiagram`: 5 segments. `TokenPanel`: two rows (чат / память).
- `FactsPanel` → `MemoryPanel`: three sections — долговременная (file view →
  textarea edit → PUT), рабочая (goal/plan/facts editable, per-fact promote),
  краткосрочная (message count; lives only here).
- `ChatList`: chats grouped under workspace headers («+ чат» in a workspace
  creates a chat already linked to it).
- `SettingsPanel`: workspace name input (datalist of existing), three layer
  checkboxes; strategy seg + window input removed.
- Welcome screen examples updated to memory-themed prompts.

## Risks / Trade-offs

- Extractor misclassifies the working↔long-term boundary → user override via
  edit/promote/delete; prompt carries explicit criteria; errors are visible,
  not silent (that's the point of the panels).
- Long-term file grows unbounded over many sessions → extractor caps items
  (e.g. ≤30 bullets, ≤4000 chars, drop oldest/least relevant); same-day demo
  scope makes this safe.
- User edits `longterm.md` into a weird shape → tolerant parse; raw content
  still injected verbatim; invalid lines just don't appear as parsed items.
- Parallel extraction into shared workspace → per-workspace lock; last merge
  wins (LLM merges against latest state, acceptable at demo scale).
- Config-driven workspace assign by NAME: typo creates a new workspace →
  datalist of existing names + slug normalization; explicit assign endpoint
  rejected as redundant.
- Workspace name rename = new workspace (name is the key) → acceptable;
  documented, not silently "fixed".

## Migration Plan

None — new `day11/` folder; existing days untouched. Rollback = delete the
folder + the change dir.
