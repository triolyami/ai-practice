# Proposal

## Why

Day 14 task (verbatim):

> День 14. Инварианты и ограничения состояния. Добавьте в ассистента
> инварианты, которые он не имеет права нарушать. Примеры инвариантов:
> выбранная архитектура, принятые технические решения, ограничения по стеку,
> бизнес-правила. Сделайте так, чтобы: инварианты хранились отдельно от
> диалога; ассистент явно учитывал их в рассуждениях; ассистент отказывался
> предлагать решения, которые их нарушают. Проверьте: что происходит при
> конфликте запроса и инварианта; как ассистент объясняет отказ.

The week builds a stateful agent piece by piece: day 12 did declared
personalization (profiles), day 13 (state machine) was done elsewhere.
Day 14 adds the third piece — **invariants**: rules the assistant may not
break. The lecture's core lesson is double protection: invariants injected
into the prompt are breakable text rules, so a deterministic response check
(the "линтер") must back them. The comparison axis (repo convention) is the
enforcement ladder: off → prompt-only → prompt+lint.

## What Changes

- New `day14/` app, forked from `day12/` skeleton: `Agent` + registry +
  SQLite persistence + busy-lock + `tokens.py` + `config.py` + React
  frontend. **Removes**: user profiles (`profiles.py`, `profiles/`,
  `## Пайплайн` execution, `/api/profile*`), long-term memory extraction
  (`memory.py`, `memory/longterm.md`, post-`done` extractor, `memory`
  events), the profile context-diagram segment, and per-chat profile
  binding.
- **Invariant sets as files**: `day14/invariants/<slug>.md`, same sectioned
  markdown grammar as day12 profiles (`# Имя`, `## Секция` + `- ключ:
  значение`), plus a machine-checkable `## Проверки` section (`- бан:
  <regex>` scans the whole reply, `- бан-код: <regex>` scans fenced code
  blocks only). CRUD via UI and API; files re-read from disk on every
  request.
- **Binding per chat** (`sessions.invariant_id`): composer chip picker
  («без инвариантов» option); deleted file degrades honestly via meta.
- **Enforcement modes** per chat (`sessions.enforce`): `off` (invariants
  not injected, baseline) | `prompt` (injected; lint marks violations but
  passes the reply) | `enforce` (injected; violations trigger one retry
  with feedback, then a server-synthesized refusal).
- **Refusal protocol**: the injected block instructs the model to start a
  refusal with `ОТКАЗ:`, cite the violated invariant, and offer the closest
  allowed alternative. `ОТКАЗ`-prefixed replies are exempt from lint (a
  refusal may name what it refuses).
- **Retry loop in Agent**: on lint hits in enforce mode the failed attempt
  streams visibly, is marked «заблокировано», is retried once with a
  feedback system note, and on a second failure is replaced by a
  synthesized refusal. Only `user + final answer` enter history; blocked
  attempts persist in the answer's meta.
- Frontend: `InvariantsPanel` (list/raw-markdown editor/template/delete),
  composer invariant chip + enforce mode seg control, answer badges
  (отказ / нарушение / заблокировано / проверено), collapsed blocked
  attempts, one-click conflict probes, context diagram segment
  «инварианты».
- Seed invariant sets committed: `android-mvi.md` (Kotlin/Compose/MVI,
  no-RxJava/Dagger — the lecture's example) and `dostavka-msk.md`
  (business rules: Moscow-only delivery, free APIs).

## Capabilities

### New Capabilities

- `assistant-invariants`: invariant sets stored as files separate from the
  dialog, injected into every request under a bound chat, deterministically
  checked on responses, with refusal and retry behavior on conflict —
  across three enforcement levels for comparison.

### Modified Capabilities

(none — day14 is a self-contained app; day11/12 capabilities stay untouched)

## Impact

- New folder `day14/` (Python stdlib server on port 7872, Vite dev on
  5184, committed `frontend/dist/`); new SQLite DB `day14/data/` (gitignored).
- New API surface: `GET /api/invariants`, `GET /api/invariant?id=`,
  `PUT /api/invariant`, `POST /api/invariant/delete`; `config.invariant` and
  `config.enforce` on `/api/chat`; new NDJSON event `violation`; extended
  `done` meta (`invariant`, `enforce`, `violations`, `attempts`,
  `synthesized`).
- No changes to existing days; `lab/` untouched.
