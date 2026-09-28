# Design

## Context

See proposal.md for the task text and motivation. Current state that
shapes the approach:

- `day18/` is a copy-forward stack: `ThreadingHTTPServer` app +
  `Agent` with a bounded tool-call loop (`MAX_TOOL_ROUNDS = 5`), an
  `MCPHub` daemon-thread owning one asyncio loop and one `mcp.Client`
  per registry entry, and a React chat UI that already renders
  `tool_call` / `tool_result` phases. Day19 keeps the machinery but
  trims `MCP_SERVERS` to the single `pipeline` server (user request,
  post-implementation): the day-17/18 demo servers (py-tools,
  ts-tools, tracker, scheduler), their files, the scheduler watcher
  and the «сводка» pinned chat were removed so the lane-1 model sees
  only the chain's tools.
- Every executed call lands in `meta.tool_calls` as
  `{name, server, tool, arguments, ok, preview, latency_ms}` — `preview`
  is truncated at `TOOL_PREVIEW` chars, `arguments` is full.
- Day 17 verified live that `deepseek-v4-flash`/`deepseek-v4-pro` drive
  tool calls; glm models were untested (401, Z.ai balance).
- `deepseek` key lives in root `.env` (`DEEPSEEK_API_KEY`); config reads
  env at import, so a server restart is required after editing `.env`.

The conceptual frame (agreed with the user): MCP tools are isolated —
a tool cannot call another tool. **Composition is a host-side concern**:
whoever holds the sessions carries stage N's output into stage N+1's
arguments. The day's experiment compares *who* orchestrates.

## Goals / Non-Goals

**Goals:**
- One pipeline, three orchestration lanes, one measurable difference:
  - **Lane 1 — LLM-orchestrated**: the model chains the three tools
    inside a normal chat turn (existing loop; nothing new in the agent).
  - **Lane 2 — code-orchestrated**: `POST /api/pipeline` calls the three
    tools in sequence through the hub, piping outputs verbatim.
  - **Lane 3 — composite control**: `run_pipeline` on the MCP server
    calls the handlers internally; demonstrates that server-side
    "composition" never crosses a tool boundary, so the data-passing
    check is undefined for it.
- A per-run, per-hop **fidelity verdict** (`exact` / `differs` /
  `not-applicable`) computed from recorded hashes — this is the task's
  «корректность передачи данных» made testable.

**Non-Goals:**
- No graph/DAG of tools, no arbitrary pipeline definitions — the chain
  is fixed to the task's three stages.
- No MCP-native composition tricks (sampling, roots, elicitation) —
  the protocol has no tool-chaining concept; that absence is a finding,
  not a gap to fill.
- No programmatic tool calling ("code mode": model writes a script that
  calls the tools in a sandbox) — real pattern, but out of scope for
  this day.
- No new persistence: pipeline runs are ephemeral; chat turns keep the
  existing meta-only storage. `day19/out/` holds generated files only.

## Decisions

### The orchestrator comparison is the deliverable

Three lanes over the same four tools, deliberately arranged so the data
path differs per lane:

```
  lane                orchestrator      hop N -> N+1 data path
  ------------------  ----------------  ------------------------------
  1 LLM chain         model in turn     result -> context -> model
                                        retypes it as next arguments
                                        (lossy by design)
  2 code chain        /api/pipeline     result -> python var -> args
                                        (byte-exact by construction)
  3 composite tool    inside server     never leaves the process
                                        (no tool boundary crossed)
```

Rejected as *the* answer rather than a control: composite tool
(`run_pipeline`). It is real and useful — fastest, atomic, trivially
correct — but from the client's view it is one call with zero
inter-tool hops, so "передача данных между инструментами" never happens
at the MCP layer. Building it anyway (the handlers already exist, so it
costs ~20 lines) makes that visible instead of asserted.

Rejected: spreading `search`/`summarize`/`save_to_file` across three
servers. Cross-server composition would exercise `srv__tool`
namespacing, but day 17 already proved that; one `pipeline` server keeps
the demo focused. Also rejected: reusing `py-tools`/`tracker` for the
stages — wrong semantics, muddies the reading. Taken further after the
first implementation: the inherited demo servers left the registry
entirely (files deleted, watcher + «сводка» UI removed with them) —
fewer subprocesses at startup, no node dependency, and no stray tools
for the lane-1 model to pick instead of the chain.

### Fidelity via recorded hashes, not stored results

To check "did stage N+1 receive stage N's output intact" after the fact
the checker needs the full previous output — but `meta.tool_calls`
stores only a truncated `preview`. Options:

- **Store the full result in meta** — works, but bloats every
  assistant message and contradicts the spec's preview-only intent.
- **Have each pipeline tool echo a hash of its input** — works only for
  pipeline tools; couples tools to the experiment.
- **Adapter records `result_len` + `result_sha256` per call**
  (chosen) — ~4 lines in the existing trace append, generic to all
  tools, tiny metadata. Fidelity per hop is then
  `sha256(next.arguments.text) == prev.result_sha256`, computable from
  meta alone by UI or checker — including on restored transcripts.

### `summarize` is LLM-backed inside the MCP tool, with an offline fallback

The tool builds a lazy OpenAI-compatible client for deepseek
(`DEEPSEEK_API_KEY`) — an MCP tool that itself calls a model, which is
a bonus finding ("tools aren't limited to dumb functions"). Lazy init
matters: the SDK rejects an empty `api_key` at construction, so the
client is built on first call, not at import (same gotcha as day 3's
`get_client`). With no key it falls back to a deterministic extractive
summary (first N sentences / char budget) — keeps the pipeline and
`offline_check.py` fully offline. Alternative considered: pure
extractive always — simpler but drops the bonus finding and makes the
"process" stage a glorified slice.

### Lane 2 is a thin synchronous endpoint

`POST /api/pipeline {query, name?}` runs three `hub.call_tool` calls
sequentially inside the request handler (`ThreadingHTTPServer` gives us
a thread; `run_coroutine_threadsafe` into the hub loop is the existing
bridge) and streams NDJSON:

```
{"type":"stage","i":0,"tool":"search","input":{...},"output":"...","sha256":...}
{"type":"stage","i":1,"tool":"summarize","input":{...},"output":"..."}
{"type":"stage","i":2,"tool":"save_to_file","input":{...},"output":"..."}
{"type":"done","ok":true,"verdict":"exact","path":"out/x.txt"}
```

First stage error → no later stages run, `done.ok=false` carries the
stage index (honest errors are data, per the repo's convention).
Rejected: running the lane inside an agent turn (that is lane 1) or as
a background job (no need — the chain is seconds, not minutes).

### Corpus and output

`day19/data/` ships a few committed UTF-8 text files (real prose —
e.g. notes on MCP/agent topics — sized so `search` output is
non-trivial, several hundred chars, which is exactly where the LLM
lane's retyping fidelity gets interesting). `save_to_file` writes to
`day19/out/` (gitignored generated output), sanitizing `name` to a safe
basename. Rejected: web search for `search` — needs an API/key and is
non-deterministic, breaking the offline check.

### Frontend

A «пайплайн» card on the page offers: query input, «запустить
пайплайн» (lane 2, streams stage boxes), a composite «композитный»
button (lane 3 via `/api/mcp/call` → `run_pipeline`, one box + n/a
badge), and the suggested chat prompt for lane 1 as copyable text —
lane 1 itself renders through the existing `tool_call` phases, plus a
fidelity badge computed from `meta.tool_calls`
(`sha256` of the recorded `arguments` vs `result_sha256` — a ~15-line
client-side hash). No new streaming machinery.

`MAX_TOOL_ROUNDS = 5` already accommodates the 3-hop chain — unchanged.

## Risks / Trade-offs

- **The model may not chain on the first prompt** (or chain with odd
  arguments) → the card ships a tested suggested prompt; deepseek
  models are tool-call-verified live, glm untested on this box (401
  history) — the demo model default is `deepseek-v4-flash`. If a model
  flubs the chain, that is itself reportable behavior, not a crash.
- **Lane 1 fidelity will often be `differs`** — that is the *finding*,
  not a bug: the model legitimately re-serializes large text.
  Mitigation for confusion: the badge labels it «модель переписала
  данные» with the diff sizes, not a red error.
- **LLM-backed `summarize` adds latency/cost inside a tool call** →
  acceptable for a demo; documented; the fallback path keeps tests and
  offline runs deterministic.
- **Registry trim is deliberately not a spec delta**: the `mcp-tools`
  requirement covers the registry *mechanism*, which is unchanged;
  which servers a day ships is folder content (day18/ still carries
  all four). A MODIFIED delta would also have to carry forward the
  earlier days' ship-list scenarios verbatim — false for this folder —
  so `mcp-tools` stays untouched.
- **Two writers to `day19/out/`** (lane 2 endpoint + tool via lane 1/3):
  same sanitized-basename writes, no locking — concurrent same-name
  writes could clobber → acceptable for a demo; names include the
  query-derived default so collisions are unlikely.
