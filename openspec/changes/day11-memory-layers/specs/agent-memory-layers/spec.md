# Spec Delta

## Purpose

Gives the chat agent an explicit three-layer memory model — short-term
(current dialog), working (current-task data shared by a workspace of chats),
and long-term (user profile/decisions/knowledge) — where each layer is stored
separately, the routing of new information is visible and overridable, and the
effect of each layer on answers can be observed.

## ADDED Requirements

### Requirement: Three memory layers in separate stores

The system SHALL maintain three memory layers in physically separate stores:
short-term memory (the chat's message transcript) in the per-session message
store, working memory (current-task data: goal, plan, facts) in a
workspace-scoped store, and long-term memory (user profile, decisions,
knowledge) in a standalone file independent of the session database.

#### Scenario: Layers are stored separately
- **WHEN** a chat has produced turns that yielded task data and user-level
  facts
- **THEN** the transcript, the working task data, and the long-term file each
  contain their respective data, and deleting the chat removes only the
  transcript

#### Scenario: Long-term survives everything
- **WHEN** a session is reset, forgotten, or the server restarts
- **THEN** the long-term memory content is unchanged and still injected into
  subsequent requests

### Requirement: Short-term memory is the whole current dialog

Every request SHALL include the chat's full message history verbatim (bounded
only by the global history cap), with no windowing or summarization applied.

#### Scenario: Early context is recalled
- **WHEN** the user states a fact in an early message and asks about it many
  turns later within the history cap
- **THEN** the agent answers using that fact because the full transcript was
  sent

### Requirement: Working memory is scoped to a workspace

Each chat SHALL belong to a workspace; working memory SHALL be stored per
workspace so that all chats in the same workspace share one task state, and
chats in different workspaces do not see each other's working memory.

#### Scenario: Two chats share a task
- **WHEN** chat A and chat B belong to the same workspace and a turn in chat A
  adds a task fact to working memory
- **THEN** a subsequent request in chat B includes that fact in its working
  memory block

#### Scenario: Different tasks stay separate
- **WHEN** chat C belongs to a different workspace than chats A and B
- **THEN** requests in chat C contain none of A/B's working memory

### Requirement: Automatic memory extraction after each answer

After every completed answer the system SHALL run an extraction step that
classifies newly stated information as task-relevant (written to the chat's
workspace working memory) or user-level (appended to the long-term file),
deduplicating against existing entries. Information that fits neither layer
SHALL NOT be persisted.

#### Scenario: Classification lands data in the right layer
- **WHEN** the user states a task deadline and a personal stack preference in
  one dialog
- **THEN** the deadline appears in the workspace's working memory and the
  stack preference appears in the long-term file

#### Scenario: Extraction failure is non-fatal
- **WHEN** the extraction step fails or returns an unparseable result
- **THEN** the answer is still delivered, a notice is emitted, stored memory
  is left untouched, and extraction is retried after the next answer

#### Scenario: Catch-up after joining a workspace
- **WHEN** a chat with existing history is assigned to a workspace it was not
  part of
- **THEN** the next completed answer folds that chat's not-yet-processed
  history into the shared working memory

### Requirement: User can inspect and override every layer

The system SHALL expose each layer's contents and let the user: edit the
working memory (goal, plan, facts), edit the long-term memory content,
delete stored items, and promote a working-memory item into long-term memory.

#### Scenario: Promote a fact to long-term
- **WHEN** the user promotes a working-memory fact
- **THEN** that fact is added to the long-term file and persists across
  chats and restarts

#### Scenario: Manual edit is honored
- **WHEN** the user edits the long-term content or working memory directly
- **THEN** subsequent requests inject the edited content

### Requirement: Per-request layer toggles

For each request the user SHALL be able to enable or disable each of the
three layers independently; disabled layers are excluded from the request,
and the response metadata SHALL report which layers were active and the
token estimate per layer.

#### Scenario: Effect of a layer is observable
- **WHEN** the user asks the same question once with long-term memory enabled
  and once with it disabled
- **THEN** the two requests differ by exactly the long-term block, and each
  answer's metadata records the active layers

### Requirement: Memory state is visible

The UI SHALL show the contents of all three layers (long-term file content,
the workspace's goal/plan/facts, and the short-term message count) and SHALL
visualize the composition of the next request broken down by layer.

#### Scenario: Next-request composition is shown per layer
- **WHEN** the user opens the memory/context panel after some turns
- **THEN** it displays separate segments for system, long-term, working,
  history, and request portions

### Requirement: Workspace lifecycle

A new chat SHALL receive its own private workspace by default. Assigning a
chat to an existing workspace SHALL share that workspace's working memory. A
workspace SHALL persist after its chats are deleted and remain available for
reuse. Deleting a workspace SHALL clear its working memory and return its
member chats to private workspaces.

#### Scenario: Task outlives its dialog
- **WHEN** all chats of a workspace are deleted and a new chat is assigned to
  that workspace
- **THEN** the new chat's requests include the retained working memory

#### Scenario: Deleting a workspace clears the task
- **WHEN** a workspace is deleted
- **THEN** its working memory is removed and its former chats no longer share
  task state

### Requirement: Persistence across restarts

Working memory, workspace membership, and extraction progress SHALL be
persisted so that after a server restart, chats resume with the same layered
memory state.

#### Scenario: Restart preserves layers
- **WHEN** the server restarts after turns that populated all layers
- **THEN** reloading a chat restores its transcript, workspace link, and
  working memory, and the long-term file is unchanged
