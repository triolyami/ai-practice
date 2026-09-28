# Proposal

## Why

Day 20 task: «Orchestration MCP» — register several MCP servers, let the
agent pick the right tool, route requests correctly, and run a long
interaction flow that uses tools from different servers, verifying
selection and call order. Days 17–19 already built every piece in
isolation (multi-server registry, tool-calling agent, fidelity trace);
this day recombines them and adds the one thing missing: a scenario
that forces tools from different servers into one dependent chain, plus
a programmatic verdict on whether the model picked and ordered them
correctly.

## What Changes

- New `day20/` app: copy of the day19 stack (agent + MCP hub + stdlib
  server + chat frontend) with `MCP_SERVERS` restored to four stdio
  servers — `pipeline`, `tracker`, `scheduler`, plus `py-tools` as a
  semantic distractor (`notes_add` vs tracker issues tests real tool
  selection, not just "called something").
- `MAX_TOOL_ROUNDS` 5 → 10: a 5+ hop flow of dependent calls cannot
  batch and would hit the old ceiling.
- New `flow.py`: canned multi-server scenario(s) + a pure `check(trace)`
  verifier — expected order as subsequence, minimum distinct servers,
  forbidden distractor tools.
- New `flow_run.py` CLI: posts a scenario to `/api/chat`, prints the
  tool trace and the verdict. No new server endpoints.
- `offline_check.py` gains `check()` tests on synthetic traces.

## Capabilities

### New Capabilities
- `mcp-orchestration`: long cross-server flows driven by the agent —
  server/tool selection from descriptions, correct call order under
  data dependencies, and a programmatic verdict over the trace
  (subsequence match, server coverage, distractor rejection, hop
  fidelity via existing `hop_exact` hashes).

### Modified Capabilities
<!-- None: existing specs describe their own dayN apps; day20 is a new
     self-contained app that reuses the machinery. -->

## Impact

- New folder `day20/`; files copied from day19 and day18 (no edits to
  those days). Frontend: wholesale copy, sed-level edits (title, port
  7876→7877, vite 5188→5189, storage prefix), one `npm run build`.
- No new dependencies. Tracker/scheduler/pipeline servers reuse day18/19
  code verbatim; databases regenerate under `day20/data/`.
