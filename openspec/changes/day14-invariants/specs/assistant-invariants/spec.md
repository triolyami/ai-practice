# Spec Delta

## Purpose

Lets a chat assistant operate under named invariant sets (architecture,
stack, business rules) stored as files outside the dialog, injected into
every request, and deterministically enforced on responses — with
observable refusal behavior when a request conflicts with an invariant.

## ADDED Requirements

### Requirement: Invariant sets are stored as files separate from the dialog

Invariant sets SHALL live as markdown files under `day14/invariants/<slug>.md`
using the sectioned grammar (`# Name`, `## Section` with `- key: value`
bullets) plus an optional `## Проверки` section holding machine-checkable
rules (`- бан: <regex>` applies to the whole reply, `- бан-код: <regex>`
applies to fenced code blocks only). Files SHALL be re-read from disk on
every request so external or UI edits take effect on the next turn. CRUD
SHALL be available through the API (`GET /api/invariants`,
`GET /api/invariant?id=`, `PUT /api/invariant`, `POST /api/invariant/delete`)
and through a sidebar editor panel.

#### Scenario: File edit reaches the next request

- **WHEN** a user edits an invariant file (UI panel or external editor)
  and then sends a message in a chat bound to that set
- **THEN** the request contains the updated invariant text

#### Scenario: Deleted bound file degrades honestly

- **WHEN** the file for a chat's bound invariant set is deleted and the
  user sends a message
- **THEN** the request goes out without an invariants block and the
  answer meta reports the set as missing (`invariant_missing`)

#### Scenario: Invalid check regex does not break the request

- **WHEN** a `## Проверки` line contains an invalid regex
- **THEN** that check is skipped, the request proceeds, and the set's
  listing marks the broken check

### Requirement: Invariants are bound per chat and injected into the request

Each chat SHALL have an `invariant_id` binding (empty = none) selectable
via the composer chip. When bound and enforcement is not `off`, the
request SHALL include a dedicated system block containing the invariant
text and the refusal protocol; the context diagram SHALL show the
invariants segment. Binding SHALL persist across server restarts.

#### Scenario: Same request, different bound sets

- **WHEN** two chats bound to different invariant sets receive the same
  conflicting request
- **THEN** each answer reflects its own set's rules (different refusals
  or answers)

#### Scenario: Unbound chat has no invariants

- **WHEN** a chat has no invariant binding (or mode `off`)
- **THEN** no invariants block is sent and no lint runs

### Requirement: Enforcement is a three-level mode

Each chat SHALL have an enforcement mode `off | prompt | enforce`
(default `prompt`). `off`: invariants are not injected and lint does not
run. `prompt`: invariants are injected and lint runs as a detector —
violating replies pass through marked with violation badges.
`enforce`: invariants are injected and a lint hit triggers the retry
loop. Mode SHALL be changeable mid-chat and recorded in each answer's
meta.

#### Scenario: Prompt mode marks but passes a violating reply

- **WHEN** mode is `prompt`, a set with a `бан-код` check is bound, and
  the model replies with code matching the check
- **THEN** the reply is delivered and its meta lists the violations

#### Scenario: Off mode ignores invariants entirely

- **WHEN** mode is `off` and a set is bound
- **THEN** the request has no invariants block and no violation data
  appears in meta

### Requirement: Deterministic lint checks the reply

After each model reply, lint SHALL evaluate the bound set's checks:
`бан` patterns against the full reply text, `бан-код` patterns against
fenced code blocks (fence language tag included). Replies beginning with
`ОТКАЗ` SHALL be exempt from lint. Results SHALL be reported as a list of
matched checks with the matched text.

#### Scenario: бан-код ignores prose mentions

- **WHEN** a reply discusses a banned library in prose without code
  blocks
- **THEN** `бан-код` checks produce no hits

#### Scenario: Refusal is never linted

- **WHEN** a reply starts with `ОТКАЗ` and names a banned word inside the
  explanation
- **THEN** lint reports zero hits

### Requirement: Conflicting requests produce a refusal

The injected invariants block SHALL instruct the model: if fulfilling the
request would violate an invariant, begin the reply with `ОТКАЗ:`, name
the violated invariant, and offer the closest allowed alternative. The
UI SHALL render `ОТКАЗ` replies with a refusal badge.

#### Scenario: Direct conflict yields explained refusal

- **WHEN** a user asks for a Python service while the bound set requires
  Kotlin only
- **THEN** the reply starts with `ОТКАЗ:`, cites the stack invariant, and
  proposes the Kotlin alternative

#### Scenario: Discussion is not a proposal

- **WHEN** a user asks why a banned library is inferior (a discussion,
  not a request for violating output)
- **THEN** the assistant answers normally without refusing

### Requirement: Enforce mode retries once, then synthesizes a refusal

In `enforce` mode, a reply with lint hits SHALL be marked blocked, SHALL
NOT enter dialog history, and SHALL trigger exactly one retry: the same
request plus a feedback system note listing the violated checks. If the
retry also violates, the committed answer SHALL be a server-synthesized
`ОТКАЗ` refusal naming the violated checks (meta marks it synthesized).
Blocked attempt content SHALL persist in the committed answer's meta.

#### Scenario: Slip is caught and corrected

- **WHEN** mode is `enforce` and the model's first reply contains a
  banned code pattern
- **THEN** the attempt is marked blocked, a retry runs, and a clean or
  refusal answer is committed

#### Scenario: Persistent violator gets synthesized refusal

- **WHEN** both the first attempt and the retry violate
- **THEN** the committed answer is a synthesized refusal and meta reports
  `attempts: 2` and `synthesized: true`

### Requirement: Invariant application is observable

Each answer's meta SHALL record the bound set (id/name/missing),
enforcement mode, lint violations, attempt count, and whether the answer
was synthesized or a refusal. The UI SHALL show badges for refusal /
violation / blocked / verified states and a collapsed view of blocked
attempts.

#### Scenario: Meta documents the enforcement story

- **WHEN** an answer was produced after a blocked attempt
- **THEN** its meta shows `attempts: 2`, the violated checks, and the
  blocked attempt content
