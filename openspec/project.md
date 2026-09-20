# Project: ChalengProject

Homework repo for an AI-engineering course (task texts arrive in Russian).
The course runs ~7 weeks, 5 tasks per week, one topic per week. Weeks 1–2
(days 1–10) are done and live as one folder per task: `day1/` … `day10/`,
plus `lab/` (an interactive offshoot of day 2).

## How work is organized

- One task = one OpenSpec **change**. The change folder
  (`openspec/changes/<slug>/`) holds the proposal (task text + scope),
  design (decisions + rejected alternatives), tasks checklist, and spec
  deltas. On archive it becomes the dated day record.
- `openspec/specs/` is the current truth for whatever is still evolving.
  Days 1–10 are finished snapshots — they are NOT retro-spec'd.
- Per-day `README.md` keeps run instructions and human notes; the spec
  deltas carry the behavioral contract.

## Conventions

- Python 3, stdlib-first: HTTP servers are hand-rolled (`server.py` per day,
  one port per day, starting at 7860). Frontend = Vite + React 19 with
  `dist/` committed so servers work without Node; dev ports 5173+.
- LLM access via OpenAI-compatible APIs: Z.ai (`glm-*`) and DeepSeek;
  keys in repo-root `.env` (NEVER committed, never printed — `.env.example`
  is the template). Config per day is a small self-contained `config.py`.
- Chat/streaming endpoints use NDJSON (`start`/`delta`/`done` events);
  per-day localStorage namespaces (`dayN-*-v1`).
- Every task is a comparison experiment: consider the plausible approaches
  (prompt vs API param, library vs stdlib, strategies, …), compare them,
  recommend one with reasons — but the task text defines the deliverable;
  never drift beyond it.
