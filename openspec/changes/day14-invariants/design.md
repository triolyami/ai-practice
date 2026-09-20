# Design

## Context

Day 12 shipped the newest agent kernel in the repo: `Agent` (persona +
history + streaming `send_stream`), per-chat file-bound profiles,
long-term extractor, SQLite persistence, React chat UI with right
sidebar panels. Day 14 needs none of the memory/profile machinery — only
the kernel plus a *rules* layer. Confirmed with the user: fork day12,
strip `profiles.py` / `memory.py` / pipelines, repurpose the
file-store + binding + editor-panel machinery into invariants.

The lecture's teaching point: a text rule in a prompt is breakable —
"двойная защита" = inject AND check the reply deterministically.

## Goals / Non-Goals

**Goals:**
- Invariant sets as editable files outside the dialog, bound per chat
- Prompt injection + deterministic post-check, compared across
  off | prompt | enforce
- Observable conflict behavior: refusal protocol, violation badges,
  blocked-attempt transparency

**Non-Goals:**
- LLM-as-judge semantic checking (cost + nondeterminism; the point is the
  deterministic guarantee)
- Request-side prefiltering (kills the refusal-explanation observation
  the task wants)
- Task state machine / profiles / memory (days 12/13, out of scope here)
- Semantic coverage of checks beyond what the file's author writes as
  regexes — the gap itself is a demo finding

## Decisions

### Invariant files reuse the profile grammar + `## Проверки`

`# Name` / `## Section` + `- key: value` bullets for human-readable rules
(rendered verbatim into the prompt block); `## Проверки` + `- бан: re` /
`- бан-код: re` for machine checks. One file = semantic rules AND their
deterministic checks, single source of truth, disk re-read per request.

*Alternatives rejected:* inline `| check:` per bullet (harder to parse,
mixes layers); separate checks file (two sources of truth); LLM-judge
(see Non-Goals); request prefilter (see Non-Goals).

### Two lint scopes + refusal exemption

`бан` scans the whole reply (business rules live in prose); `бан-код`
scans fenced code blocks only, fence lang tag included (prose may
legitimately *discuss* banned tech). Replies starting with `ОТКАЗ` skip
lint entirely — a refusal must name what it refuses.

*Rejected:* whole-reply-only scanning (false-positives on
"не использую RxJava" prose); code-only scanning (misses business-rule
violations); linting refusals anyway (a refusal containing banned words
is correct behavior).

### Refusal protocol is a deterministic prefix

Injected instruction: on conflict, start with `ОТКАЗ:`, cite the violated
invariant, offer the closest allowed alternative. Prefix detection is a
string check — drives the UI badge, the lint exemption, and the meta
flag. *Rejected:* JSON/marker tags (fragile, less readable in chat).

### Enforce streams, marks, retries — never buffers

Attempts stream to the UI normally (chosen by user over buffering). On
lint hit: the streamed attempt is marked «заблокировано», stays collapsed
in the transcript via `meta.blocked_attempts`, is excluded from model
history, and one retry runs with a feedback system note listing the
violated checks. Second failure → committed synthesized `ОТКАЗ`.
Trade-off accepted: violating content is transiently visible — the
slip→catch→fix drama IS the demo; strict never-render enforcement would
require buffering and loses live streaming in enforce mode.

### History commits only the final answer

Blocked attempts never enter `history` (model never sees its own
violation); they persist in `meta.blocked_attempts` so reloads keep the
story. Same pattern as day12's pipeline (commit after last step only).

### Modes live on the session, like day12's binding

`sessions.enforce` (`off|prompt|enforce`, default `prompt`) +
`sessions.invariant_id`. Both via `configure()`, both re-validated per
request. Lint always runs when a set is bound and mode != off; the mode
decides the consequence (badge vs block).

### Keep tokens/context diagram; drop the extractor

`tokens.py` gains an `invariants` breakdown segment — the diagram shows
the invariant block entering the request (visualizes "stored separately,
explicitly considered"). The day12 extractor + `memory`/`summary` events
are deleted entirely.

## Risks / Trade-offs

- **Semantic invariants slip past regex** ("only MVI" can't be regexed
  reliably) → prompt layer is the only guard there; that's the honest
  finding the comparison demonstrates. `prompt` mode's detector badges
  make slips visible.
- **Over-refusal** (model refuses innocent requests) → observable via
  отказ badges; probe «почему RxJava хуже корутин» tests it.
- **ОТКАЗ smuggling** (model prefixes `ОТКАЗ:` then emits violating code)
  → documented trust hole; could re-lint refusals later if it matters.
- **Streamed violation seen briefly** → accepted trade-off (see
  Decisions); documented in README.
- **Feedback retry cost** → one extra call max per turn; totals bucket
  counts it.

## Open Questions

(none — all decisions confirmed with the user)
