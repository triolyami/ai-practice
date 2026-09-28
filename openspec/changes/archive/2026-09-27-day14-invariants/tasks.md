# Tasks

## 1. Skeleton: day14/ from day12, stripped

- [x] 1.1 Copy day12 → day14 (server.py, agent.py, storage.py, tokens.py, config.py, frontend/ incl. package.json+lock, offline_check.py); delete profiles.py, memory.py, memory/, profiles/, pipeline machinery; verify no references to profiles/memory/workspaces remain (`grep -ri "profile\|memory\|pipeline\|workspace" day14 --include="*.py" -l` shows only intentional leftovers)
- [x] 1.2 Renumber: server port 7872, vite dev port 5184, localStorage keys day14-*-v1, DB path day14/data/; update strings mentioning day12 → day14; append `day14/frontend/node_modules/`, `day14/server.log`, `day14/data/` to root .gitignore; verify `git status` shows no day14 junk files

## 2. invariants.py — file store + lint

- [x] 2.1 Implement `day14/invariants.py`: parse files (`# Name`, `## Section` `- k: v`, `## Проверки` `- бан: re` / `- бан-код: re`), `list_invariants()` / `read_invariant(slug)` (re-reads disk) / `write_invariant` / `delete_invariant`, caps mirroring profiles.py; verify `read_invariant` returns sections + compiled checks + broken-check marks
- [x] 2.2 Implement `lint_reply(text, checks)` → hits list (scope ban scans whole reply, ban_code scans fenced blocks incl. lang tag, `ОТКАЗ` prefix exempt); `render_invariants_message(set)` builds the system block with refusal protocol; verify with unit checks: prose mention of banned lib passes ban_code, fenced code hit fails, ОТКАЗ reply exempt, bad regex marked broken not fatal

## 3. agent.py — binding, modes, enforce loop

- [x] 3.1 Remove memory/profile/pipeline logic (extractor, covered, layers→{short} only or drop layers entirely per minimal diff); add `invariant_id`, `enforce` (off|prompt|enforce, default prompt) to `__init__`/`configure`/`snapshot`/`from_snapshot`; `_request()` injects the invariants system block; verify snapshot roundtrip keeps binding+mode
- [x] 3.2 Implement the enforce loop in send_stream: after reply, lint when bound+mode!=off; `prompt` → meta.violations marked, commit normally; `enforce` → emit `violation` event with attempt content, retry once with feedback system note, second failure → synthesized ОТКАЗ committed with meta.synthesized/attempts/blocked_attempts; ОТКАЗ replies commit as refusals; verify offline_check fake-client scenarios pass (slip→retry→clean, double violation→synthesized, ОТКАЗ no-lint, off mode untouched)

## 4. server.py + storage.py

- [x] 4.1 Port 7872; remove profile/memory endpoints; add `GET /api/invariants`, `GET /api/invariant?id=`, `PUT /api/invariant`, `POST /api/invariant/delete`; parse_config accepts `invariant` (slug or '') + `enforce` (validated mode); NDJSON gains `violation` event; verify curl: list/get/put/delete + chat with enforce mode
- [x] 4.2 storage.py: `sessions.invariant_id` + `sessions.enforce` columns (drop profile_id/covered/workspace leftovers); verify save/load roundtrip

## 5. Frontend

- [x] 5.1 ProfilesPanel → InvariantsPanel (list + raw-md editor + template + delete + bound badge); composer chip «инварианты: X ▾» dropdown; SettingsPanel enforce seg (выкл/промпт/жёсткий); verify UI renders + API calls hit new endpoints
- [x] 5.2 Chat: badges (отказ/нарушение/заблокировано/проверено), blocked-attempt collapsed block, `violation` event handling in useChat (current message flips to blocked, retry streams into a new assistant message); ContextDiagram segment инварианты; MetaLine shows set+mode+attempts; composer probes row (4 conflict presets); verify in dev or via dist build

## 6. Seeds, README, checks

- [x] 6.1 Commit `day14/invariants/android-mvi.md` + `dostavka-msk.md` seeds + template constant; verify they parse (list_invariants returns both with checks)
- [x] 6.2 Write `day14/offline_check.py` covering: file roundtrip, parser caps, broken regex, lint scopes, ОТКАЗ exemption, enforce retry paths, binding/mode persistence, synthesized refusal; verify all pass with fake client (no API)
- [x] 6.3 Write `day14/README.md`: task text, architecture (request composition, lint scopes, refusal protocol, enforce loop), probe scenario for the user's live run, decisions+rejected; verify renders and commands work
- [x] 6.4 Build frontend (`npm run build` in day14/frontend, dist committed); smoke: server starts on 7872, GET / serves page, /api/invariants lists seeds; document results
