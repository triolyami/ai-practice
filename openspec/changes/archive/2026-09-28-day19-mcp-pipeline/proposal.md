# Proposal

## Why

Day 19 task (verbatim):

> День 19. Композиция MCP-инструментов
>
> Создайте несколько MCP-инструментов, например:
>
> 👉 search
> 👉 summarize
> 👉 saveToFile
>
> Реализуйте пайплайн:
>
> 👉 первый инструмент получает данные
> 👉 второй — обрабатывает
> 👉 третий — сохраняет результат
>
> Проверьте:
>
> 👉 автоматическое выполнение цепочки
> 👉 корректность передачи данных между инструментами
>
> Результат:
>
> Автоматический пайплайн из нескольких MCP-инструментов

MCP tools are isolated by design — a tool cannot call another tool.
Composition is a **host-side** concern: whoever holds the MCP sessions
carries one tool's output into the next tool's arguments. Day 17 already
built the machinery for this (bounded tool-call loop, hub, per-call
trace in `meta.tool_calls`), so a `search → summarize → save_to_file`
chain is three tool rounds in one turn. The day's open question is not
"can it chain" but **who orchestrates and at what fidelity** — which is
exactly the task's «корректность передачи данных» check.

Decisions taken with the user during exploration:

- Build **two orchestration lanes side by side** (the comparison):
  1. **LLM-orchestrated** — a chat prompt makes the model chain the
     tools itself via the existing loop. Automatic, flexible, but data
     round-trips through the model's context: the model re-types one
     tool's output as the next tool's arguments — lossy by design.
  2. **Code-orchestrated** — a pipeline endpoint calls the three tools
     in sequence through the hub and pipes each output verbatim into the
     next input. Automatic AND byte-exact.
- Add a **composite tool as a negative control** (lane 3): a meta-tool
  `run_pipeline` on the server that calls the three handlers internally.
  The client sees one call, zero inter-tool hops — demonstrating that
  server-side "composition" never crosses a tool boundary, so the task's
  data-passing check literally does not apply to it. It is cheap (~the
  handlers already exist) and sharpens the finding.
- `summarize` is **LLM-backed inside the MCP tool** (deepseek, whose key
  is verified working) with a deterministic extractive fallback when no
  key is configured — an MCP tool that itself calls a model is a bonus
  finding.

## What Changes

- New `day19/` folder, base copied forward from day18 (agent loop, hub,
  SQLite, React chat UI) — slimmed to the task: `MCP_SERVERS` keeps
  only `pipeline`, the day-17/18 demo servers (py-tools, ts-tools,
  tracker, scheduler), their files, the scheduler watcher and the
  «сводка» pinned chat are removed.
- New stdio MCP server `pipeline` (the single `MCP_SERVERS` entry) with
  four tools:
  - `search(query, limit?)` — deterministic grep over a committed
    `day19/corpus/` corpus; returns matched chunks as text.
  - `summarize(text)` — LLM-backed (deepseek) when `DEEPSEEK_API_KEY`
    is set; otherwise a deterministic extractive summary (first-N
    sentences), so the pipeline runs fully offline.
  - `save_to_file(name, text)` — writes `day19/out/<name>.txt`
    (name sanitized), returns path + byte count.
  - `run_pipeline(query)` — the composite negative control: calls the
    three handlers internally in one tool call.
- New endpoint `POST /api/pipeline {query, name?}` — the
  code-orchestrated lane: three sequential `hub.call_tool` calls,
  streaming NDJSON `stage` events (input/output per hop) + `done` with a
  fidelity verdict.
- New fidelity check, applied per lane: compare what stage N emitted
  with what stage N+1 actually received (`search` output vs `summarize`'s
  `text` argument, `summarize` output vs `save_to_file`'s `text`
  argument). For lane 1 the data comes from the persisted
  `meta.tool_calls` trace; for lane 2 it is exact by construction and
  reported as such; lane 3 reports «no inter-tool hops to check».
- Frontend: a «пайплайн» card — query input, «запустить пайплайн»
  (lane 2 button) plus a copyable chat prompt for lane 1; three stage
  boxes (search → summarize → save) with in/out previews and a fidelity
  badge (exact / differs / not-applicable); the composite lane shown as
  a single box. Lane 1 chains render through the existing `tool_call`
  phase UI — no new streaming machinery.
- `day19/offline_check.py` — the day's verification, no network:
  in-process hub calls the chain end-to-end, code-lane fidelity is
  byte-exact, composite lane reports no hops, LLM-lane fidelity verdict
  derives correctly from a fake `meta.tool_calls` trace.
- `day19/README.md` per repo convention (ru).

## Capabilities

### New Capabilities
- `mcp-pipeline`: multi-tool composition — the pipeline tool set
  (search/summarize/save_to_file/run_pipeline), the two host-side
  orchestration lanes (LLM-driven chain, code-driven chain), and the
  per-lane data-passing fidelity check.

### Modified Capabilities
- `agent-tool-calling`: the persisted `meta.tool_calls` trace gains
  `result_len` / `result_sha256` / `hop_exact` fields — the fidelity
  evidence for the LLM-orchestrated lane.

`mcp-tools` is deliberately untouched: the registry mechanism is
unchanged and which servers ship is per-day folder content — the
earlier days' servers still exist in their own folders.

## Impact

- **Code**: new `day19/` tree (copy of day18 minus the demo servers,
  watcher and «сводка» UI, plus `pipeline_server.py`, pipeline endpoint
  in `server.py`, frontend additions, corpus under `corpus/`). No
  edits to day18 or earlier folders.
- **APIs**: `POST /api/pipeline` added; existing `/api/chat`,
  `/api/mcp`, `/api/mcp/call` unchanged.
- **Dependencies**: none new — stdlib server + existing `mcp` SDK;
  LLM-backed `summarize` reuses the existing OpenAI-compatible client.
- **Env**: optional `DEEPSEEK_API_KEY` (root `.env`, already present);
  without it `summarize` degrades to extractive mode.
