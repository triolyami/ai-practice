# Spec Delta

## Purpose

Gives the chat agent user-level personalization on top of its memory
model: editable user-profile files bound per chat and injected into every
request, an optional per-profile pipeline that turns one user request
into an ordered chain of model calls, and a clear separation between
declared preferences (the profile) and learned ones (long-term memory).

## ADDED Requirements

### Requirement: User profiles live in files with a sectioned format

The system SHALL store user profiles as separate files
(`day12/profiles/<slug>.md`), one file per profile, in a sectioned
markdown format: preference sections (`## Профиль`, `## Стиль`,
`## Формат`, `## Ограничения`, and any extra sections) holding
`- ключ: значение` bullets, plus an optional `## Пайплайн` section
holding ordered `- имя: инструкция` steps. Profiles SHALL be re-read
from disk when a request is built, so editing a file (in the UI or
externally) affects the next request without a restart.

#### Scenario: Profiles persist outside the database

- **WHEN** the server restarts or a session row is deleted
- **THEN** all profile files are unchanged and still usable

#### Scenario: External edit takes effect

- **WHEN** a profile file is edited on disk while its chat exists
- **THEN** the next request in that chat injects the edited content

### Requirement: A chat is bound to a profile, injected into every request

Each chat SHALL bind to at most one profile (`sessions.profile_id`,
empty = no profile). Every request in that chat SHALL include the bound
profile rendered as its own system message (separate from the agent
persona prompt and the long-term memory block). The answer metadata
SHALL record which profile (if any) was applied.

#### Scenario: Different profiles produce different answers

- **WHEN** two chats bound to different profiles receive the same user
  message
- **THEN** the two requests differ by exactly the profile block, and each
  answer's metadata names the profile that produced it

#### Scenario: Switching profile mid-chat

- **WHEN** the user changes a chat's bound profile after some turns
- **THEN** subsequent requests use the new profile while earlier answers
  keep their original profile metadata

### Requirement: Profile is a per-request toggleable layer

The request layer toggles SHALL be `{short, longterm, profile}`. When the
profile layer is disabled or no profile is bound, the profile block is
absent from the request; metadata SHALL report the active layers.

#### Scenario: Profile effect is observable

- **WHEN** the same message is sent once with the profile layer on and
  once with it off (profile still bound)
- **THEN** the two requests differ by exactly the profile block, and each
  answer's metadata records the active layers

### Requirement: Optional profile pipeline orchestrates the answer

When the bound profile contains a non-empty `## Пайплайн` section, a user
request SHALL execute its steps in order: one model call per step, where
each step receives the step instruction and the outputs of the previous
steps. Step progress SHALL be streamed as distinguishable events, and the
final step's output SHALL be the delivered answer. A profile without the
section produces a normal single-call answer.

#### Scenario: Pipeline steps run in declared order

- **WHEN** a chat is bound to a profile whose `## Пайплайн` lists steps
  «разбор», «ответ», «проверка» and the user sends a message
- **THEN** three model calls happen in that order, each step's streamed
  output is shown under its own phase, and the «проверка» output is the
  visible final answer

#### Scenario: Transcript keeps only the user turn and final answer

- **WHEN** a pipeline run completes
- **THEN** the stored history gains exactly one user message and one
  assistant message (the final step's output); intermediate step outputs
  do not enter the transcript or later requests

#### Scenario: Pipeline failure keeps history clean

- **WHEN** a step in the middle of a pipeline fails or the client
  disconnects
- **THEN** no partial turn is appended to the transcript (same rollback
  semantics as a failed single-call turn)

### Requirement: Learned memory stays separate from declared preferences

The post-answer extraction step SHALL update only long-term memory
(no working-memory output). The extractor SHALL receive the active
profile's content and SHALL NOT record into long-term memory preferences
or facts already declared in the profile. The extraction cursor SHALL be
tracked per session so a chat's backlog is processed in bounded chunks
after each answer.

#### Scenario: New user fact is learned

- **WHEN** the user states a durable preference that is not declared in
  the bound profile
- **THEN** the extraction step appends it to the long-term file, and a
  later request (in any chat) includes it

#### Scenario: Declared preference is not re-recorded

- **WHEN** the user repeats something already declared in the bound
  profile (e.g. «отвечай списком» when the profile declares that format)
- **THEN** the long-term file is unchanged by that turn

### Requirement: Profiles are inspectable, editable, and deletable in the UI

The UI SHALL list all profiles, show which profile each chat is bound to,
let the user create a profile (from a template), edit it as raw markdown,
and delete it. Deleting a profile that chats are bound to SHALL be
graceful: those chats continue without a profile block and their metadata
reports the missing profile.

#### Scenario: Bound profile is deleted

- **WHEN** a profile file is deleted while a chat still references it
- **THEN** the next request in that chat is sent with no profile block
  and the answer metadata marks the profile as missing

### Requirement: Layered memory substrate is retained without working memory

The agent SHALL keep two memory layers beneath personalization: the
short-term transcript (whole dialog, verbatim) and the long-term file.
Working memory and its workspace scope SHALL NOT exist in day12: there is
no workspace entity, no task card, and no shared per-task state between
chats.

#### Scenario: No workspace machinery remains

- **WHEN** a chat is created, listed, or configured
- **THEN** there is no workspace field, grouping, or endpoint — chats are
  a flat list and memory state is per-session plus the shared long-term
  file
